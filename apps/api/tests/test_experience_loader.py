"""The experience fixture reaches the database as its own tier.

What other mothers report goes through the same table and the same embedding
pipeline as the clinical corpus (one retrieval engine, one card component),
but every row says what it is: `tier = 'experience'`. The default of the
column is 'evidence', so the rows loaded before the column existed, and every
evidence_*.json file, keep meaning what they meant.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from adelia.enrichment.experience_loader import (
    EXPERIENCE_DIR,
    experience_entries_as_sources,
    load_experience_file,
)

from tests.pg_gate import PG_AVAILABLE

needs_pg = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

ES_FILE = EXPERIENCE_DIR / "experiences_es.json"
TEST_PREFIX = "EXPERIENCE-TEST-"


def test_the_experience_dir_is_its_own_glob_not_the_evidence_one():
    """main.py loads `enrichment/data/evidence_*.json`; the experience files
    live elsewhere so the clinical loader never picks them up by accident."""
    assert EXPERIENCE_DIR.name == "experience"
    assert not list(EXPERIENCE_DIR.glob("evidence_*.json"))
    assert ES_FILE.exists()


def test_entries_become_sources_tagged_experience_in_every_field_that_matters():
    data = json.loads(ES_FILE.read_text(encoding="utf-8"))
    sources = experience_entries_as_sources(data)
    assert len(sources) == len(data["entries"])
    for entry, src in zip(data["entries"], sources, strict=True):
        assert src["tier"] == "experience"
        assert src["source_type"] == "experience"
        # Never 'pediatrics': the answering path filters on that tag, and the
        # tier column is the second lock, not the only one.
        assert src["specialties"] == ["experience"]
        assert src["title"] == entry["title"]
        assert src["organization"] == entry["author"]
        assert src["publication_year"] == entry["year"]
        assert src["url"] == entry["url"]
        assert src["language"] == "es"
        # One chunk per entry: the summary is what the model reads and what the
        # parent sees, in our own words.
        assert src["chunks"] == [entry["summary"]]


def test_a_file_that_does_not_declare_the_experience_tier_is_refused():
    with pytest.raises(ValueError, match="tier"):
        experience_entries_as_sources({"_meta": {"tier": "evidence"}, "entries": []})


@pytest.fixture
async def clean_experience_rows():
    from adelia.db import AsyncSessionLocal

    async def _sweep():
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM evidence_sources WHERE title LIKE :p"), {"p": f"{TEST_PREFIX}%"}
            )
            await session.commit()

    await _sweep()
    yield
    await _sweep()


def _test_file(tmp_path: Path, n: int = 2) -> Path:
    data = json.loads(ES_FILE.read_text(encoding="utf-8"))
    data["entries"] = data["entries"][:n]
    for e in data["entries"]:
        e["title"] = f"{TEST_PREFIX}{e['title']}"
    path = tmp_path / "experiences_test.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


@needs_pg
async def test_loading_writes_experience_rows_and_is_idempotent(tmp_path, clean_experience_rows,
                                                                 monkeypatch):
    from adelia.db import AsyncSessionLocal
    from adelia.enrichment import evidence_loader

    monkeypatch.setattr(evidence_loader, "SOURCE_PACING_S", 0)
    fake = AsyncMock(side_effect=lambda texts: [[0.0] * 1024 for _ in texts])
    path = _test_file(tmp_path)
    with patch("adelia.enrichment.evidence_loader.embed_texts", fake):
        first = await load_experience_file(path)
        second = await load_experience_file(path)
    assert first == (2, 2)
    assert second == (0, 0)

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text(
            "SELECT es.tier, es.source_type, es.specialties, ec.language "
            "FROM evidence_sources es JOIN evidence_chunks ec ON ec.source_id = es.id "
            "WHERE es.title LIKE :p"
        ), {"p": f"{TEST_PREFIX}%"})).all()
    assert len(rows) == 2
    for tier, source_type, specialties, language in rows:
        assert tier == "experience"
        assert source_type == "experience"
        assert specialties == ["experience"]
        assert language == "es"


@needs_pg
async def test_rows_loaded_as_evidence_default_to_the_evidence_tier():
    """Nothing already in the table changed meaning when the column arrived."""
    from adelia.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        bad = await session.scalar(text(
            "SELECT count(*) FROM evidence_sources "
            "WHERE source_type <> 'experience' AND tier <> 'evidence'"
        ))
    assert bad == 0


@needs_pg
async def test_the_database_rejects_a_tier_it_does_not_know(clean_experience_rows):
    from adelia.db import AsyncSessionLocal
    from adelia.models import EvidenceSource

    async with AsyncSessionLocal() as session:
        session.add(EvidenceSource(
            source_type="reference", title=f"{TEST_PREFIX}bad-tier", organization="TEST",
            specialties=["pediatrics"], language="es", tier="rumour",
        ))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
