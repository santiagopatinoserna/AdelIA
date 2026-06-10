"""Pure unit tests for 23andMe parser + variant matching."""
from __future__ import annotations

from pathlib import Path


from adelia.enrichment.genomics import (
    catalog_stats,
    evaluate_genotype,
    match_variants,
    parse_23andme_raw,
)


_FIXTURE = Path(__file__).parent / "fixtures" / "genomics_sample.txt"


def test_parse_skips_comments_and_no_calls():
    with _FIXTURE.open() as f:
        genotypes = list(parse_23andme_raw(f))
    # 17 data rows, but 1 is no-call (--), so 16 yielded
    rsids = [g.rsid for g in genotypes]
    assert "rs0000" not in rsids  # no-call dropped
    assert "rs4244285" in rsids


def test_parse_extracts_genotype_uppercase():
    with _FIXTURE.open() as f:
        genotypes = {g.rsid: g for g in parse_23andme_raw(f)}
    assert genotypes["rs4244285"].genotype == "AA"
    assert genotypes["rs7903146"].genotype == "CT"


def test_evaluate_genotype_homozygous():
    count, zyg = evaluate_genotype("AA", ["A"])
    assert count == 2
    assert zyg == "homozygous"


def test_evaluate_genotype_heterozygous():
    count, zyg = evaluate_genotype("AT", ["A"])
    assert count == 1
    assert zyg == "heterozygous"


def test_evaluate_genotype_absent():
    count, zyg = evaluate_genotype("GG", ["A"])
    assert count == 0
    assert zyg == "absent"


def test_evaluate_genotype_multi_allele_risk():
    """Risk could be specified as both A and T (e.g. transitions)."""
    count, zyg = evaluate_genotype("AT", ["A", "T"])
    assert count == 2
    assert zyg == "homozygous"


def test_match_variants_finds_cyp2c19_pgx():
    with _FIXTURE.open() as f:
        genotypes = list(parse_23andme_raw(f))
    hits = match_variants(genotypes)
    cyp2c19 = next((h for h in hits if h.gene == "CYP2C19"), None)
    assert cyp2c19 is not None
    assert cyp2c19.user_genotype == "AA"
    assert cyp2c19.zygosity == "homozygous"
    assert cyp2c19.category == "pharmacogenomics"


def test_match_variants_apoe_heterozygous():
    with _FIXTURE.open() as f:
        genotypes = list(parse_23andme_raw(f))
    hits = match_variants(genotypes)
    apoe = next((h for h in hits if h.rsid == "rs429358"), None)
    assert apoe is not None
    assert apoe.zygosity == "heterozygous"
    assert apoe.gene == "APOE"


def test_match_variants_absent_variants_omitted():
    with _FIXTURE.open() as f:
        genotypes = list(parse_23andme_raw(f))
    hits = match_variants(genotypes)
    # rs1799963 (G allele risk) — fixture has GG → no A allele → absent → not in hits
    f2 = next((h for h in hits if h.rsid == "rs1799963"), None)
    assert f2 is None


def test_match_variants_sorted_pgx_first():
    with _FIXTURE.open() as f:
        genotypes = list(parse_23andme_raw(f))
    hits = match_variants(genotypes)
    if len(hits) < 2:
        return  # skip if fixture has too few
    # First hits should be pharmacogenomics (highest priority category)
    first_categories = [h.category for h in hits[:3]]
    assert first_categories[0] == "pharmacogenomics"


def test_catalog_stats_returns_summary():
    stats = catalog_stats()
    assert stats["variants_total"] >= 15
    assert "pharmacogenomics" in stats["by_category"]
    assert "disease_risk" in stats["by_category"]


def test_match_includes_actionability_text():
    """Every hit should carry the actionability text for downstream display."""
    with _FIXTURE.open() as f:
        genotypes = list(parse_23andme_raw(f))
    hits = match_variants(genotypes)
    for h in hits:
        assert h.actionability
        assert len(h.actionability) > 20  # not empty placeholder
