"""Unit tests for evidence_retrieval formatting + seed loader structure.

PG-gated retrieval tests deferred (need real pgvector index). Pure logic tested here.
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from adelia.enrichment.evidence_retrieval import (
    EvidenceMatch,
    evidence_citations_for_response,
    format_evidence_for_prompt,
)


def _fake_match(i: int) -> EvidenceMatch:
    return EvidenceMatch(
        chunk_id=uuid4(),
        source_id=uuid4(),
        source_title=f"Sample Guideline {i}",
        organization="ADA",
        publication_year=2024,
        url=f"https://example.com/g{i}",
        content=f"Clinical evidence snippet number {i}. " * 5,
        chunk_index=0,
        distance=0.2 + (i * 0.05),
    )


def test_format_evidence_empty_returns_empty_string():
    assert format_evidence_for_prompt([]) == ""


def test_format_evidence_has_citation_tags():
    matches = [_fake_match(1), _fake_match(2)]
    out = format_evidence_for_prompt(matches)
    assert "[ev_1]" in out
    assert "[ev_2]" in out
    assert "ADA" in out
    assert "Clinical evidence snippet number 1" in out


def test_format_evidence_preserves_year():
    matches = [_fake_match(1)]
    out = format_evidence_for_prompt(matches)
    assert "2024" in out


def test_citations_for_response_returns_list_of_dicts():
    matches = [_fake_match(1), _fake_match(2)]
    citations = evidence_citations_for_response(matches)
    assert len(citations) == 2
    assert citations[0]["tag"] == "ev_1"
    assert citations[1]["tag"] == "ev_2"
    assert citations[0]["organization"] == "ADA"
    assert citations[0]["url"].startswith("https://")
    assert citations[0]["distance"] >= 0


def test_citations_snippet_truncated():
    """Snippets should be ≤ 280 chars to keep response payload light."""
    matches = [_fake_match(1)]
    citations = evidence_citations_for_response(matches)
    assert len(citations[0]["snippet"]) <= 280


def test_evidence_seed_json_loadable_and_valid():
    """Seed file should parse + have at least 5 sources covering core specialties."""
    seed_path = Path(__file__).parent.parent / "adelia" / "enrichment" / "data" / "evidence_seed.json"
    with seed_path.open() as f:
        data = json.load(f)
    sources = data.get("sources", [])
    assert len(sources) >= 8
    specialties_seen = set()
    for src in sources:
        assert "title" in src
        assert "source_type" in src
        assert src["source_type"] in {"guideline", "paper", "protocol", "reference"}
        assert "chunks" in src
        assert len(src["chunks"]) >= 1
        for chunk_text in src["chunks"]:
            assert len(chunk_text) > 20
        specialties_seen.update(src.get("specialties", []))
    # Core specialties covered in seed
    assert "endocrinology" in specialties_seen
    assert "cardiology" in specialties_seen
    assert "pediatrics" in specialties_seen


def test_evidence_seed_sources_have_urls():
    """Every source must have a URL for citation purposes."""
    seed_path = Path(__file__).parent.parent / "adelia" / "enrichment" / "data" / "evidence_seed.json"
    with seed_path.open() as f:
        data = json.load(f)
    for src in data.get("sources", []):
        assert src.get("url", "").startswith("http")
