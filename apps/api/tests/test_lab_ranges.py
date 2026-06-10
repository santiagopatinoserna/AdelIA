"""Pure unit tests for lab reference range lookup + evaluation."""
from __future__ import annotations


from adelia.enrichment.lab_ranges import (
    coverage_count,
    evaluate,
    get_reference_range,
)


def test_get_reference_range_hba1c():
    r = get_reference_range("hba1c")
    assert r is not None
    assert r.unit == "%"
    assert r.low == 4.0
    assert r.high == 5.6


def test_get_reference_range_sex_specific_creatinine_male_vs_female():
    male = get_reference_range("creatinine", sex="M")
    female = get_reference_range("creatinine", sex="F")
    assert male is not None and female is not None
    assert male.high == 1.3
    assert female.high == 1.1


def test_get_reference_range_unknown_returns_none():
    assert get_reference_range("xyz123 not a real lab") is None


def test_evaluate_normal_hba1c():
    status = evaluate("hba1c", 5.2)
    assert status is not None
    assert status.flag == "normal"
    assert status.zone_label == "normal"


def test_evaluate_prediabetes_hba1c():
    status = evaluate("HbA1c", 6.0)
    assert status is not None
    # 6.0 is > 5.6 → flag should be 'high'
    assert status.flag == "high"
    assert status.zone_label == "prediabetes"


def test_evaluate_diabetes_hba1c():
    status = evaluate("hemoglobin a1c", 7.5)
    assert status is not None
    assert status.flag == "high"
    assert status.zone_label == "diabetes"


def test_evaluate_low_value():
    status = evaluate("hemoglobin", 8.0, sex="F")
    assert status is not None
    assert status.flag == "low"


def test_evaluate_spanish_alias():
    status = evaluate("hemoglobina", 14.5, sex="M")
    assert status is not None
    assert status.canonical_name == "hemoglobin"
    assert status.flag == "normal"


def test_evaluate_string_value_parsed():
    status = evaluate("glucose", "85")
    assert status is not None
    assert status.flag == "normal"


def test_evaluate_invalid_value_returns_none():
    assert evaluate("hba1c", "not a number") is None


def test_evaluate_hypertension_zones():
    # Stage 1 hypertension: 130-139
    status = evaluate("bp_systolic", 135)
    assert status is not None
    assert status.zone_label == "stage_1_hypertension"


def test_evaluate_severe_hypertension():
    status = evaluate("bp_systolic", 200)
    assert status is not None
    assert status.zone_label == "hypertensive_crisis"


def test_evaluate_psa_borderline():
    status = evaluate("PSA", 5.2)
    assert status is not None
    assert status.zone_label == "borderline"


def test_evaluate_returns_unit_in_interpretation():
    status = evaluate("vitamin d", 18)
    assert status is not None
    assert status.zone_label == "deficient"
    assert "ng/mL" in status.interpretation or "ng/ml" in status.interpretation.lower()


def test_coverage_at_least_25_labs():
    assert coverage_count() >= 25


def test_evaluate_vital_temperature_fever():
    status = evaluate("body temperature", 38.5)
    assert status is not None
    assert status.zone_label == "fever"
