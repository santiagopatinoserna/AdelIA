from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID


from adelia.config import settings
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

# SSE stream guards (v0.1.1 carry-over): a hung LLM stream must not hold the
# HTTP connection open forever. Gap = max silence between tokens; total =
# hard cap for the whole answer.
TOKEN_GAP_TIMEOUT_S = 30.0
STREAM_TOTAL_TIMEOUT_S = 120.0


@dataclass
class ChatEvent:
    type: Literal["token", "final", "error"]
    content: str = ""
    citations: list[ChatCitation] = field(default_factory=list)
    evidence_citations: list[dict] = field(default_factory=list)


# Per-locale response-language + mandatory closing disclaimer (v0.1.1 i18n).
_LOCALE_RULES = {
    "es": (
        "Responde en español, en uno o dos párrafos cortos.",
        'Termina con "Verifica con tu médico antes de tomar decisiones clínicas."',
        '"No tengo información suficiente"',
    ),
    "en": (
        "Answer in English, in one or two short paragraphs.",
        'End with "Verify with your doctor before making clinical decisions."',
        '"I don\'t have enough information"',
    ),
    "fr": (
        "Réponds en français, en un ou deux paragraphes courts.",
        'Termine par "Vérifiez avec votre médecin avant toute décision clinique."',
        '"Je n\'ai pas assez d\'informations"',
    ),
}


def _system_prompt(locale: str) -> str:
    lang_rule, disclaimer_rule, no_info = _LOCALE_RULES.get(locale, _LOCALE_RULES["es"])
    return f"""Eres el asistente de salud de AdelIA, enfocado en el seguimiento de
la salud de bebés y niños. Respondes sobre los datos del bebé proporcionados,
pero TODA interpretación o afirmación clínica debe SUSTENTARSE EXCLUSIVAMENTE en
los estudios de investigación / guías clínicas provistos en la sección
"Clinical evidence". No respondes desde tu conocimiento general.

Reglas estrictas:
- Toda interpretación, valoración o recomendación clínica DEBE apoyarse en al menos una cita de evidencia [ev_1], [ev_2], ... Si NO hay un estudio o guía en el contexto que respalde la respuesta clínica, di {no_info} y explica que no hay evidencia de investigación que la sustente. NO interpretes ni aconsejes sin respaldo de investigación.
- Puedes reportar los datos del bebé como hechos (valores, fechas, qué dijo cada médico) citándolos con marcadores numéricos [1], [2], ... del orden de los fragmentos del paciente — pero NO los interpretes clínicamente sin una cita [ev_N].
- El historial de la conversación ES contexto válido: resuelve referencias ("ese valor", "¿y a los 6 meses?") usando los datos ya citados en turnos anteriores, manteniendo sus marcadores originales.
- Cita los estudios/guías con marcadores [ev_1], [ev_2], ... de la sección "Clinical evidence".
- Separa claramente el dato del bebé de la evidencia (e.g. "regurgita tras cada toma [1]; según NASPGHAN-ESPGHAN es habitual y mejora hacia los 12 meses [ev_1]").
- {lang_rule}
- NUNCA inventes datos médicos ni estudios. NUNCA des consejos médicos definitivos.
- {disclaimer_rule}
"""


def _format_rag_context(chunks: list) -> str:
    """Format retrieved chunks as numbered context for the LLM prompt.

    Uses the expanded parent window when available — the small chunk stays
    the citation quote, but the LLM sees the surrounding context."""
    lines = []
    for i, c in enumerate(chunks, start=1):
        lines.append(f"[{i}] {getattr(c, 'parent_content', None) or c.content}")
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
    """Stream generation tokens from the configured provider.

    Provider is selected by settings.llm_provider ("mistral" | "openai").
    Embeddings/OCR always use Mistral regardless — only generation is
    pluggable. history: prior turns ({"role","content"}), oldest first; the
    RAG context lives only in the final user message.

    Raises RuntimeError if the selected provider's API key is missing.
    """
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": user_message})

    if settings.llm_provider == "openai":
        async for piece in _stream_openai_tokens(messages):
            yield piece
    else:
        async for piece in _stream_mistral_tokens(messages):
            yield piece


async def _stream_mistral_tokens(messages: list[dict]) -> AsyncIterator[str]:
    """Raises RuntimeError if MISTRAL_API_KEY missing."""
    client = get_mistral_client()
    response = await client.chat.stream_async(
        model=settings.mistral_chat_model,
        messages=messages,
        temperature=0.2,
    )
    async for event in response:
        if event.data and event.data.choices:
            delta = event.data.choices[0].delta
            piece = getattr(delta, "content", "") or ""
            if piece:
                yield piece


async def _stream_openai_tokens(messages: list[dict]) -> AsyncIterator[str]:
    """Stream tokens from OpenAI chat completions.

    Raises RuntimeError if OPENAI_API_KEY missing (config error, no retry).
    """
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    stream = await client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=messages,
        temperature=0.2,
        stream=True,
    )
    async for chunk in stream:
        if chunk.choices:
            piece = chunk.choices[0].delta.content or ""
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
    *, user_id: UUID, question: str, history: list[dict] | None = None, locale: str = "es"
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
                        source_type="entity",
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

        token_iter = _stream_llm_tokens(
            _system_prompt(locale), user_msg, history=history
        ).__aiter__()
        stream_start = time.monotonic()
        try:
            while True:
                remaining = STREAM_TOTAL_TIMEOUT_S - (time.monotonic() - stream_start)
                if remaining <= 0:
                    raise TimeoutError(
                        f"chat stream exceeded {STREAM_TOTAL_TIMEOUT_S:.0f}s total budget"
                    )
                try:
                    token = await asyncio.wait_for(
                        token_iter.__anext__(), timeout=min(TOKEN_GAP_TIMEOUT_S, remaining)
                    )
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"chat stream stalled >{TOKEN_GAP_TIMEOUT_S:.0f}s between tokens"
                    )
                yield ChatEvent(type="token", content=token)
        finally:
            # Abandoning the generator without aclose() leaves the HTTP
            # stream to Mistral open until GC — the exact leak these
            # timeouts exist to prevent.
            await token_iter.aclose()

        yield ChatEvent(
            type="final",
            citations=citations,
            evidence_citations=evidence_citations,
        )
    except Exception as exc:  # noqa: BLE001 — surface to client as error event
        logger.exception("answer_question_streaming failed: %s", exc)
        yield ChatEvent(type="error", content=str(exc))
