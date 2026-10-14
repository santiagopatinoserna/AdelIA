import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import REGCONFIG

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import Chunk, Document
from adelia.services.fusion import rrf
from adelia.services.lexical import HYBRID_CANDIDATE_POOL, LexicalPlan, plan_lexical
from adelia.services.reranker import NullReranker, Reranker, rerank_items
from adelia.services.scope import Scope

logger = logging.getLogger(__name__)

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
    scope: Scope,
    query_embedding: list[float],
    top_k: int = 8,
    max_distance: float | None = None,
    query_text: str | None = None,
    locale: str | None = None,
    reranker: Reranker | None = None,
) -> list[RetrievedChunk]:
    """Vector-similarity search over chunks (pgvector cosine), filtered to
    the scope's documents that are not soft-deleted. Returns up to top_k
    results with their parent-chunk content expanded for context.

    Args:
        scope: whose record to search (user, and optionally one profile).
            Before 2026-08-31 this was a bare `user_id`, so a mother with two
            children had her newborn's question answered out of her
            four-year-old's chunks: `chunks.profile_id` was written on every
            row and read by nothing. `Scope.where` keeps rows with a NULL
            profile_id, which is every row written before profiles existed.
        query_embedding: 1024-dim vector from mistral-embed.
        top_k: number of small chunks to retrieve.
        max_distance: cosine-distance cut-off; anything farther is not
            returned. Defaults to settings.patient_max_distance. Before
            2026-08-31 there was no cut-off at all here: the query returned
            the closest top_k chunks whatever their distance, so a user with
            three unrelated documents always got three "relevant" chunks.
            Pass float("inf") to disable (tests that seed synthetic vectors).
        query_text: the question as text, for the lexical half of hybrid
            retrieval. Ignored unless settings.retrieval_hybrid_enabled is on.
        locale: the question's language (es/en/fr), picks the text-search
            configuration. Any other value means no lexical query.
        reranker: a services.reranker.Reranker applied to the fused pool.
            Defaults to NullReranker, the identity. Hybrid path only.

    Hybrid retrieval (settings.retrieval_hybrid_enabled, OFF by default). With
    the flag off, or without `query_text`, or with a locale the corpus is not
    written in, the vector query below runs with LIMIT top_k and nothing else
    does: same SQL, same result as before the flag existed. With it on, the
    vector query returns a pool of HYBRID_CANDIDATE_POOL rows, a `tsvector`
    query ranks the same user's chunks by `ts_rank_cd`, Reciprocal Rank Fusion
    merges the two, the reranker reorders, and the first top_k are returned.

    The lexical query carries the SAME scope as the vector one, by construction:
    both splat `scope.where(Chunk)` and the soft-delete filter. A lexical
    search that forgot `user_id` would be a cross-user data leak, since
    full-text matching reads the words of whoever's chunk contains them; the
    two-user, two-profile test in tests/test_hybrid_retrieval.py is what holds
    that line.

    As with the evidence side, the full-text ranking can reorder the fragments
    that passed `max_distance` but cannot admit one that did not (see
    enrichment/evidence_retrieval.retrieve_evidence for the reasoning).

    Returns:
        Ordered list (most similar first) of RetrievedChunk. parent_content
        carries the surrounding ~1500-token parent window rebuilt from the
        document raw_text via sibling chunk offsets (None when offsets or
        raw_text are unavailable). Citations keep the small-chunk content.
    """
    cutoff = settings.patient_max_distance if max_distance is None else max_distance
    plan = plan_lexical(query_text, locale)
    pool = max(top_k, HYBRID_CANDIDATE_POOL) if plan is not None else top_k
    async with AsyncSessionLocal() as session:
        # Join chunks → documents to enforce soft-delete filter at the SQL layer.
        # Use pgvector cosine distance — lower is more similar.
        distance_expr = Chunk.embedding.cosine_distance(query_embedding)
        where = [
            *scope.where(Chunk),
            Document.deleted_at.is_(None),
        ]
        if cutoff != float("inf"):
            where.append(distance_expr < cutoff)
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
            .where(*where)
            .order_by(distance_expr.asc())
            .limit(pool)
        )
        result = await session.execute(stmt)
        rows = list(result.all())

        if plan is not None and rows:
            lexical_ids = await lexical_chunk_ranking(
                session, scope=scope, plan=plan, pool=pool
            )
            fused = dict(rrf([[str(r.chunk_id) for r in rows], lexical_ids]))
            # Only vector survivors are fused back in; sorted() is stable, so
            # equal fused scores keep their vector order.
            rows = sorted(rows, key=lambda r: -fused[str(r.chunk_id)])
            rows = await rerank_items(
                reranker or NullReranker(),
                query_text,
                rows,
                id_of=lambda r: str(r.chunk_id),
                text_of=lambda r: r.content,
                score_of=lambda r: fused[str(r.chunk_id)],
            )
            rows = rows[:top_k]

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


async def lexical_chunk_ranking(
    session,
    *,
    scope: Scope,
    plan: LexicalPlan,
    pool: int,
) -> list[str]:
    """Chunk ids of this scope ranked by full-text relevance, best first (as str).

    `scope.where(Chunk)` and `Document.deleted_at IS NULL` are the exact
    conditions the vector query uses, so this ranking can only ever contain
    chunks the vector query is also allowed to return: the caller's user, the
    caller's profile (or rows not yet assigned to one), and no soft-deleted
    document. `chunks.tsv` indexes the text under es + en + fr (migration
    0021), so the question is parsed under its own language and matches the
    same words whatever language the document was in.

    Best-effort, like the evidence side: a failure is logged and returns [], so
    the caller falls back to the vector order, and it runs in a SAVEPOINT so a
    failed statement does not abort the transaction the parent-window queries
    still need.
    """
    query = sa.func.to_tsquery(sa.cast(plan.ts_config, REGCONFIG), plan.tsquery)
    stmt = (
        sa.select(Chunk.id)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            *scope.where(Chunk),
            Document.deleted_at.is_(None),
            Chunk.tsv.bool_op("@@")(query),
        )
        # Normalisation 1 divides the rank by 1 + log(length), a mild brake on
        # long chunks that match more terms simply by containing more words.
        .order_by(sa.func.ts_rank_cd(Chunk.tsv, query, 1).desc(), Chunk.id.asc())
        .limit(pool)
    )
    try:
        async with session.begin_nested():
            result = await session.execute(stmt)
            return [str(chunk_id) for chunk_id in result.scalars()]
    except Exception as exc:  # noqa: BLE001 - never let the cross-check break retrieval
        # Class name only: str(exc) carries the bound parameters, which are the
        # parent's question terms, and health questions do not belong in logs.
        logger.warning(
            "lexical chunk ranking failed, using vector order: %s", type(exc).__name__
        )
        return []


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
