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

from adelia.db import AsyncSessionLocal
from adelia.models import EvidenceChunk, EvidenceSource
from adelia.workers.embed import embed_texts

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


def main() -> None:
    """CLI entry: python -m adelia.enrichment.evidence_loader."""
    logging.basicConfig(level=logging.INFO)
    sources, chunks = asyncio.run(load_seed_if_empty())
    print(f"Loaded {sources} sources, {chunks} chunks (0,0 = already populated)")


if __name__ == "__main__":
    main()
