"""What evidence_loader.load_sources holds while it loads, and what it stores.

Two questions the 2026-11-06 batch (316 sources, 805 chunks) raised before it
went to data/ (docs/corpus/CANDIDATOS_2026_11_06.md, 18):

* Boot now loads the corpus beside the server (adelia/main.py), so the load
  shares the pool with the mothers' requests for minutes. No session may stay
  open across the call to Mistral: a 429 there waits up to 77 s
  (EMBED_RETRY_DELAYS), and a connection held through it is the pool
  exhaustion that already caused 500s once (CLAUDE.md).
* The translated sources carry original_language, original_title and
  original_license, three keys the table does not have. The loader builds a
  source from named fields only, so it must store the source and drop those
  three, on a real Postgres, not only on paper.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from adelia.enrichment import evidence_loader as loader
from adelia.models import EvidenceSource
from tests.pg_gate import PG_AVAILABLE

needs_pg = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")
DATA_DIR = loader._SEED_FILE.parent
TEST_TITLE_PREFIX = "LOADER-TEST-"


class _Session:
    """Counts how many sessions are open; enough of AsyncSession for load_sources."""

    open = 0
    added: list = []

    async def __aenter__(self):
        type(self).open += 1
        return self

    async def __aexit__(self, *exc):
        type(self).open -= 1

    async def execute(self, _stmt):
        return SimpleNamespace(all=lambda: [("Ya cargada",)])

    def add(self, obj):
        type(self).added.append(obj)

    async def flush(self):
        for obj in type(self).added:
            if isinstance(obj, EvidenceSource) and obj.id is None:
                obj.id = uuid4()

    async def commit(self):
        return None


async def test_no_session_is_open_while_a_source_is_embedded(monkeypatch):
    _Session.open, _Session.added = 0, []
    seen: list[int] = []

    async def _embed(texts):
        seen.append(_Session.open)
        return [[0.0] * 1024 for _ in texts]

    monkeypatch.setattr(loader, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(loader, "embed_with_retry", _embed)
    monkeypatch.setattr(loader, "SOURCE_PACING_S", 0)
    sources = [
        {"source_type": "guideline", "title": "Ya cargada", "chunks": ["x"]},
        {"source_type": "guideline", "title": "Nueva A", "chunks": ["a", "b"]},
        {"source_type": "guideline", "title": "Nueva B", "chunks": ["c"]},
    ]
    assert await loader.load_sources(sources, "evidence_x.json") == (2, 3)
    assert seen == [0, 0], "a session held across the call to Mistral"
    assert _Session.open == 0


def _translated_source() -> dict:
    """A real translated source of the batch, with the third key added: no
    page is both translated and in the public domain (those are the CDC's, in
    English), and the loader has to drop the three together."""
    for path in sorted(DATA_DIR.glob("evidence_*_2026_11.json")):
        for s in json.loads(path.read_text(encoding="utf-8"))["sources"]:
            if s.get("original_title") and s.get("original_language"):
                return {**s, "original_license": "public_domain"}
    raise AssertionError("no promoted source has original_title")


async def _sweep():
    from adelia.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM evidence_sources WHERE title LIKE :p"), {"p": f"{TEST_TITLE_PREFIX}%"}
        )
        await session.commit()


@needs_pg
async def test_a_translated_source_is_stored_and_its_original_fields_are_dropped(
    tmp_path, monkeypatch
):
    from adelia.db import AsyncSessionLocal

    source = {**_translated_source()}
    title = f"{TEST_TITLE_PREFIX}{uuid4().hex[:6]} {source['title']}"[:500]
    source["title"] = title
    path = tmp_path / "evidence_probe_2026_11.json"
    path.write_text(json.dumps({"sources": [source]}, ensure_ascii=False), encoding="utf-8")

    async def _embed(texts):
        return [[0.0] * 1024 for _ in texts]

    monkeypatch.setattr(loader, "embed_with_retry", _embed)
    monkeypatch.setattr(loader, "SOURCE_PACING_S", 0)
    await _sweep()
    try:
        assert await loader.load_evidence_file(path) == (1, len(source["chunks"]))
        async with AsyncSessionLocal() as session:
            row = (await session.execute(
                text("SELECT language, license, tier FROM evidence_sources WHERE title = :t"),
                {"t": title},
            )).one()
            chunks = (await session.execute(
                text("SELECT ec.language FROM evidence_chunks ec JOIN evidence_sources es "
                     "ON es.id = ec.source_id WHERE es.title = :t ORDER BY ec.chunk_index"),
                {"t": title},
            )).scalars().all()
        # The chunks are Spanish: stemmed as Spanish (migration 0021), whatever
        # language the page was read in.
        assert tuple(row) == ("es", source["license"], "evidence")
        assert chunks == ["es"] * len(source["chunks"])
        # A second boot changes nothing.
        assert await loader.load_evidence_file(path) == (0, 0)
    finally:
        await _sweep()
