"""Pure unit tests for drug interaction checker."""
from __future__ import annotations

import pytest

from adelia.enrichment.drug_interactions import (
    check_interactions,
    check_pair,
    coverage_stats,
    resolve_canonical,
)


def test_resolve_canonical_exact():
    assert resolve_canonical("warfarin") == "warfarin"
    assert resolve_canonical("coumadin") == "warfarin"
    assert resolve_canonical("warfarina") == "warfarin"


def test_resolve_canonical_strips_dosage():
    """'warfarin 5mg' should resolve to canonical 'warfarin'."""
    assert resolve_canonical("warfarin 5mg") == "warfarin"
    assert resolve_canonical("metformin 500mg") == "metformin"


def test_resolve_canonical_unknown_returns_none():
    assert resolve_canonical("xyz_not_a_real_drug") is None
    assert resolve_canonical("") is None


def test_check_pair_warfarin_aspirin_major():
    inter = check_pair("warfarin", "aspirin")
    assert inter is not None
    assert inter.severity == "major"
    assert "bleeding" in inter.mechanism.lower()


def test_check_pair_order_independent():
    a = check_pair("warfarin", "aspirin")
    b = check_pair("aspirin", "warfarin")
    assert a is not None and b is not None
    assert a.severity == b.severity


def test_check_pair_same_drug_returns_none():
    """Drug paired with itself should not be flagged."""
    assert check_pair("warfarin", "warfarin") is None
    assert check_pair("warfarin", "coumadin") is None  # both alias to warfarin


def test_check_pair_no_known_interaction_returns_none():
    """Two known drugs with no documented interaction → None."""
    inter = check_pair("metformin", "levothyroxine")
    assert inter is None


def test_check_pair_unknown_drug_returns_none():
    assert check_pair("warfarin", "xyz_unknown") is None


def test_check_pair_contraindicated_severity():
    """Sildenafil + nitroglycerin is contraindicated (highest severity)."""
    inter = check_pair("sildenafil", "nitroglycerin")
    assert inter is not None
    assert inter.severity == "contraindicated"


def test_check_interactions_bulk_sorted_by_severity():
    meds = ["warfarin", "aspirin", "ibuprofen", "amiodarone", "metformin"]
    found = check_interactions(meds)
    # Multiple interactions expected: warfarin+aspirin, warfarin+ibuprofen,
    # warfarin+amiodarone, aspirin+ibuprofen (none, expected), amiodarone+...
    assert len(found) >= 3
    # All major-level
    for inter in found:
        assert inter.severity in {"contraindicated", "major", "moderate"}
    # Sort order: contraindicated first
    if len(found) > 1:
        from adelia.enrichment.drug_interactions import _SEVERITY_RANK
        for i in range(len(found) - 1):
            assert _SEVERITY_RANK[found[i].severity] <= _SEVERITY_RANK[found[i + 1].severity]


def test_check_interactions_skips_unknown_silently():
    meds = ["warfarin", "aspirin", "xyz_garbage_med"]
    found = check_interactions(meds)
    # warfarin+aspirin should still be flagged
    assert any(inter.drug_a == "aspirin" and inter.drug_b == "warfarin" for inter in found)


def test_check_interactions_brand_and_generic_resolve_same():
    """Coumadin + advil should resolve to warfarin + ibuprofen."""
    a = check_interactions(["coumadin", "advil"])
    b = check_interactions(["warfarin", "ibuprofen"])
    assert len(a) == len(b) == 1
    assert a[0].severity == b[0].severity == "major"


def test_check_interactions_spanish_brand_names():
    """Aspirina + ibuprofeno should resolve via Spanish aliases."""
    found = check_interactions(["warfarina", "aspirina"])
    assert len(found) == 1
    assert found[0].severity == "major"


def test_grapefruit_statin_interaction():
    """Grapefruit (food) + statin is a real interaction in the dataset."""
    inter = check_pair("grapefruit", "simvastatin")
    assert inter is not None
    assert inter.severity == "moderate"


def test_serotonin_syndrome_pair():
    """Tramadol + SSRI → major severity."""
    inter = check_pair("tramadol", "fluoxetine")
    assert inter is not None
    assert inter.severity == "major"
    assert "serotonin" in inter.mechanism.lower()


def test_coverage_stats_returns_counts():
    stats = coverage_stats()
    assert stats["interactions_total"] >= 25
    assert "major" in stats["by_severity"]
    assert "contraindicated" in stats["by_severity"]
