from dataclasses import dataclass
from typing import Any
from uuid import UUID

import sqlalchemy as sa

from adelia.db import AsyncSessionLocal
from adelia.models import Chunk, Document


@dataclass
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    user_id: UUID
    content: str                 # small-chunk content
    parent_content: str | None   # expanded parent chunk content (None if no parent found)
    entity_ids: list[str]
    raw_quote_hint: str          # first ~80 chars of content for footnote preview
    page: int | None
    embedding_distance: float
    document_deleted_at: Any = None  # for filter verification in tests


async def retrieve_relevant_chunks(
    *,
    user_id: UUID,
    query_embedding: list[float],
    top_k: int = 8,
) -> list[RetrievedChunk]:
    """Vector-similarity search over chunks (pgvector cosine), filtered to
    user's documents that are not soft-deleted. Returns up to top_k results
    with their parent-chunk content expanded for context.

    Args:
        user_id: tenant filter.
        query_embedding: 1024-dim vector from mistral-embed.
        top_k: number of small chunks to retrieve.

    Returns:
        Ordered list (most similar first) of RetrievedChunk. parent_content
        is None for v0.1 — true parent-chunk persistence deferred to v0.1.1
        once briefing generator (M5) needs it. Today's small chunks already
        carry enough context for chat (350-token windows).
    """
    async with AsyncSessionLocal() as session:
        # Join chunks → documents to enforce soft-delete filter at the SQL layer.
        # Use pgvector cosine distance — lower is more similar.
        distance_expr = Chunk.embedding.cosine_distance(query_embedding)
        stmt = (
            sa.select(
                Chunk.id.label("chunk_id"),
                Chunk.document_id.label("document_id"),
                Chunk.user_id.label("user_id"),
                Chunk.content,
                Chunk.chunk_metadata.label("metadata"),
                distance_expr.label("distance"),
                Document.deleted_at.label("doc_deleted_at"),
            )
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Chunk.user_id == user_id,
                Document.deleted_at.is_(None),
            )
            .order_by(distance_expr.asc())
            .limit(top_k)
        )
        result = await session.execute(stmt)
        rows = list(result.all())

        retrieved: list[RetrievedChunk] = []
        for row in rows:
            meta = row.metadata or {}
            entity_ids = list(meta.get("entity_ids") or [])
            content = row.content
            retrieved.append(
                RetrievedChunk(
                    chunk_id=row.chunk_id,
                    document_id=row.document_id,
                    user_id=row.user_id,
                    content=content,
                    parent_content=None,  # v0.1.1 carry-over
                    entity_ids=entity_ids,
                    raw_quote_hint=content[:80],
                    page=meta.get("page"),
                    embedding_distance=float(row.distance) if row.distance is not None else 0.0,
                    document_deleted_at=row.doc_deleted_at,
                )
            )
        return retrieved
