import json
from pathlib import Path

import pytest

from adelia.agent.pediatrics import (
    SUPPORTED_COUNTRIES,
    calendar_meta,
    doses_recorded,
    due_vaccines,
    growth_percentile,
    resolve_country,
    vaccine_status,
)



def test_percentile_midpoint_is_around_50():
    # value equal to the P50 row for that age/sex → ~50th percentile
    p = growth_percentile(metric="weight", value=5.6, age_months=2, sex="M")
    assert p is not None and 40 <= p <= 60


def test_percentile_out_of_table_returns_none():
    assert growth_percentile(metric="weight", value=5.0, age_months=999, sex="M") is None


def test_the_growth_table_is_whos_month_by_month_from_birth_to_two_years():
    """Until 2026-11-25 the table held six months for boys and four for girls, and
    several P3/P85/P97 were the ±2 SD and +1 SD values of WHO's z-score tables
    (boys at birth: 4.4 kg is +2 SD, P97 is 4.3). Most weighings got no percentile
    and the rest a wrong edge. Now: WHO's percentile tables, every month 0-24
    (weight tab_wfa_*_p_0_5, length tab_lhfa_*_p_0_2), spot-checked here."""
    data = json.loads((Path(__file__).parents[1] / "adelia" / "agent" / "data"
                       / "who_growth.json").read_text(encoding="utf-8"))
    for metric in ("weight", "height"):
        for sex in ("M", "F"):
            rows = data[metric][sex]
            assert [r["age_months"] for r in rows] == list(range(25)), (metric, sex)
            assert all(r["p3"] < r["p15"] < r["p50"] < r["p85"] < r["p97"] for r in rows)
    assert data["weight"]["M"][0] == {
        "age_months": 0, "p3": 2.5, "p15": 2.9, "p50": 3.3, "p85": 3.9, "p97": 4.3}
    assert data["weight"]["F"][4] == {
        "age_months": 4, "p3": 5.1, "p15": 5.6, "p50": 6.4, "p85": 7.3, "p97": 8.1}
    assert data["height"]["M"][12]["p50"] == 75.7
    assert data["height"]["F"][24]["p50"] == 86.4  # length lying down, as until 2 years
    # Every month now has an answer.
    assert growth_percentile(metric="weight", value=6.4, age_months=4, sex="F") == 50


def test_due_vaccines_returns_list():
    v = due_vaccines(age_months=2)
    assert isinstance(v, list) and all("name" in x and "due_month" in x for x in v)


# ---------------------------------------------------------------------------
# Vaccines (audit 3.9)
#
# The v0.1 rule returned every dose the child had ever been old enough for
# and marked them all overdue: at 18 and 24 months, ten out of ten, hepatitis
# B at birth included. It never read the `immunization` entities the app
# extracts from the child's own card, and it only knew the Spanish calendar.
# ---------------------------------------------------------------------------
_DATA = Path(__file__).resolve().parents[1] / "adelia" / "agent" / "data"

# A fully vaccinated Spanish 18-month-old, written the way a vaccination card
# reads: brand names, ordinals, accents and all.
FULLY_VACCINATED_ES = [
    "Hepatitis B", "Hexavalente 1ª dosis", "Hexavalente 2ª dosis", "Hexavalente 3ª dosis",
    "Prevenar 20 1ª", "Prevenar 20 2ª", "Prevenar 20 3ª",
    "Bexsero 1ª", "Bexsero 2ª", "Bexsero 3ª",
    "Meningococo C 1ª", "Meningococo C 2ª",
    "Triple vírica", "Varicela", "Rotateq 1", "Rotateq 2",
]


def test_a_well_vaccinated_18_month_old_has_nothing_overdue():
    """The acceptance criterion of item 3.9, verbatim."""
    statuses = vaccine_status(age_months=18, country="ES", administered=FULLY_VACCINATED_ES)
    assert [s for s in statuses if s.overdue] == []


@pytest.mark.parametrize("age", [2, 6, 12, 15, 18, 24])
def test_the_pending_window_never_looks_more_than_two_months_ahead(age):
    for s in vaccine_status(age_months=age, country="ES"):
        if s.status == "due":
            assert age <= s.due_month <= age + 2


def test_the_birth_hepatitis_b_dose_is_never_reported_overdue():
    """Spain gives it only to babies of HBsAg-positive mothers, so calling it
    overdue for everyone was a false alarm on every single child."""
    statuses = vaccine_status(age_months=18, country="ES")
    assert not any(s.overdue and "Hepatitis B" in s.name for s in statuses)


def test_missing_doses_are_still_reported():
    """Over-correcting would be just as bad: a child with nothing recorded
    must still be told what is missing."""
    statuses = vaccine_status(age_months=18, country="ES", administered=[])
    assert any(s.overdue for s in statuses)


def test_a_partial_record_covers_only_the_doses_it_shows():
    two_doses = ["Hexavalente 1ª", "Hexavalente 2ª"]
    statuses = vaccine_status(age_months=15, country="ES", administered=two_doses)
    hexa = [s for s in statuses if "Hexavalente" in s.name]
    assert [s.dose for s in hexa] == [3]


def test_doses_are_counted_per_group_not_per_string():
    calendar = json.loads((_DATA / "vaccines_es.json").read_text(encoding="utf-8"))
    counts = doses_recorded(["Infanrix hexa", "Vaxelis", "Hexavalente 3ª"], calendar)
    assert counts["hexavalente"] == 3


# --- the calendar follows the country, not the interface language ----------


def test_both_calendars_exist_and_declare_their_authority():
    for country in SUPPORTED_COUNTRIES:
        meta = calendar_meta(country)
        assert meta["country"] == country
        assert meta["calendar"] and meta["authority"] and meta["url"]


def test_france_and_spain_differ_where_the_calendars_differ():
    """Meningococcus B is 2/4/12 months in Spain and 3/5/12 in France, so
    answering a French parent from the Spanish calendar is the wrong answer."""
    def due_months(country, group_word):
        cal = json.loads((_DATA / f"vaccines_{country.lower()}.json").read_text(encoding="utf-8"))
        return [v["due_month"] for v in cal["vaccines"] if group_word in v["group"]]

    assert due_months("ES", "meningococo_b") == [2, 4, 12]
    assert due_months("FR", "meningocoque_b") == [3, 5, 12]


def test_country_falls_back_to_the_locale_then_to_spain():
    assert resolve_country("FR") == "FR"
    assert resolve_country(None, "fr") == "FR"
    assert resolve_country(None, "es") == "ES"
    assert resolve_country("XX", None) == "ES"


def test_every_calendar_entry_can_be_matched_back_from_its_own_name():
    """A vaccine whose own name does not match its alias list can never be
    ticked off a card, so it would be reported overdue forever."""
    for country in SUPPORTED_COUNTRIES:
        cal = json.loads((_DATA / f"vaccines_{country.lower()}.json").read_text(encoding="utf-8"))
        for entry in cal["vaccines"]:
            counts = doses_recorded([entry["name"]], cal)
            assert counts.get(entry["group"], 0) >= 1, f"{country}: {entry['name']}"
