from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID


from adelia.llm import get_mistral_client
from adelia.db import AsyncSessionLocal
from adelia.enrichment.evidence_retrieval import (
    EvidenceMatch,
    evidence_citations_for_response,
    format_evidence_for_prompt,
    retrieve_evidence,
)
from adelia.schemas import ChatCitation
from adelia.services.retrieval import retrieve_relevant_chunks
from adelia.services.structured_query import query_observations_by_name_and_date_range
from adelia.services.temporal import detect_temporal_intent
from adelia.workers.embed import embed_texts


logger = logging.getLogger(__name__)


@dataclass
class ChatEvent:
    type: Literal["token", "final", "error"]
    content: str = ""
    citations: list[ChatCitation] = field(default_factory=list)
    evidence_citations: list[dict] = field(default_factory=list)


_SYSTEM_PROMPT = """Eres un asistente médico que responde EXCLUSIVAMENTE basándote en
los datos del paciente Y la evidencia clínica proporcionada como contexto.

Reglas estrictas:
- Si la información NO está en el contexto del paciente, NI en la evidencia, NI en turnos anteriores de esta conversación, di "No tengo información suficiente".
- El historial de la conversación ES contexto válido: resuelve referencias ("ese valor", "¿y en 2023?") usando los datos ya citados en turnos anteriores, manteniendo sus marcadores originales.
- Cita datos del paciente con marcadores numéricos [1], [2], ... correspondientes al orden de los fragmentos del paciente.
- Cita guidelines/evidencia con marcadores [ev_1], [ev_2], ... correspondientes a la sección "Clinical evidence".
- Cuando combines ambos (e.g. "tu HbA1c X% [2] está en rango prediabetes según ADA [ev_1]"), separa claramente paciente vs evidencia.
- Responde en español, en uno o dos párrafos cortos.
- NUNCA inventes datos médicos. NUNCA des consejos médicos definitivos.
- Termina con "Verifica con tu médico antes de tomar decisiones clínicas."
"""


def _format_rag_context(chunks: list) -> str:
    """Format retrieved chunks as numbered context for the LLM prompt."""
    lines = []
    for i, c in enumerate(chunks, start=1):
        lines.append(f"[{i}] {c.content}")
    return "\n\n".join(lines)


def _format_temporal_context(rows: list[dict]) -> str:
    """Format structured-query rows as a numbered table for the LLM prompt."""
    lines = []
    for i, r in enumerate(rows, start=1):
        value = r.get("value") or {}
        v_str = (
            f"{value.get('value')} {value.get('unit') or ''}".strip()
            if isinstance(value, dict)
            else str(value)
        )
        date_str = r.get("event_date").isoformat() if r.get("event_date") else "fecha desconocida"
        lines.append(f"[{i}] {r['name']} = {v_str} ({date_str})")
    return "\n\n".join(lines)


async def _stream_llm_tokens(
    system_prompt: str,
    user_message: str,
    history: list[dict] | None = None,
) -> AsyncIterator[str]:
    """Stream tokens from Mistral. Yields one token-substring per chunk.

    history: prior conversation turns ({"role", "content"}), oldest first.
    The RAG context lives only in the final user message — history carries
    the conversational thread so follow-ups ("¿y en 2023?") resolve.

    Raises RuntimeError if MISTRAL_API_KEY missing.
    """
    client = get_mistral_client()
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": user_message})
    response = await client.chat.stream_async(
        model="mistral-medium-latest",
        messages=messages,
        temperature=0.2,
    )
    async for event in response:
        if event.data and event.data.choices:
            delta = event.data.choices[0].delta
            piece = getattr(delta, "content", "") or ""
            if piece:
                yield piece


async def _retrieve_evidence_for_query(
    query_embedding: list[float] | None,
    *,
    top_k: int = 4,
) -> list[EvidenceMatch]:
    """Best-effort evidence retrieval. Returns [] on any error (graceful degradation).

    Dual-RAG: complements patient retrieval with clinical guidelines.
    """
    if query_embedding is None:
        return []
    try:
        async with AsyncSessionLocal() as session:
            return await retrieve_evidence(
                session,
                query_embedding=query_embedding,
                top_k=top_k,
                max_distance=0.45,
            )
    except Exception as e:
        logger.warning("evidence retrieval failed (continuing without): %s", e)
        return []


async def answer_question_streaming(
    *, user_id: UUID, question: str, history: list[dict] | None = None
) -> AsyncIterator[ChatEvent]:
    """Main orchestrator: detect temporal intent → retrieve patient + evidence context → stream LLM.

    Dual-RAG: patient chunks (or temporal observations) PLUS clinical guidelines
    (from evidence_chunks). Citations returned in separate namespaces:
    - citations: list[ChatCitation] (patient data — linkable to /dashboard/documents)
    - evidence_citations: list[dict] (guidelines — linkable to source URLs)
    """
    citations: list[ChatCitation] = []
    evidence_citations: list[dict] = []
    query_embedding: list[float] | None = None

    # Elliptical follow-ups ("¿y ese valor?") embed poorly on their own —
    # augment the retrieval query with the tail of the conversation. Temporal
    # intent detection still runs on the raw question.
    retrieval_query = question
    if history:
        tail = " ".join(m["content"] for m in history[-2:])
        retrieval_query = f"{tail[-1000:]}\n{question}"

    try:
        temporal = detect_temporal_intent(question)
        if temporal is not None:
            rows = await query_observations_by_name_and_date_range(
                user_id=user_id,
                name_substring=temporal.entity_name,
                from_date=temporal.from_date,
                to_date=temporal.to_date,
            )
            patient_context = _format_temporal_context(rows)
            # Also embed for evidence retrieval (temporal queries benefit from
            # guidelines about the queried lab — e.g. "HbA1c curve" → ADA targets)
            try:
                qe = await embed_texts([retrieval_query])
                query_embedding = qe[0] if qe else None
            except Exception as e:
                logger.warning("embed for evidence failed in temporal path: %s", e)
            for r in rows:
                citations.append(
                    ChatCitation(
                        chunk_id=r["id"],
                        document_id=r["document_id"],
                        raw_quote=r["raw_quote"] or "",
                        page=None,
                    )
                )
        else:
            # Standard RAG path
            query_embeds = await embed_texts([retrieval_query])
            if not query_embeds:
                raise RuntimeError(
                    "embed_texts returned empty — cannot retrieve chunks"
                )
            query_embedding = query_embeds[0]
            chunks = await retrieve_relevant_chunks(
                user_id=user_id,
                query_embedding=query_embedding,
                top_k=8,
            )
            patient_context = _format_rag_context(chunks)
            for c in chunks:
                citations.append(
                    ChatCitation(
                        chunk_id=c.chunk_id,
                        document_id=c.document_id,
                        raw_quote=c.content,
                        page=c.page,
                    )
                )

        # Dual-RAG: parallel evidence retrieval
        evidence_matches = await _retrieve_evidence_for_query(query_embedding)
        evidence_block = format_evidence_for_prompt(evidence_matches)
        evidence_citations = evidence_citations_for_response(evidence_matches)

        # Compose final user message with both contexts
        sections = [f"Pregunta del usuario: {question}\n"]
        if patient_context:
            sections.append(f"## Patient data (cite as [N]):\n{patient_context}")
        if evidence_block:
            sections.append(evidence_block)
        user_msg = "\n\n".join(sections)

        async for token in _stream_llm_tokens(_SYSTEM_PROMPT, user_msg, history=history):
            yield ChatEvent(type="token", content=token)

        yield ChatEvent(
            type="final",
            citations=citations,
            evidence_citations=evidence_citations,
        )
    except Exception as exc:  # noqa: BLE001 — surface to client as error event
        logger.exception("answer_question_streaming failed: %s", exc)
        yield ChatEvent(type="error", content=str(exc))
