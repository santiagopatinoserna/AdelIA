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
