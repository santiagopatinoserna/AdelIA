from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from mistralai.client.sdk import Mistral

from adelia.config import settings
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


_SYSTEM_PROMPT = """Eres un asistente médico que responde EXCLUSIVAMENTE basándote en
los fragmentos de la historia clínica del usuario proporcionados como contexto.

Reglas estrictas:
- Si la información no está en el contexto, di "No tengo información suficiente".
- Cita los fragmentos con marcadores numéricos [1], [2], ... que corresponden
  al orden de los fragmentos del contexto.
- Responde en español, en un párrafo corto.
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
    system_prompt: str, user_message: str
) -> AsyncIterator[str]:
    """Stream tokens from Mistral. Yields one token-substring per chunk.

    Raises RuntimeError if MISTRAL_API_KEY missing.
    """
    if not settings.mistral_api_key:
        raise RuntimeError("MISTRAL_API_KEY not set")

    client = Mistral(api_key=settings.mistral_api_key)
    response = await client.chat.stream_async(
        model="mistral-medium-latest",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,
    )
    async for event in response:
        if event.data and event.data.choices:
            delta = event.data.choices[0].delta
            piece = getattr(delta, "content", "") or ""
            if piece:
                yield piece


async def answer_question_streaming(
    *, user_id: UUID, question: str
) -> AsyncIterator[ChatEvent]:
    """Main orchestrator: detect temporal intent → retrieve context → stream LLM.

    Yields ChatEvent(type='token', content=...) for each LLM token, then a
    single ChatEvent(type='final', citations=[...]) at the end. On error,
    yields ChatEvent(type='error', content=<message>).
    """
    citations: list[ChatCitation] = []
    try:
        temporal = detect_temporal_intent(question)
        if temporal is not None:
            rows = await query_observations_by_name_and_date_range(
                user_id=user_id,
                name_substring=temporal.entity_name,
                from_date=temporal.from_date,
                to_date=temporal.to_date,
            )
            context = _format_temporal_context(rows)
            user_msg = (
                f"Pregunta del usuario: {question}\n\n"
                f"Datos estructurados de observaciones:\n{context}"
            )
            # Map each row to a Citation surrogate (chunk_id ← entity id)
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
            query_embeds = await embed_texts([question])
            if not query_embeds:
                raise RuntimeError(
                    "embed_texts returned empty — cannot retrieve chunks"
                )
            chunks = await retrieve_relevant_chunks(
                user_id=user_id,
                query_embedding=query_embeds[0],
                top_k=8,
            )
            context = _format_rag_context(chunks)
            user_msg = (
                f"Pregunta del usuario: {question}\n\n"
                f"Fragmentos del contexto:\n{context}"
            )
            for c in chunks:
                citations.append(
                    ChatCitation(
                        chunk_id=c.chunk_id,
                        document_id=c.document_id,
                        raw_quote=c.content,
                        page=c.page,
                    )
                )

        async for token in _stream_llm_tokens(_SYSTEM_PROMPT, user_msg):
            yield ChatEvent(type="token", content=token)

        yield ChatEvent(type="final", citations=citations)
    except Exception as exc:  # noqa: BLE001 — surface to client as error event
        logger.exception("answer_question_streaming failed: %s", exc)
        yield ChatEvent(type="error", content=str(exc))
