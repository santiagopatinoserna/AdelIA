"""Reference ranges: the adult rows still work, and a baby is never one.

`age_months` became a required argument on 2026-08-31 (audit 3.5): v0.1
compared every value against an adult range, which in an app about babies is
wrong in both directions at once. The adult assertions below therefore all
pass ADULT, and the pediatric block underneath pins the five cases the audit
named.
"""
from __future__ import annotations

import pytest

from adelia.enrichment.lab_ranges import (
    ADULT_AGE_MONTHS as ADULT,
    STANDARD_AGE_BANDS,
    coverage_count,
    evaluate,
    get_reference_range,
)


def test_get_reference_range_hba1c():
    r = get_reference_range("hba1c", age_months=ADULT)
    assert r is not None
    assert r.unit == "%"
    assert r.low == 4.0
    assert r.high == 5.6


def test_get_reference_range_sex_specific_creatinine_male_vs_female():
    male = get_reference_range("creatinine", age_months=ADULT, sex="M")
    female = get_reference_range("creatinine", age_months=ADULT, sex="F")
    assert male is not None and female is not None
    assert male.high == 1.3
    assert female.high == 1.1


def test_get_reference_range_unknown_returns_none():
    assert get_reference_range("xyz123 not a real lab", age_months=ADULT) is None


def test_evaluate_normal_hba1c():
    status = evaluate("hba1c", 5.2, age_months=ADULT)
    assert status is not None
    assert status.flag == "normal"
    assert status.zone_label == "normal"


def test_evaluate_prediabetes_hba1c():
    status = evaluate("HbA1c", 6.0, age_months=ADULT)
    assert status is not None
    # 6.0 is > 5.6 → flag should be 'high'
    assert status.flag == "high"
    assert status.zone_label == "prediabetes"


def test_evaluate_diabetes_hba1c():
    status = evaluate("hemoglobin a1c", 7.5, age_months=ADULT)
    assert status is not None
    assert status.flag == "high"
    assert status.zone_label == "diabetes"


def test_evaluate_low_value():
    status = evaluate("hemoglobin", 8.0, age_months=ADULT, sex="F")
    assert status is not None
    assert status.flag == "low"


def test_evaluate_spanish_alias():
    status = evaluate("hemoglobina", 14.5, age_months=ADULT, sex="M")
    assert status is not None
    assert status.canonical_name == "hemoglobin"
    assert status.flag == "normal"


def test_evaluate_string_value_parsed():
    status = evaluate("glucose", "85", age_months=ADULT)
    assert status is not None
    assert status.flag == "normal"


def test_evaluate_invalid_value_returns_none():
    assert evaluate("hba1c", "not a number", age_months=ADULT) is None


def test_evaluate_hypertension_zones():
    # Stage 1 hypertension: 130-139
    status = evaluate("bp_systolic", 135, age_months=ADULT)
    assert status is not None
    assert status.zone_label == "stage_1_hypertension"


def test_evaluate_severe_hypertension():
    status = evaluate("bp_systolic", 200, age_months=ADULT)
    assert status is not None
    assert status.zone_label == "hypertensive_crisis"


def test_evaluate_psa_borderline():
    status = evaluate("PSA", 5.2, age_months=ADULT)
    assert status is not None
    assert status.zone_label == "borderline"


def test_evaluate_returns_unit_in_interpretation():
    status = evaluate("vitamin d", 18, age_months=ADULT)
    assert status is not None
    assert status.zone_label == "deficient"
    assert "ng/mL" in status.interpretation or "ng/ml" in status.interpretation.lower()


def test_coverage_at_least_25_labs():
    assert coverage_count() >= 25


def test_evaluate_vital_temperature_fever():
    status = evaluate("body temperature", 38.5, age_months=ADULT)
    assert status is not None
    assert status.zone_label == "fever"


# ---------------------------------------------------------------------------
# Pediatric bands (audit 3.5)
#
# The five cases the audit named, each against the guideline that supplies
# the band. Every one of them was wrong before: three false alarms, one false
# reassurance, and one that could not be computed at all.
# ---------------------------------------------------------------------------


def test_heart_rate_130_at_6_months_is_normal_not_tachycardia():
    """ERC 2021 table 2: 100-180 bpm at that age. The adult row said 60-100."""
    status = evaluate("frecuencia cardíaca", 130, age_months=6)
    assert status is not None
    assert status.flag == "normal"
    assert status.range.age_band == "1-12m"


def test_hemoglobin_11_at_9_months_is_normal_not_low():
    """WHO 2024: the anaemia cutoff at 6-23 months is 10.5 g/dL, not 12.0."""
    status = evaluate("hemoglobina", 11.0, age_months=9)
    assert status is not None
    assert status.flag == "normal"
    assert status.range.low == 10.5


def test_white_cells_13_at_2_months_is_inside_the_nice_band():
    """NICE NG143 1.5.4/1.5.6: <5 or >15 x10^9/l is the actionable range."""
    status = evaluate("leucocitos", 13.0, age_months=2)
    assert status is not None
    assert status.flag == "normal"
    assert status.range.low == 5.0 and status.range.high == 15.0


def test_38_degrees_at_2_months_is_not_a_low_grade_fever():
    """The false reassurance that mattered most: NICE NG143 1.2.12 puts this
    baby in the HIGH RISK group, and the adult row called it 'low_grade'."""
    status = evaluate("temperatura", 38.0, age_months=2)
    assert status is not None
    assert status.flag == "high"
    assert status.zone_label == "fiebre_alto_riesgo_menor_3_meses"
    assert "low_grade" not in (status.zone_label or "")


def test_38_degrees_at_8_months_is_fever_without_the_under_3_months_label():
    status = evaluate("temperatura", 38.0, age_months=8)
    assert status is not None
    assert status.zone_label == "fiebre"


@pytest.mark.parametrize("name,value,age", [
    ("hba1c", 5.2, 9),          # no pediatric band exists for HbA1c
    ("psa", 1.0, 24),
    ("hemoglobina", 11.0, 3),   # WHO gives no cutoff under 6 months
])
def test_no_pediatric_band_returns_none_instead_of_the_adult_range(name, value, age):
    assert evaluate(name, value, age_months=age) is None


def test_sex_overrides_never_reach_a_child():
    """No pediatric guideline loaded here splits by sex, so a sex-specific
    adult bound must not follow a value into a pediatric band."""
    male = evaluate("hemoglobina", 11.0, age_months=9, sex="M")
    female = evaluate("hemoglobina", 11.0, age_months=9, sex="F")
    assert male is not None and female is not None
    assert male.range.low == female.range.low == 10.5
    assert male.range.sex is None


def test_every_pediatric_band_names_its_source():
    """A band with no guideline behind it is an invented number."""
    for name in ("heart rate", "temperatura", "leucocitos", "hemoglobina",
                 "spo2", "frecuencia respiratoria"):
        for age in (0, 2, 8, 18, 40, 100):
            ref = get_reference_range(name, age_months=age)
            if ref is not None:
                assert ref.source, f"{name} at {age} months has a band with no source"


def test_the_standard_band_vocabulary_is_declared():
    labels = [b[0] for b in STANDARD_AGE_BANDS]
    assert labels == ["0-1m", "1-12m", "1-2a", "2-5a", "5-12a", "adulto"]
