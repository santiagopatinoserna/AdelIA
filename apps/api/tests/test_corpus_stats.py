"""GET /clinical/corpus-stats: the corpus figure comes from the database.

The landing printed "118 fuentes" from a literal while production held 127
sources and 301 chunks (audit 1.1, second time). These tests pin the three
things that keep the figure true: it is counted in the database and not
copied from anywhere, it is public (visitors have no account), and it is
cached so a crowd on the landing does not become a crowd of aggregate queries.

The dev database is shared and its size is whatever earlier runs left, so no
test here asserts an absolute count: they compare against SQL run in the same
test, or against the change caused by rows the test inserts and removes.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from adelia.services import corpus_stats
from tests.pg_gate import PG_AVAILABLE

needs_pg = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

TEST_TITLE_PREFIX = "CORPUS-STATS-TEST-"


@pytest.fixture(autouse=True)
def _fresh_cache():
    corpus_stats.reset_cache()
    yield
    corpus_stats.reset_cache()


async def _sweep():
    from adelia.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM evidence_sources WHERE title LIKE :p"), {"p": f"{TEST_TITLE_PREFIX}%"}
        )
        await session.commit()


@needs_pg
async def test_the_endpoint_is_public_and_matches_the_database(client):
    from adelia.db import AsyncSessionLocal

    resp = await client.get("/clinical/corpus-stats")  # no Authorization header
    assert resp.status_code == 200
    body = resp.json()
    async with AsyncSessionLocal() as session:
        sources = (await session.execute(text("SELECT count(*) FROM evidence_sources"))).scalar_one()
        chunks = (await session.execute(text("SELECT count(*) FROM evidence_chunks"))).scalar_one()
        years = (
            await session.execute(
                text("SELECT min(publication_year), max(publication_year) FROM evidence_sources")
            )
        ).one()
    assert body["sources"] == sources
    assert body["chunks"] == chunks
    assert (body["year_min"], body["year_max"]) == tuple(years)
    assert sum(body["by_type"].values()) == body["sources"]
    # Every type is reported even when empty, so absence never has to be read
    # as a zero by the page.
    assert set(body["by_type"]) == set(corpus_stats.SOURCE_TYPES)


@needs_pg
async def test_the_endpoint_can_be_cached_by_whatever_sits_in_front(client):
    resp = await client.get("/clinical/corpus-stats")
    assert resp.headers["cache-control"] == f"public, max-age={int(corpus_stats.CACHE_TTL_S)}"


@needs_pg
async def test_a_new_source_moves_the_counts_and_the_range():
    """The figure follows the rows: one source with a year, one without."""
    from adelia.db import AsyncSessionLocal
    from adelia.models import EvidenceChunk, EvidenceSource

    await _sweep()
    before = await corpus_stats.get_corpus_stats()
    try:
        async with AsyncSessionLocal() as session:
            dated = EvidenceSource(
                source_type="protocol", title=f"{TEST_TITLE_PREFIX}dated-{uuid4().hex[:6]}",
                organization="TEST", publication_year=2999, specialties=["pediatrics"], language="es",
            )
            undated = EvidenceSource(
                source_type="reference", title=f"{TEST_TITLE_PREFIX}undated-{uuid4().hex[:6]}",
                organization="TEST", publication_year=None, specialties=["pediatrics"], language="es",
            )
            session.add_all([dated, undated])
            await session.flush()
            session.add_all(
                EvidenceChunk(source_id=src.id, content=f"chunk {i}", chunk_index=i, language="es")
                for src in (dated, undated)
                for i in range(2)
            )
            await session.commit()

        # Inside the TTL the old answer is served, which is what the cache is for.
        assert await corpus_stats.get_corpus_stats() == before
        corpus_stats.reset_cache()

        after = await corpus_stats.get_corpus_stats()
        assert after.sources == before.sources + 2
        assert after.chunks == before.chunks + 4
        assert after.by_type["protocol"] == before.by_type["protocol"] + 1
        assert after.by_type["reference"] == before.by_type["reference"] + 1
        assert after.sources_without_year == before.sources_without_year + 1
        assert after.year_max == 2999
    finally:
        await _sweep()


async def test_the_query_runs_once_per_ttl(monkeypatch):
    calls = {"n": 0}
    clock = {"now": 1000.0}

    async def _query():
        calls["n"] += 1
        return corpus_stats.CorpusStats(
            sources=1, chunks=2, year_min=2000, year_max=2001, sources_without_year=0,
            by_type={t: 0 for t in corpus_stats.SOURCE_TYPES},
        )

    monkeypatch.setattr(corpus_stats, "_query", _query)
    monkeypatch.setattr(corpus_stats.time, "monotonic", lambda: clock["now"])

    await corpus_stats.get_corpus_stats()
    clock["now"] += corpus_stats.CACHE_TTL_S - 1
    await corpus_stats.get_corpus_stats()
    assert calls["n"] == 1
    clock["now"] += 2
    await corpus_stats.get_corpus_stats()
    assert calls["n"] == 2


async def test_an_empty_corpus_has_no_year_range(monkeypatch):
    """No sources must give null years, never 0 or a made-up span."""

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

        def one(self):
            return self._rows[0]

        def scalar_one(self):
            return self._rows[0]

    class _Session:
        def __init__(self):
            self._answers = iter([_Result([]), _Result([(None, None, 0)]), _Result([0])])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, _stmt):
            return next(self._answers)

    monkeypatch.setattr(corpus_stats, "AsyncSessionLocal", _Session)
    stats = await corpus_stats._query()
    assert stats.sources == 0 and stats.chunks == 0
    assert stats.year_min is None and stats.year_max is None
    assert stats.sources_without_year == 0
    assert stats.by_type == {t: 0 for t in corpus_stats.SOURCE_TYPES}
