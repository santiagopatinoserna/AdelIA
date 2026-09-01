# apps/api/adelia/agent/pediatrics.py
"""Growth percentiles and the vaccination calendar, by country.

Vaccines (audit 2026-08-31, item 3.9)
-------------------------------------
The v0.1 rule was `due_month <= age + 1`, "overdue" being `due_month < age`,
against a hard-coded Spanish list and nothing else. Run on a healthy,
fully-vaccinated child it returned, at 18 and at 24 months, all ten vaccines
and marked all ten "overdue", including the hepatitis B dose given at birth.
That is a false alarm on the most anxiety-loaded subject a parent has, drawn
on screen as an amber card, and it teaches the parent to ignore the warning
on the day one really is missing.

Three things changed:

* **The window is bounded on both sides.** Pending means the dose is due now
  or within the next two months (`age <= due_month <= age + 2`), not "any
  dose this child has ever been old enough for".
* **The record is consulted.** A dose is only overdue if it is late AND the
  `immunization` entities the app already extracts from the child's own
  vaccination card do not show it. `administered` carries those names.
* **The calendar follows the country, not the interface language.** Spain
  and France differ at almost every age (meningococcus B at 2/4/12 months in
  Spain, 3/5/12 in France; ACWY at 12 years in Spain, 6 and 12 months in
  France), so answering a French parent from the Spanish calendar is simply
  the wrong answer.

Optional doses (the birth hepatitis B dose, which Spain gives only to babies
of HBsAg-positive mothers; rotavirus, whose number of doses depends on the
product) are never reported as overdue: `routine: false` in the data files.
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

_DATA = Path(__file__).parent / "data"

#: The calendars that exist. A locale is not a country, but until Profile
#: carries one it is the only signal the agent has.
SUPPORTED_COUNTRIES = ("ES", "FR")
DEFAULT_COUNTRY = "ES"
_LOCALE_COUNTRY = {"es": "ES", "fr": "FR", "en": "ES"}

#: How far ahead "próximas vacunas" looks, in months.
UPCOMING_WINDOW_MONTHS = 2


@lru_cache(maxsize=1)
def _growth() -> dict:
    return json.loads((_DATA / "who_growth.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=len(SUPPORTED_COUNTRIES))
def _calendar(country: str) -> dict:
    path = _DATA / f"vaccines_{country.lower()}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def country_for_locale(locale: str | None) -> str:
    return _LOCALE_COUNTRY.get((locale or "").lower(), DEFAULT_COUNTRY)


def resolve_country(country: str | None, locale: str | None = None) -> str:
    if country and country.upper() in SUPPORTED_COUNTRIES:
        return country.upper()
    return country_for_locale(locale)


def calendar_meta(country: str) -> dict:
    """Which calendar was used, so the answer can name it."""
    return _calendar(resolve_country(country)).get("_meta", {})


# maps a percentile band edge to its numeric percentile
_BANDS = [("p3", 3), ("p15", 15), ("p50", 50), ("p85", 85), ("p97", 97)]


def growth_percentile(*, metric: str, value: float, age_months: int, sex: str) -> int | None:
    table = _growth().get(metric, {}).get(sex)
    if not table:
        return None
    row = next((r for r in table if r["age_months"] == age_months), None)
    if row is None:
        return None
    # piecewise-linear interpolation across the known band edges
    edges = [(row[k], p) for k, p in _BANDS]
    if value <= edges[0][0]:
        return edges[0][1]
    if value >= edges[-1][0]:
        return edges[-1][1]
    for (v_lo, p_lo), (v_hi, p_hi) in zip(edges, edges[1:]):
        if v_lo <= value <= v_hi:
            frac = (value - v_lo) / (v_hi - v_lo) if v_hi != v_lo else 0.0
            return round(p_lo + frac * (p_hi - p_lo))
    return None


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFD", text or "")
    folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    return " ".join(folded.lower().split())


def doses_recorded(
    administered: Iterable[str] | None, calendar: dict
) -> dict[str, int]:
    """How many doses of each vaccine group the child's record shows.

    `administered` is the free text of the child's `immunization` entities,
    as extracted from the vaccination card ("Hexavalente 2ª dosis",
    "Prevenar 13", "Bexsero"). Matching is by alias substring on an
    accent-folded string, and the count per group is what decides whether
    dose 3 is covered, so three "Infanrix hexa" lines cover doses 1 to 3.

    Deliberately generous: a missed match marks a given dose as pending,
    which costs a parent a glance at the card. The opposite mistake, calling
    a missing dose "done", is the one that matters.
    """
    counts: dict[str, int] = {}
    if not administered:
        return counts
    groups: dict[str, list[str]] = {}
    for entry in calendar.get("vaccines", []):
        groups.setdefault(entry["group"], [])
        for alias in entry.get("match", []):
            groups[entry["group"]].append(_normalize(alias))
    for raw in administered:
        text = _normalize(raw)
        if not text:
            continue
        for group, aliases in groups.items():
            if any(alias and alias in text for alias in aliases):
                counts[group] = counts.get(group, 0) + 1
    return counts


@dataclass(frozen=True)
class VaccineStatus:
    name: str
    due_month: int
    dose: int
    #: "due" = due now or within the window; "overdue" = past due with no record.
    status: str
    note: str | None = None

    @property
    def overdue(self) -> bool:
        return self.status == "overdue"

    def as_dict(self) -> dict:
        out = {
            "name": self.name,
            "due_month": self.due_month,
            "dose": self.dose,
            "status": self.status,
            "overdue": self.overdue,
        }
        if self.note:
            out["note"] = self.note
        return out


def vaccine_status(
    *,
    age_months: int,
    country: str | None = None,
    locale: str | None = None,
    administered: Iterable[str] | None = None,
) -> list[VaccineStatus]:
    """Doses due soon, plus doses genuinely missing from the record."""
    resolved = resolve_country(country, locale)
    calendar = _calendar(resolved)
    recorded = doses_recorded(administered, calendar)
    seen: dict[str, int] = {}
    out: list[VaccineStatus] = []
    for entry in calendar.get("vaccines", []):
        group = entry["group"]
        seen[group] = seen.get(group, 0) + 1
        covered = recorded.get(group, 0) >= entry["dose"]
        due = entry["due_month"]
        if covered:
            continue
        if age_months <= due <= age_months + UPCOMING_WINDOW_MONTHS:
            out.append(VaccineStatus(entry["name"], due, entry["dose"], "due", entry.get("note")))
        elif due < age_months and entry.get("routine", True):
            out.append(VaccineStatus(entry["name"], due, entry["dose"], "overdue", entry.get("note")))
    return out


def due_vaccines(
    *,
    age_months: int,
    country: str | None = None,
    locale: str | None = None,
    administered: Iterable[str] | None = None,
) -> list[dict]:
    """`vaccine_status` as plain dicts, the shape the agent tool renders."""
    return [
        s.as_dict()
        for s in vaccine_status(
            age_months=age_months, country=country, locale=locale, administered=administered
        )
    ]
