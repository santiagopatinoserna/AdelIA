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

from sqlalchemy import String, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.config import settings



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
    max_distance: float | None = None,
) -> list[EvidenceMatch]:
    """Retrieve top-K evidence chunks ranked by cosine distance.

    Args:
        query_embedding: 1024-dim vector from mistral-embed
        specialties: optional filter — only evidence tagged with at least one
            of these specialties is returned (e.g. ['pediatrics']). The
            answering path passes ['pediatrics'] so a question about a baby
            can never be answered with the adult sources the same table
            holds (atrial fibrillation, cancer screening, SBAR).
        top_k: max results
        max_distance: cosine distance cut-off. Defaults to
            settings.evidence_max_distance, calibrated against the real corpus
            (see apps/api/docs/CALIBRACION_UMBRAL_EVIDENCIA.md). The previous
            default, 0.45, was above the corpus's own diameter (0.3386), so it
            rejected nothing and every question came back "evidence-backed".

    Returns: sorted list, most relevant first.
    """
    if max_distance is None:
        max_distance = settings.evidence_max_distance
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

    # JSONB array contains-any check via the ?| operator, whose right-hand
    # side is a text[]. `array[:spec_list]` built an array OF the parameter,
    # so asyncpg was handed a list where it expected a str and raised
    # DataError: invalid input for query argument $3: ['pediatrics'] (expected
    # str, got list). Every call that passed `specialties` therefore blew up —
    # silently, because both call sites swallow the exception and return []
    # (briefing_orchestrator._retrieve_specialty_evidence never returned a
    # single fragment). Bind the list itself, typed as text[].
    spec_list = list(specialties) if specialties else None
    if spec_list:
        stmt_text += " AND es.specialties ?| :spec_list"
        params["spec_list"] = spec_list

    stmt_text += " ORDER BY distance ASC LIMIT :k"
    params["k"] = top_k

    stmt = text(stmt_text)
    if spec_list:
        stmt = stmt.bindparams(bindparam("spec_list", type_=ARRAY(String)))
    result = await session.execute(stmt, params)
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
