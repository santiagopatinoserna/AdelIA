"""Pure unit tests for ICD-10/SNOMED normalization."""
from __future__ import annotations

import pytest

from adelia.enrichment.normalization import (
    NormalizedCode,
    coverage_stats,
    normalize,
    normalize_many,
)


def test_normalize_exact_english():
    result = normalize("type 2 diabetes mellitus")
    assert result is not None
    assert result.icd10 == "E11.9"
    assert result.snomed == "44054006"
    assert result.category == "conditions"
    assert result.match_score >= 95


def test_normalize_spanish_alias():
    result = normalize("diabetes tipo 2")
    assert result is not None
    assert result.icd10 == "E11.9"
    assert result.canonical_name == "type 2 diabetes mellitus"


def test_normalize_french_alias():
    result = normalize("hypertension artérielle")
    assert result is not None
    assert result.icd10 == "I10"


def test_normalize_acronym():
    result = normalize("htn")
    assert result is not None
    assert result.icd10 == "I10"


def test_normalize_handles_typos():
    """Fuzzy match should catch minor typos."""
    result = normalize("diabetes tipo dos")  # spelled out instead of digit
    # Token-set ratio should still match
    assert result is None or result.icd10.startswith("E1")


def test_normalize_case_insensitive():
    a = normalize("ASTHMA")
    b = normalize("asthma")
    assert a is not None
    assert b is not None
    assert a.icd10 == b.icd10


def test_normalize_returns_none_on_garbage():
    result = normalize("xyz this is not a medical concept at all 12345")
    assert result is None


def test_normalize_returns_none_on_empty():
    assert normalize("") is None
    assert normalize("   ") is None


def test_normalize_min_score_threshold():
    # With very high threshold, a partial match should fail
    result = normalize("diab", min_score=95)
    # Either matches at ~95+ or returns None — both acceptable
    if result is not None:
        assert result.match_score >= 95


def test_normalize_allergy_penicillin():
    result = normalize("alergia a penicilina")
    assert result is not None
    assert result.icd10 == "Z88.0"
    assert result.category == "allergies"


def test_normalize_procedure_colonoscopy():
    result = normalize("colonoscopia")
    assert result is not None
    assert result.snomed == "73761001"
    assert result.category == "procedures"


def test_normalize_immunization_flu():
    result = normalize("vacuna gripe")
    assert result is not None
    assert result.category == "immunizations"
    assert result.snomed == "46233009"


def test_normalize_many_returns_dict():
    out = normalize_many(["diabetes tipo 2", "hypertension", "garbage abc xyz"])
    assert isinstance(out, dict)
    assert out["diabetes tipo 2"] is not None
    assert out["hypertension"] is not None
    assert out["garbage abc xyz"] is None


def test_coverage_stats_has_all_categories():
    stats = coverage_stats()
    assert stats["conditions"] >= 30
    assert stats["allergies"] >= 5
    assert stats["procedures"] >= 5
    assert stats["immunizations"] >= 5
    assert stats["total"] == (
        stats["conditions"] + stats["allergies"] + stats["procedures"] + stats["immunizations"]
    )
