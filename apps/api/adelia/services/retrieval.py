from dataclasses import dataclass
from typing import Any
from uuid import UUID

import sqlalchemy as sa

from adelia.db import AsyncSessionLocal
from adelia.models import Chunk, Document

# Parent expansion: rebuild the ~1500-token parent window around each hit
# from document raw_text using sibling chunk offsets. Capped so 8 expanded
# parents stay well inside the LLM context budget.
PARENT_CONTENT_MAX_CHARS = 2500


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
        carries the surrounding ~1500-token parent window rebuilt from the
        document raw_text via sibling chunk offsets (None when offsets or
        raw_text are unavailable). Citations keep the small-chunk content.
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

        parent_windows = await _parent_windows_for(session, rows)

        retrieved: list[RetrievedChunk] = []
        for row in rows:
            meta = row.metadata or {}
            entity_ids = list(meta.get("entity_ids") or [])
            content = row.content
            parent_key = (row.document_id, meta.get("parent_index"))
            retrieved.append(
                RetrievedChunk(
                    chunk_id=row.chunk_id,
                    document_id=row.document_id,
                    user_id=row.user_id,
                    content=content,
                    parent_content=parent_windows.get(parent_key),
                    entity_ids=entity_ids,
                    raw_quote_hint=content[:80],
                    page=meta.get("page"),
                    embedding_distance=float(row.distance) if row.distance is not None else 0.0,
                    document_deleted_at=row.doc_deleted_at,
                )
            )
        return retrieved


async def _parent_windows_for(session, rows) -> dict[tuple[UUID, int], str]:
    """Map (document_id, parent_index) → parent window text.

    Rebuilds each parent from Document.raw_text using min(start_char) /
    max(end_char) across the parent's sibling chunks — exact text, no
    overlap duplication from re-joining small chunks.
    """
    pairs = {
        (row.document_id, (row.metadata or {}).get("parent_index"))
        for row in rows
        if (row.metadata or {}).get("parent_index") is not None
    }
    if not pairs:
        return {}
    doc_ids = {doc_id for doc_id, _ in pairs}

    sibling_stmt = sa.select(
        Chunk.document_id,
        Chunk.chunk_metadata.label("metadata"),
    ).where(Chunk.document_id.in_(doc_ids))
    siblings = (await session.execute(sibling_stmt)).all()

    bounds: dict[tuple[UUID, int], tuple[int, int]] = {}
    for sib in siblings:
        meta = sib.metadata or {}
        parent_index = meta.get("parent_index")
        start, end = meta.get("start_char"), meta.get("end_char")
        if parent_index is None or start is None or end is None:
            continue
        key = (sib.document_id, parent_index)
        if key not in pairs:
            continue
        cur = bounds.get(key)
        bounds[key] = (
            min(start, cur[0]) if cur else start,
            max(end, cur[1]) if cur else end,
        )
    if not bounds:
        return {}

    text_stmt = sa.select(Document.id, Document.raw_text).where(
        Document.id.in_({doc_id for doc_id, _ in bounds})
    )
    raw_texts = {row.id: row.raw_text for row in (await session.execute(text_stmt)).all()}

    windows: dict[tuple[UUID, int], str] = {}
    for (doc_id, parent_index), (start, end) in bounds.items():
        raw = raw_texts.get(doc_id)
        if not raw:
            continue
        windows[(doc_id, parent_index)] = raw[start:end][:PARENT_CONTENT_MAX_CHARS]
    return windows
