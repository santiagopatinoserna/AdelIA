"""Pure unit tests for Apple Health export.xml parser."""
from __future__ import annotations

from datetime import date
from pathlib import Path


from adelia.ingestion.apple_health_parser import (
    APPLE_HEALTH_TYPES,
    count_records,
    parse_health_records,
)


_FIXTURE = Path(__file__).parent / "fixtures" / "ingestion" / "apple_health_sample.xml"


def test_parser_yields_supported_records_only():
    records = list(parse_health_records(str(_FIXTURE)))
    # 9 supported Records in sample (1 unsupported HKQuantityTypeIdentifierUnsupportedTypeXYZ dropped)
    assert len(records) == 9


def test_parser_maps_apple_type_to_adelia_name():
    records = list(parse_health_records(str(_FIXTURE)))
    names = {r.name for r in records}
    assert "weight" in names
    assert "glucose" in names
    assert "bp_systolic" in names
    assert "bp_diastolic" in names
    assert "heart_rate" in names
    assert "steps" in names
    assert "active_calories" in names


def test_parser_preserves_value_as_string():
    """Preserve precision — don't auto-cast to float (lossy for e.g. 78.4)."""
    records = list(parse_health_records(str(_FIXTURE)))
    weight = next(r for r in records if r.name == "weight")
    assert weight.value == "78.4"
    assert isinstance(weight.value, str)


def test_parser_extracts_unit_and_source():
    records = list(parse_health_records(str(_FIXTURE)))
    glucose = next(r for r in records if r.name == "glucose")
    assert glucose.unit == "mg/dL"
    assert glucose.source_name == "Dexcom G7"


def test_parser_extracts_event_date():
    records = list(parse_health_records(str(_FIXTURE)))
    glucose = next(r for r in records if r.apple_type == "HKQuantityTypeIdentifierBloodGlucose")
    assert glucose.event_date == date(2026, 5, 18)


def test_parser_builds_raw_quote_with_verbatim_components():
    records = list(parse_health_records(str(_FIXTURE)))
    glucose = next(r for r in records if r.name == "glucose")
    # raw_quote MUST be reconstructible for citation purposes
    assert "HKQuantityTypeIdentifierBloodGlucose" in glucose.raw_quote
    assert "142" in glucose.raw_quote
    assert "mg/dL" in glucose.raw_quote
    assert "Dexcom G7" in glucose.raw_quote


def test_parser_drops_unsupported_types_silently():
    """HKQuantityTypeIdentifierUnsupportedTypeXYZ is in the sample but not in APPLE_HEALTH_TYPES map → dropped."""
    records = list(parse_health_records(str(_FIXTURE)))
    apple_types_seen = {r.apple_type for r in records}
    assert "HKQuantityTypeIdentifierUnsupportedTypeXYZ" not in apple_types_seen


def test_parser_respects_max_records_cap():
    records = list(parse_health_records(str(_FIXTURE), max_records=3))
    assert len(records) == 3


def test_count_records_matches_parse_length():
    parsed_count = len(list(parse_health_records(str(_FIXTURE))))
    counted = count_records(str(_FIXTURE))
    assert counted == parsed_count


def test_parser_handles_missing_value_attribute_gracefully():
    """If a Record has no value attribute, parser should skip it without raising."""
    import io

    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<HealthData>
  <Record type="HKQuantityTypeIdentifierBodyMass" startDate="2025-01-01 00:00:00 +0000" value="80" unit="kg"/>
  <Record type="HKQuantityTypeIdentifierBodyMass" startDate="2025-01-02 00:00:00 +0000" unit="kg"/>
  <Record type="HKQuantityTypeIdentifierBodyMass" startDate="2025-01-03 00:00:00 +0000" value="81" unit="kg"/>
</HealthData>
"""
    stream = io.BytesIO(xml)
    records = list(parse_health_records(stream))
    assert len(records) == 2  # middle record dropped (no value)


def test_apple_health_types_subset_covers_v01_priorities():
    """Sanity check that v0.1 subset covers the critical biometrics."""
    critical_types = {
        "HKQuantityTypeIdentifierBodyMass",
        "HKQuantityTypeIdentifierBloodGlucose",
        "HKQuantityTypeIdentifierBloodPressureSystolic",
        "HKQuantityTypeIdentifierBloodPressureDiastolic",
        "HKQuantityTypeIdentifierHeartRate",
        "HKQuantityTypeIdentifierStepCount",
    }
    assert critical_types.issubset(APPLE_HEALTH_TYPES.keys())
