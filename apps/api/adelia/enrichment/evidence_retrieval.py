"""Dual-RAG evidence retrieval — clinical guidelines + papers + protocols.

Sister to the patient RAG (Modo A chat retrieval). Combined results in
chat_orchestrator / briefing_orchestrator provide:
- Patient context (from `chunks` table — what's true about THIS user)
- Evidence context (from `evidence_chunks` table — what's true clinically)

LLM synthesizes both with separate citation namespaces:
- 🟡 patient citation (linkable to /dashboard/documents/{id})
- 📘 evidence citation (linkable to source URL)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.models import EvidenceChunk, EvidenceSource


@dataclass(frozen=True)
class EvidenceMatch:
    chunk_id: UUID
    source_id: UUID
    source_title: str
    organization: str | None
    publication_year: int | None
    url: str | None
    content: str
    chunk_index: int
    distance: float  # cosine distance, lower = more relevant


async def retrieve_evidence(
    session: AsyncSession,
    *,
    query_embedding: list[float],
    specialties: Iterable[str] | None = None,
    top_k: int = 5,
    max_distance: float = 0.45,
) -> list[EvidenceMatch]:
    """Retrieve top-K evidence chunks ranked by cosine distance.

    Args:
        query_embedding: 1024-dim vector from mistral-embed
        specialties: optional filter — only evidence tagged with at least one
            of these specialties is returned (e.g. ['cardiology'])
        top_k: max results
        max_distance: cosine distance cutoff (0.45 ≈ 0.55 similarity, reasonable threshold)

    Returns: sorted list, most relevant first.
    """
    # pgvector cosine distance via `<=>` operator
    # We do a join to evidence_sources to filter by specialty + return metadata
    stmt_text = """
        SELECT
            ec.id AS chunk_id,
            ec.source_id,
            es.title AS source_title,
            es.organization,
            es.publication_year,
            es.url,
            ec.content,
            ec.chunk_index,
            ec.embedding <=> :emb AS distance
        FROM evidence_chunks ec
        JOIN evidence_sources es ON es.id = ec.source_id
        WHERE ec.embedding <=> :emb < :max_distance
    """
    params: dict = {"emb": str(query_embedding), "max_distance": max_distance}

    if specialties:
        spec_list = list(specialties)
        # JSONB array contains-any check via the ?| operator
        stmt_text += " AND es.specialties ?| array[:spec_list]"
        params["spec_list"] = spec_list

    stmt_text += " ORDER BY distance ASC LIMIT :k"
    params["k"] = top_k

    result = await session.execute(text(stmt_text), params)
    rows = result.mappings().all()

    return [
        EvidenceMatch(
            chunk_id=r["chunk_id"],
            source_id=r["source_id"],
            source_title=r["source_title"],
            organization=r["organization"],
            publication_year=r["publication_year"],
            url=r["url"],
            content=r["content"],
            chunk_index=r["chunk_index"],
            distance=float(r["distance"]),
        )
        for r in rows
    ]


def format_evidence_for_prompt(matches: list[EvidenceMatch]) -> str:
    """Render evidence matches as a context block for LLM system prompt.

    Each match prefixed with a `[ev_N]` citation tag the LLM can reference.
    """
    if not matches:
        return ""

    lines = ["## Clinical evidence (cite as [ev_N]):"]
    for i, m in enumerate(matches, start=1):
        attribution = m.source_title
        if m.organization:
            attribution = f"{m.organization} — {attribution}"
        if m.publication_year:
            attribution = f"{attribution} ({m.publication_year})"
        lines.append(f"[ev_{i}] {attribution}")
        lines.append(m.content)
        lines.append("")
    return "\n".join(lines)


def evidence_citations_for_response(matches: list[EvidenceMatch]) -> list[dict]:
    """Render evidence matches as a JSON-serializable list for the API response.

    Frontend uses this to render 📘 citation badges with click-through URLs.
    """
    return [
        {
            "tag": f"ev_{i}",
            "source_id": str(m.source_id),
            "chunk_id": str(m.chunk_id),
            "title": m.source_title,
            "organization": m.organization,
            "year": m.publication_year,
            "url": m.url,
            "snippet": m.content[:280],
            "distance": round(m.distance, 4),
        }
        for i, m in enumerate(matches, start=1)
    ]
