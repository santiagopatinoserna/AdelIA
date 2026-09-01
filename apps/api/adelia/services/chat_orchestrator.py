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
from adelia.clinical import red_flags
from adelia.schemas import ChatCitation
from adelia.services.answer_contract import (
    chat_system_prompt,
    no_evidence_reply,
    red_flag_reply,
)
from adelia.services.retrieval import retrieve_relevant_chunks
from adelia.services.scope import Scope
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


# The response language, the citation obligation and the closing disclaimer
# now live in services/answer_contract, shared verbatim with the /dashboard
# agent (agent/orchestrator). Before 2026-08-31 they existed only here, so the
# default screen answered clinical questions with none of them.


def _system_prompt(locale: str) -> str:
    return chat_system_prompt(locale)


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


async def generate_answer(
    system_prompt: str,
    user_message: str,
    *,
    timeout_s: float = STREAM_TOTAL_TIMEOUT_S,
) -> str:
    """One complete answer from the configured provider, no streaming.

    Same provider selection, same prompts and the same total budget as the
    chat, collected into a string. It exists for the public demo
    (routers/demo), whose answer is delivered in a single JSON response: a
    demo page has no session to stream into and no transcript to persist, so
    SSE would buy it nothing and cost it a second transport to get wrong.

    The generator is always closed. Abandoning it leaves the HTTP stream to
    the provider open until GC, which is the leak the chat's own timeouts
    exist to prevent.
    """
    token_iter = _stream_llm_tokens(system_prompt, user_message).__aiter__()
    pieces: list[str] = []
    start = time.monotonic()
    try:
        while True:
            remaining = timeout_s - (time.monotonic() - start)
            if remaining <= 0:
                raise TimeoutError(f"answer exceeded {timeout_s:.0f}s total budget")
            try:
                pieces.append(
                    await asyncio.wait_for(
                        token_iter.__anext__(), timeout=min(TOKEN_GAP_TIMEOUT_S, remaining)
                    )
                )
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"answer stalled >{TOKEN_GAP_TIMEOUT_S:.0f}s between tokens"
                )
    finally:
        await token_iter.aclose()
    return "".join(pieces).strip()


async def _retrieve_evidence_for_query(
    query_embedding: list[float] | None,
    *,
    top_k: int = 4,
) -> list[EvidenceMatch]:
    """Best-effort evidence retrieval. Returns [] on any error (graceful degradation).

    Dual-RAG: complements patient retrieval with clinical guidelines. The
    cut-off comes from settings.evidence_max_distance (calibrated, see
    docs/CALIBRACION_UMBRAL_EVIDENCIA.md), not from a literal: the literal it
    replaces (0.45) was above the corpus's own diameter and filtered nothing.

    `specialties=["pediatrics"]` is what makes the calibration describe the
    code. evidence_chunks also holds 8 adult sources (atrial fibrillation,
    hypertension, cholesterol, breast and colorectal cancer screening,
    endometriosis, adult diabetes, SBAR); without the tag filter an unfiltered
    search over all of them returned anticoagulation or cancer-screening
    fragments labelled "Clinical evidence" in an app about a baby. All 110
    pediatric sources carry the tag; the 8 adult ones do not.
    """
    if query_embedding is None:
        return []
    try:
        async with AsyncSessionLocal() as session:
            return await retrieve_evidence(
                session,
                query_embedding=query_embedding,
                specialties=["pediatrics"],
                top_k=top_k,
                max_distance=settings.evidence_max_distance,
            )
    except Exception as e:
        logger.warning("evidence retrieval failed (continuing without): %s", e)
        return []


async def answer_question_streaming(
    *,
    user_id: UUID,
    question: str,
    history: list[dict] | None = None,
    locale: str = "es",
    age_months: int | None = None,
    country: str | None = None,
    profile_id: UUID | None = None,
) -> AsyncIterator[ChatEvent]:
    """Main orchestrator: red flags → temporal intent → retrieve → stream LLM.

    Dual-RAG: patient chunks (or temporal observations) PLUS clinical guidelines
    (from evidence_chunks). Citations returned in separate namespaces:
    - citations: list[ChatCitation] (patient data, linkable to /dashboard/documents)
    - evidence_citations: list[dict] (guidelines, linkable to source URLs)

    `age_months` is the active profile's age, resolved by the caller (the
    router and the agent both have a session; this function must not open
    one mid-stream). It gates the age-dependent red flags, above all "under
    3 months with a fever of 38 C or more" (NICE NG143 1.2.12). When it is
    None the detector still runs on any age the parent wrote in the question
    itself.

    `profile_id` is the SAME resolved profile the age came from, and it is
    what keeps the two children of one account apart: retrieval and the
    temporal query are both scoped to it (audit 4.1). The caller resolves it
    once (ProfileFacts.profile_id) rather than each read resolving its own,
    so the answer, its citations and the age all describe one child. None
    means "the whole account", which is what an account with no profile at
    all still gets.
    """
    scope = Scope(user_id=user_id, profile_id=profile_id)
    citations: list[ChatCitation] = []
    evidence_citations: list[dict] = []
    query_embedding: list[float] | None = None

    # Red flags first, ahead of retrieval and of any model call (audit 3.3).
    #
    # This is deliberately the FIRST statement of the answering path, before
    # the embedding, before the vector search, before the prompt. The
    # question that makes this necessary ("my 2-month-old is at 38.2, do I
    # give her paracetamol?") is one retrieval answers beautifully and
    # wrongly: there is a paracetamol fragment, the model will dose it, and
    # the answer will carry a citation. Nothing downstream of here can undo
    # that, so nothing downstream of here runs.
    flag = red_flags.detect(question, locale=locale, age_months=age_months)
    if flag is not None:
        logger.warning(
            "chat: red flag %s fired (matched=%r, age_months=%s); returning the "
            "urgent referral without retrieval and without the generative model",
            flag.code, flag.matched, flag.age_months,
        )
        yield ChatEvent(type="token", content=red_flag_reply(flag.code, locale, country=country))
        yield ChatEvent(
            type="final",
            citations=[],
            evidence_citations=[red_flags.citation_for(flag)],
        )
        return

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
                scope=scope,
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
                scope=scope,
                query_embedding=query_embedding,
                top_k=8,
                max_distance=settings.patient_max_distance,
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

        # Hard refusal, in code, before any generative call. Nothing survived
        # the retrieval cut-offs on either side: no clinical evidence AND no
        # fragment of this user's own history. Handing that to the LLM is
        # exactly how a confident, sourceless, wrong answer about a baby gets
        # produced, and no prompt clause can be trusted to prevent it. So the
        # model is never called: the refusal is returned by the code itself.
        if not evidence_matches and not patient_context:
            logger.info(
                "chat: no grounding (0 evidence chunks, 0 patient chunks), "
                "returning the refusal without calling the generative model"
            )
            yield ChatEvent(type="token", content=no_evidence_reply(locale))
            yield ChatEvent(type="final", citations=[], evidence_citations=[])
            return

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
