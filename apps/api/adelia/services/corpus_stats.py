"""Public counts of the evidence corpus, read from the database.

Why this exists (audit 1.1): the landing wrote "118 fuentes" by hand in three
language catalogs. The 2026-08-31 audit asked for the figure to be generated;
the fix then only corrected the number and left it a literal, and six weeks
later production held 127 sources and 301 chunks while the page still said 118
and 258. A number typed into a catalog drifts the moment a corpus file is
added, so the landing now asks this module and the catalogs keep only the
sentence around the figure.

The database is the source because it is what retrieval actually searches: a
file that failed to load at boot (a CHECK violation skipped a whole corpus on
2026-08-26) must not be advertised, and counting the JSON files would do
exactly that.

The result is cached in-process for CACHE_TTL_S. The endpoint is public and
the landing reads it on every revalidation, and the corpus only changes on a
deploy, so a few minutes of staleness costs nothing and the aggregate never
runs once per visitor.
"""
from __future__ import annotations

import time

from pydantic import BaseModel
from sqlalchemy import func, select

from adelia.db import AsyncSessionLocal
from adelia.models import EvidenceChunk, EvidenceSource

# Mirror of ck_evidence_sources_type. Every key is always present in the
# answer, with 0 when the type is empty, so a consumer never has to guess
# whether a missing key means "none" or "not reported".
SOURCE_TYPES: tuple[str, ...] = ("guideline", "paper", "protocol", "reference")

CACHE_TTL_S = 300.0


class CorpusStats(BaseModel):
    sources: int
    chunks: int
    # Real range of publication_year, None when no source carries a year.
    year_min: int | None
    year_max: int | None
    # Sources that have no year. They are counted in `sources` but cannot move
    # the range, and the landing must not claim a span they do not support.
    sources_without_year: int
    by_type: dict[str, int]


_cache: tuple[float, CorpusStats] | None = None


def reset_cache() -> None:
    """Forget the cached figure (tests, and anything that edits the corpus)."""
    global _cache
    _cache = None


async def _query() -> CorpusStats:
    # One short session, no network I/O inside it (pool exhaustion already
    # caused 500s once, see CLAUDE.md).
    async with AsyncSessionLocal() as session:
        per_type = (
            await session.execute(
                select(EvidenceSource.source_type, func.count()).group_by(EvidenceSource.source_type)
            )
        ).all()
        years = (
            await session.execute(
                select(
                    func.min(EvidenceSource.publication_year),
                    func.max(EvidenceSource.publication_year),
                    func.count(EvidenceSource.publication_year),
                )
            )
        ).one()
        chunks = (await session.execute(select(func.count()).select_from(EvidenceChunk))).scalar_one()

    by_type = {t: 0 for t in SOURCE_TYPES}
    for source_type, n in per_type:
        by_type[source_type] = n
    sources = sum(by_type.values())
    return CorpusStats(
        sources=sources,
        chunks=chunks,
        year_min=years[0],
        year_max=years[1],
        sources_without_year=sources - years[2],
        by_type=by_type,
    )


async def get_corpus_stats() -> CorpusStats:
    """The corpus counts, recomputed at most once every CACHE_TTL_S seconds."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < CACHE_TTL_S:
        return _cache[1]
    stats = await _query()
    _cache = (now, stats)
    return stats
