"""Every evidence_*.json must satisfy the DB constraints BEFORE boot.

The startup loader swallows exceptions (evidence must never block boot), so a
bad file fails silently in production: a CHECK violation on source_type
skipped an entire 40-source corpus on 2026-08-26 and only the logs knew.
This test makes that mistake impossible to push.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parents[1] / "adelia" / "enrichment" / "data"
# Mirror of ck_evidence_sources_type (alembic 0005_evidence_chunks).
ALLOWED_SOURCE_TYPES = {"guideline", "paper", "protocol", "reference"}
FILES = sorted(DATA_DIR.glob("evidence_*.json"))


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_evidence_file_respects_db_constraints(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    sources = data.get("sources", [])
    assert sources, f"{path.name} has no sources"
    titles = [s["title"] for s in sources]
    assert len(titles) == len(set(titles)), f"{path.name}: duplicate titles (loader is idempotent by title)"
    for s in sources:
        assert s["source_type"] in ALLOWED_SOURCE_TYPES, (
            f"{path.name}: {s['title'][:60]!r} has source_type {s['source_type']!r}; "
            f"allowed: {sorted(ALLOWED_SOURCE_TYPES)}"
        )
        assert s.get("chunks"), f"{path.name}: {s['title'][:60]!r} has no chunks"
        assert len(s["title"]) <= 500
        # Column widths in models.EvidenceSource: a longer value makes the
        # whole file fail to load at boot (StringDataRightTruncationError).
        for field, limit in (("organization", 128), ("url", 1024), ("license", 64), ("language", 8)):
            value = s.get(field) or ""
            assert len(value) <= limit, f"{path.name}: {s['title'][:60]!r} {field} longer than {limit}"


# ---------------------------------------------------------------------------
# The urgent-care corpus (audit 3.4)
#
# The audit's finding was blunt: the corpus did not have a single line about
# urgencies, fever under 3 months or anaphylaxis, while the answering path
# always returned something. This file is what the red-flag detector cites,
# so its shape is part of the safety guarantee, not a nicety.
# ---------------------------------------------------------------------------

URGENCIAS = DATA_DIR / "evidence_urgencias_lactante.json"

# The eight topics the audit named, plus jaundice, each keyed by a word that
# must appear in the title of the source covering it.
REQUIRED_TOPICS = {
    "fiebre en menores de 3 meses": "NG143",
    "deshidratación": "CG84",
    "dificultad respiratoria": "NG9",
    "exantema que no blanquea": "NG240",
    "convulsión febril": "Convulsiones febriles",
    "anafilaxia": "Anafilaxia",
    "sueño seguro": "sueño",
    "atragantamiento": "European Resuscitation Council",
    "ictericia": "Ictericia",
}


def test_the_urgent_care_corpus_exists():
    assert URGENCIAS.exists(), "the red-flag detector cites sources from this file"


@pytest.mark.parametrize("topic,needle", sorted(REQUIRED_TOPICS.items()))
def test_every_urgent_topic_has_a_source_with_at_least_three_chunks(topic, needle):
    data = json.loads(URGENCIAS.read_text(encoding="utf-8"))
    matching = [s for s in data["sources"] if needle in s["title"]]
    assert matching, f"no source covers {topic!r}"
    for source in matching:
        assert len(source["chunks"]) >= 3, f"{topic}: {len(source['chunks'])} chunk(s)"


def test_urgent_care_chunks_are_sized_and_attributed():
    """Every chunk opens with the title and the authors, and stays inside the
    300-900 character window the other corpora use, so retrieval sees one
    idea per fragment and a citation is readable on its own."""
    data = json.loads(URGENCIAS.read_text(encoding="utf-8"))
    for source in data["sources"]:
        head = source["title"].split(" (")[0].split(":")[0][:24]
        for i, chunk in enumerate(source["chunks"]):
            assert 300 <= len(chunk) <= 900, f"{source['title'][:40]} #{i}: {len(chunk)} chars"
            assert "Tema:" in chunk and "Hallazgo:" in chunk, f"{source['title'][:40]} #{i}"
            assert head.split(",")[0][:18] in chunk, f"{source['title'][:40]} #{i} lacks its title"
            assert "—" not in chunk, "no em dashes in user-facing text"


def test_urgent_care_sources_are_pediatric_and_carry_a_url():
    """The answering path filters on the `pediatrics` tag, so an urgent-care
    source without it is a source retrieval will never return."""
    data = json.loads(URGENCIAS.read_text(encoding="utf-8"))
    for source in data["sources"]:
        assert "pediatrics" in source["specialties"], source["title"][:50]
        assert source["url"].startswith("https://"), source["title"][:50]
        assert source["publication_year"] >= 2009
        assert source["language"] == "es"
