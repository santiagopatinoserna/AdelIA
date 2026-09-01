"""Reference ranges, banded by age, with interpretation zones.

Takes an observation name (or alias), a numeric value and the patient's age
in months, and returns the range that applies AT THAT AGE plus a clinically
meaningful label.

Why age is mandatory (audit 2026-08-31, item 3.5)
-------------------------------------------------
v0.1 carried adult ranges and `evaluate()` took no age at all, so in an app
about babies every answer was measured against a grown-up. It failed in both
directions at once:

* false alarm: 130 bpm at 6 months read as "tachycardia" against 60-100, when
  the normal range at that age is 100-180 (ERC 2021, table 2);
  11.0 g/dL of haemoglobin at 9 months read as "low" against 12.0-17.5, when
  the WHO 2024 cutoff at that age is 10.5 g/dL.
* false reassurance, which is the dangerous one: 38.0 C in a 2-month-old read
  as "low_grade_fever", when NICE NG143 1.2.12 puts a child under 3 months at
  38 C or more in the HIGH RISK group.

So `age_months` is a required argument, and an age with no band returns None
rather than falling back to the adult row. "I cannot judge this" is a correct
answer; "normal for an adult" is not an answer about a baby at all.

Each pediatric band names its own primary source in the data file
(enrichment/data/lab_reference_ranges.json): ERC 2021 Paediatric Life Support
for heart and respiratory rate, NICE NG143 for temperature, white cell count
and oxygen saturation, NICE NG9 for the saturation referral threshold, and the
WHO 2024 haemoglobin cutoffs for anaemia.

Adult rows keep their v0.1 source: Mayo Clinic Labs + MedlinePlus +
LabTestsOnline, with sex-specific overrides for ferritin, creatinine, ALT,
AST, hemoglobin and hematocrit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from rapidfuzz import fuzz, process


_DATA_FILE = Path(__file__).parent / "data" / "lab_reference_ranges.json"


#: 18 years, in months: the floor of the "adulto" band in the data file.
ADULT_AGE_MONTHS = 216

#: The band vocabulary the audit asked for. Entries whose guideline uses
#: different cut-offs (WHO haemoglobin at 6 and 24 months, NICE fever at 3 and
#: 6 months) carry those instead; see the data file's `_meta.age_bands`.
STANDARD_AGE_BANDS: tuple[tuple[str, int, int | None], ...] = (
    ("0-1m", 0, 1),
    ("1-12m", 1, 12),
    ("1-2a", 12, 24),
    ("2-5a", 24, 60),
    ("5-12a", 60, 144),
    ("adulto", ADULT_AGE_MONTHS, None),
)


@dataclass(frozen=True)
class AgeBand:
    """One age slice of a reference range, with the guideline it comes from."""

    label: str
    min_months: int
    max_months: int | None
    low: float | None
    high: float | None
    source: str
    zones: tuple[dict, ...] = ()

    def covers(self, age_months: int) -> bool:
        if age_months < self.min_months:
            return False
        return self.max_months is None or age_months < self.max_months


@dataclass(frozen=True)
class _RangeLookup:
    canonical_name: str
    aliases: tuple[str, ...]
    unit: str
    low: float
    high: float
    sex_specific: dict
    zones: tuple[dict, ...]
    age_bands: tuple[AgeBand, ...] = ()

    def band_for(self, age_months: int) -> AgeBand | None:
        for band in self.age_bands:
            if band.covers(age_months):
                return band
        return None


@dataclass(frozen=True)
class ReferenceRange:
    canonical_name: str
    unit: str
    low: float | None
    high: float | None
    sex: Literal["M", "F"] | None = None
    #: Which age band produced this range, e.g. "1-12m". Empty for the
    #: legacy adult-only lookup.
    age_band: str = ""
    #: The guideline the numbers come from, verbatim from the data file.
    source: str = ""


@dataclass(frozen=True)
class RangeStatus:
    """Result of evaluating an observation against its reference range."""

    canonical_name: str
    value: float
    unit: str
    range: ReferenceRange
    flag: Literal["low", "normal", "high"]
    zone_label: str | None = None  # e.g. 'pre-diabetes', 'stage_1_hypertension'
    interpretation: str = ""  # human-readable summary in ES
    age_months: int | None = None


#: What an entry with no `age_bands` gets: its v0.1 numbers, valid from 18
#: years up and NOWHERE else. The 25 labs without a pediatric band (HbA1c,
#: LDL, PSA, troponin, ...) keep working for an adult and correctly answer
#: "I cannot judge this" for a child, which is the whole point of item 3.5.
_ADULT_ONLY_SOURCE = "Mayo Clinic Labs / MedlinePlus / LabTestsOnline (rango de adulto, v0.1)"


def _bands_for(entry: dict) -> tuple[AgeBand, ...]:
    declared = entry.get("age_bands")
    if declared:
        return tuple(
            AgeBand(
                label=b["label"],
                min_months=int(b["min_months"]),
                max_months=None if b.get("max_months") is None else int(b["max_months"]),
                low=None if b.get("low") is None else float(b["low"]),
                high=None if b.get("high") is None else float(b["high"]),
                source=b.get("source", ""),
                zones=tuple(b.get("interpretation_zones", [])),
            )
            for b in declared
        )
    return (
        AgeBand(
            label="adulto",
            min_months=ADULT_AGE_MONTHS,
            max_months=None,
            low=float(entry.get("low", 0)),
            high=float(entry.get("high", 9999)),
            source=_ADULT_ONLY_SOURCE,
            zones=tuple(entry.get("interpretation_zones", [])),
        ),
    )


@lru_cache(maxsize=1)
def _load_ranges() -> tuple[_RangeLookup, ...]:
    with _DATA_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    rows: list[_RangeLookup] = []
    for entry in data.get("ranges", []):
        rows.append(
            _RangeLookup(
                canonical_name=entry["name"],
                aliases=tuple(a.lower() for a in (entry["name"], *entry.get("aliases", []))),
                unit=entry.get("unit", ""),
                low=float(entry.get("low", 0)),
                high=float(entry.get("high", 9999)),
                sex_specific=entry.get("sex_specific", {}),
                zones=tuple(entry.get("interpretation_zones", [])),
                age_bands=_bands_for(entry),
            )
        )
    return tuple(rows)


def _lookup(name: str) -> _RangeLookup | None:
    """Match observation name to a reference range row.

    Strategy: exact alias match first (cheap, avoids false positives like
    'hemoglobin' matching 'hemoglobin a1c'). Falls back to fuzzy
    token_sort_ratio which discriminates by length unlike token_set_ratio.
    """
    q = name.strip().lower()
    if not q:
        return None
    rows = _load_ranges()

    # Phase 1: exact alias match
    for idx, row in enumerate(rows):
        if q in row.aliases:
            return row

    # Phase 2: fuzzy fallback with token_sort_ratio (length-aware)
    all_aliases: list[tuple[str, int]] = []
    for idx, row in enumerate(rows):
        for alias in row.aliases:
            all_aliases.append((alias, idx))

    choices = [a for a, _ in all_aliases]
    best = process.extractOne(q, choices, scorer=fuzz.token_sort_ratio)
    if best is None:
        return None
    matched, score, pos = best
    if score < 80:
        return None
    _, row_idx = all_aliases[pos]
    return rows[row_idx]


def get_reference_range(
    name: str,
    *,
    age_months: int,
    sex: Literal["M", "F"] | None = None,
) -> ReferenceRange | None:
    """The reference range that applies to a patient of this age, or None.

    None means one of two things, and both are answers the caller must
    surface rather than paper over: the observation is unknown, or there is
    no band covering that age. There is deliberately no fallback to the adult
    row: see the module docstring.
    """
    row = _lookup(name)
    if row is None:
        return None

    band = row.band_for(age_months)
    if band is None:
        return None

    low, high, source = band.low, band.high, band.source
    # Sex overrides are adult-only in v0.1: none of the pediatric guidelines
    # loaded here (ERC, NICE, WHO under 15) split their cut-offs by sex, so
    # applying an adult split to a baby would invent a distinction.
    if band.label == "adulto" and sex and sex in row.sex_specific:
        low = float(row.sex_specific[sex]["low"])
        high = float(row.sex_specific[sex]["high"])

    return ReferenceRange(
        canonical_name=row.canonical_name,
        unit=row.unit,
        low=low,
        high=high,
        sex=sex if band.label == "adulto" else None,
        age_band=band.label,
        source=source,
    )


def _zone_label(zones: tuple[dict, ...], value: float) -> str | None:
    for zone in zones:
        if value <= float(zone.get("max", 9999)):
            return zone.get("label")
    return None


def evaluate(
    name: str,
    value: float | str,
    *,
    age_months: int,
    sex: Literal["M", "F"] | None = None,
) -> RangeStatus | None:
    """Evaluate an observation against the band for `age_months`.

    Returns None when the observation is not recognised, when the value is
    not a number, or when no band covers that age. `age_months` is required:
    the whole defect this function had was that it did not know how old the
    patient was (audit 3.5).
    """
    row = _lookup(name)
    if row is None:
        return None

    try:
        v = float(value)
    except (TypeError, ValueError):
        return None

    ref_range = get_reference_range(name, age_months=age_months, sex=sex)
    if ref_range is None:
        return None
    band = row.band_for(age_months)
    assert band is not None  # get_reference_range would have returned None

    zone_label = _zone_label(band.zones, v)

    low, high = ref_range.low, ref_range.high
    if low is not None and v < low:
        flag: Literal["low", "normal", "high"] = "low"
    elif high is not None and v > high:
        flag = "high"
    else:
        flag = "normal"

    bounds = "-".join(str(b) for b in (low, high) if b is not None)
    parts = [f"{row.canonical_name} = {v} {row.unit}"]
    if bounds:
        comparator = "referencia" if low is not None and high is not None else "límite"
        parts.append(f"({comparator} {bounds} {row.unit}, banda {band.label})")
    else:
        parts.append(f"(banda {band.label})")
    if zone_label:
        parts.append(f"[{zone_label}]")
    elif flag != "normal":
        parts.append(f"[{flag}]")

    return RangeStatus(
        canonical_name=row.canonical_name,
        value=v,
        unit=row.unit,
        range=ref_range,
        flag=flag,
        zone_label=zone_label,
        interpretation=" ".join(parts),
        age_months=age_months,
    )


def coverage_count() -> int:
    return len(_load_ranges())
