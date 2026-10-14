"""Load evidence_seed.json into evidence_sources + evidence_chunks (with embeddings).

Idempotent: skips sources whose (title, organization, publication_year) already exist.
Embeddings via mistral-embed (1024-dim, matches existing chunks table).

Usage (offline, after `docker compose up` + alembic upgrade):
    cd apps/api
    uv run python -m adelia.enrichment.evidence_loader
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from sqlalchemy import select

from mistralai.client.errors import MistralError

from adelia.db import AsyncSessionLocal
from adelia.models import EvidenceChunk, EvidenceSource
from adelia.workers.embed import embed_texts

# Boot-time embedding of a whole corpus (100+ chunks) trips Mistral's rate
# limit (429). Back off and retry instead of losing the file; the delays are
# module-level so tests can shrink them.
EMBED_RETRY_DELAYS: tuple[float, ...] = (2.0, 5.0, 10.0, 20.0, 40.0)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# Small pause between sources so a big file does not burst the API.
SOURCE_PACING_S = 0.5


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status in RETRYABLE_STATUS:
        return True
    try:
        msg = str(exc)
    except Exception:  # noqa: BLE001 — some SDK errors cannot be stringified
        return False
    return any(f"Status {s}" in msg or f"status {s}" in msg for s in RETRYABLE_STATUS)


async def embed_with_retry(texts: list[str]) -> list[list[float]]:
    """embed_texts with exponential backoff on 429/5xx; other errors propagate."""
    last: Exception | None = None
    for attempt, delay in enumerate((*EMBED_RETRY_DELAYS, None)):
        try:
            return await embed_texts(texts)
        except MistralError as exc:
            if not _is_retryable(exc) or delay is None:
                raise
            last = exc
            logger.warning("embedding rate-limited/transient (attempt %d), retrying in %.0fs: %s",
                           attempt + 1, delay, type(exc).__name__)
            await asyncio.sleep(delay)
    raise last  # pragma: no cover - loop always returns or raises

logger = logging.getLogger(__name__)

_SEED_FILE = Path(__file__).parent / "data" / "evidence_seed.json"


async def load_seed_if_empty() -> tuple[int, int]:
    """Bulk-load evidence_seed.json into the DB if no sources exist yet.

    Returns: (sources_inserted, chunks_inserted). 0/0 if already loaded.
    """
    with _SEED_FILE.open("r", encoding="utf-8") as f:
        seed = json.load(f)

    async with AsyncSessionLocal() as session:
        existing_count = await session.execute(select(EvidenceSource).limit(1))
        if existing_count.scalar_one_or_none() is not None:
            logger.info("evidence_sources already populated, skipping seed load")
            return 0, 0

        sources_added = 0
        chunks_added = 0

        for src_data in seed.get("sources", []):
            chunks_text = src_data.pop("chunks", [])
            source = EvidenceSource(
                source_type=src_data["source_type"],
                title=src_data["title"],
                organization=src_data.get("organization"),
                publication_year=src_data.get("publication_year"),
                url=src_data.get("url"),
                specialties=src_data.get("specialties", []),
                license=src_data.get("license"),
                language=src_data.get("language", "en"),
            )
            session.add(source)
            await session.flush()
            sources_added += 1

            if not chunks_text:
                continue

            # Batch embed all chunks for this source
            embeddings = await embed_texts(chunks_text)
            for idx, (text_chunk, emb) in enumerate(zip(chunks_text, embeddings, strict=True)):
                chunk = EvidenceChunk(
                    source_id=source.id,
                    content=text_chunk,
                    chunk_index=idx,
                    chunk_metadata={"section": src_data.get("title")},
                    embedding=emb,
                    # Same value as the source above, written explicitly: the
                    # full-text column is generated from it (migration 0021),
                    # and the column default ('en') would stem Spanish text as
                    # English and make it unfindable by the lexical half.
                    language=source.language,
                )
                session.add(chunk)
                chunks_added += 1

        await session.commit()
        logger.info(
            "evidence loaded: %d sources, %d chunks",
            sources_added,
            chunks_added,
        )
        return sources_added, chunks_added


async def load_evidence_file(path: Path) -> tuple[int, int]:
    """Ingest one evidence JSON file additively, idempotent by source title.

    Unlike load_seed_if_empty, this ADDS to whatever is already loaded and
    skips any source whose title already exists — so re-running is safe and
    new topic corpora (e.g. pediatric reflux) can be layered in.

    Returns: (sources_inserted, chunks_inserted).
    """
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(EvidenceSource.title))
        existing_titles = {row[0] for row in existing.all()}

        sources_added = 0
        chunks_added = 0
        for src_data in data.get("sources", []):
            if src_data["title"] in existing_titles:
                continue
            chunks_text = list(src_data.get("chunks", []))
            source = EvidenceSource(
                source_type=src_data["source_type"],
                title=src_data["title"],
                organization=src_data.get("organization"),
                publication_year=src_data.get("publication_year"),
                url=src_data.get("url"),
                specialties=src_data.get("specialties", []),
                license=src_data.get("license"),
                language=src_data.get("language", "en"),
            )
            # Embed BEFORE adding the source: if embedding ultimately fails the
            # source is not left behind without chunks (idempotency is by
            # title, so a half-loaded source would never get its chunks).
            embeddings = await embed_with_retry(chunks_text) if chunks_text else []
            session.add(source)
            await session.flush()
            sources_added += 1
            for idx, (text_chunk, emb) in enumerate(zip(chunks_text, embeddings, strict=True)):
                session.add(EvidenceChunk(
                    source_id=source.id,
                    content=text_chunk,
                    chunk_index=idx,
                    chunk_metadata={"section": src_data["title"]},
                    embedding=emb,
                    language=source.language,  # see load_seed_if_empty
                ))
                chunks_added += 1
            # Commit per source: progress survives a later failure and the
            # next boot resumes from where it stopped.
            await session.commit()
            existing_titles.add(src_data["title"])
            if SOURCE_PACING_S:
                await asyncio.sleep(SOURCE_PACING_S)
        logger.info("evidence file %s: +%d sources, +%d chunks", path.name, sources_added, chunks_added)
        return sources_added, chunks_added


def main() -> None:
    """CLI: python -m adelia.enrichment.evidence_loader [path/to/file.json]

    No argument: seed-if-empty (original). With a file path: additive
    idempotent load of that file.
    """
    import sys

    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 1:
        sources, chunks = asyncio.run(load_evidence_file(Path(sys.argv[1])))
        print(f"Loaded {sources} new sources, {chunks} new chunks from {sys.argv[1]}")
    else:
        sources, chunks = asyncio.run(load_seed_if_empty())
        print(f"Loaded {sources} sources, {chunks} chunks (0,0 = already populated)")


if __name__ == "__main__":
    main()
