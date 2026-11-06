from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID


from adelia.config import settings
from adelia.llm import (
    content_text,
    get_anthropic_client,
    get_mistral_client,
    raise_on_refusal,
    reasoning_effort_kwargs,
    uses_anthropic,
)
from adelia.agent import implicit_subject, lay_terms
from adelia.agent.corpus_query import corpus_query
from adelia.agent.graph import GraphDeps, Retrieved, stream_graph
from adelia.agent.route import log_route
from adelia.db import AsyncSessionLocal
from adelia.enrichment.evidence_retrieval import (
    EvidenceMatch,
    merge_by_best_distance,
    retrieve_evidence,
)
from adelia.enrichment.profile_service import ProfileFacts
from adelia.schemas import ChatCitation
from adelia.services.answer_contract import chat_system_prompt
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
    *,
    provider: str | None = None,
) -> AsyncIterator[str]:
    """Stream generation tokens from the configured provider.

    Provider is selected by `provider` when given, else by settings.llm_provider
    ("mistral" | "openai" | "anthropic"). Only the public demo passes one
    (settings.demo_llm_provider); the chat and briefings never do, so they keep
    following llm_provider. Embeddings/OCR always use Mistral regardless; only
    generation is pluggable. history: prior turns ({"role","content"}), oldest
    first; the RAG context lives only in the final user message.

    Raises RuntimeError if the selected provider's API key is missing.
    """
    if uses_anthropic(provider):
        async for piece in _stream_anthropic_tokens(system_prompt, user_message, history):
            yield piece
        return

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": user_message})

    if (provider or settings.llm_provider) == "openai":
        async for piece in _stream_openai_tokens(messages):
            yield piece
    else:
        async for piece in _stream_mistral_tokens(messages):
            yield piece


async def _stream_mistral_tokens(messages: list[dict]) -> AsyncIterator[str]:
    """Raises RuntimeError if MISTRAL_API_KEY missing.

    settings.chat_reasoning_effort rides along only when it is set AND the model
    is on adelia.llm.REASONING_EFFORT_MODELS; unset, the call has exactly the
    keyword arguments it always had. With effort "high" the delta `content` is
    a list that starts with a thinking chunk, so every piece goes through
    content_text: the reasoning trace is never streamed to the parent.
    """
    client = get_mistral_client()
    response = await client.chat.stream_async(
        model=settings.mistral_chat_model,
        messages=messages,
        temperature=0.2,
        **reasoning_effort_kwargs(
            settings.chat_reasoning_effort,
            settings.mistral_chat_model,
            setting="chat_reasoning_effort",
        ),
    )
    async for event in response:
        if event.data and event.data.choices:
            delta = event.data.choices[0].delta
            piece = content_text(getattr(delta, "content", "") or "")
            if piece:
                yield piece


def _anthropic_history(history: list[dict] | None) -> list[dict]:
    """The prior turns as Anthropic accepts them: user and assistant only, and
    starting with a user turn. routers/chat keeps the LAST N messages of a
    session, so the window can open on an assistant reply, which Mistral takes
    and Anthropic answers with a 400. The system prompt travels apart."""
    turns = [m for m in history or [] if m.get("role") in ("user", "assistant")]
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    return turns


async def _stream_anthropic_tokens(
    system_prompt: str, user_message: str, history: list[dict] | None
) -> AsyncIterator[str]:
    """Raises RuntimeError if ANTHROPIC_API_KEY missing, AnthropicRefusal on a refusal.

    Thinking is on by default on the current Claude models and cannot be turned
    off on the default one; effort "medium" (its default, set explicitly so a
    model change does not move it) bounds it. text_stream yields only text
    deltas, so the reasoning is never streamed to the parent. No temperature:
    the current Claude models reject sampling parameters with a 400.
    """
    client = get_anthropic_client()
    async with client.messages.stream(
        model=settings.anthropic_chat_model,
        max_tokens=16000,
        system=system_prompt,
        messages=[*_anthropic_history(history), {"role": "user", "content": user_message}],
        output_config={"effort": "medium"},
    ) as stream:
        async for piece in stream.text_stream:
            if piece:
                yield piece
        final = await stream.get_final_message()
    # A refusal can arrive after some text; raising ends the turn as an error,
    # not as an answer that stops mid-sentence.
    raise_on_refusal(final)


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
    provider: str | None = None,
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
    token_iter = _stream_llm_tokens(system_prompt, user_message, provider=provider).__aiter__()
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
    query_text: str | None = None,
    locale: str | None = None,
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

    `query_text` and `locale` feed the lexical half of hybrid retrieval and do
    nothing while settings.retrieval_hybrid_enabled is off (the default).
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
                relative_margin=settings.evidence_relative_margin,
                query_text=query_text,
                locale=locale,
            )
    except Exception as e:
        logger.warning("evidence retrieval failed (continuing without): %s", e)
        return []


async def _guarded_stream(
    system_prompt: str, user_message: str, *, history: list[dict] | None = None
) -> AsyncIterator[str]:
    """`_stream_llm_tokens` under the SSE guards: a gap between tokens and a
    total budget. Abandoning the generator without aclose() leaves the HTTP
    stream to the provider open until GC, the exact leak these timeouts
    exist to prevent."""
    token_iter = _stream_llm_tokens(system_prompt, user_message, history=history).__aiter__()
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
            yield token
    finally:
        await token_iter.aclose()


async def retrieve_for_account(
    scope: Scope,
    *,
    question: str,
    history: list[dict] | None = None,
    locale: str = "es",
    age_months: int | None = None,
    baby_name: str | None = None,
) -> Retrieved:
    """Her own record and the clinical evidence for one question (dual RAG).

    The account surfaces' `retrieve` in the agent graph: the chat lends it,
    and so does the agent for a plan or a question. Patient chunks (or, for
    "my glucose curve last year", the structured observations) PLUS the
    pediatric guidelines, in two citation namespaces:

    - citations: list[ChatCitation] into her documents ([N] markers)
    - evidence: EvidenceMatch rows, rendered as [ev_N] cards

    Scoped to one child (audit 4.1). Raises when the embedding cannot be
    computed; the surface turns that into its error event.

    The two halves embed different text when she writes in French or English:
    her documents are searched with what she wrote, the Spanish corpus with
    its Spanish rendering (agent/corpus_query.py). Both go in one embedding
    call, so the second vector costs no extra round trip.

    `age_months` and `baby_name` are the active child's, for
    settings.implicit_subject_expansion (agent/implicit_subject.py): her name
    counts as the subject, and her age goes into "Mi bebé de N meses: ...".
    """
    citations: list[ChatCitation] = []
    evidence_embedding: list[float] | None = None

    # Elliptical follow-ups ("¿y ese valor?") embed poorly on their own —
    # augment the retrieval query with the tail of the conversation. Temporal
    # intent detection still runs on the raw question.
    retrieval_query = question
    if history:
        tail = " ".join(m["content"] for m in history[-2:] if isinstance(m.get("content"), str))
        retrieval_query = f"{tail[-1000:]}\n{question}"
    corpus_text = await corpus_query(retrieval_query, locale)
    # Her words rendered in the corpus's terms, a second evidence search in the
    # same embedding call (agent/lay_terms.py). Off by default, and then the
    # lexicon is not read. The temporal path asks for her own lab curve, which
    # no lay word names, so it searches as before.
    widened = lay_terms.expanded_query(corpus_text) if settings.lay_query_expansion else None
    widened_embedding: list[float] | None = None
    # The baby she did not name, put back, as its own evidence search
    # (agent/implicit_subject.py). Off by default, and then not read. Like the
    # lexicon, only on the standard path.
    subject = (
        implicit_subject.subject_query(
            corpus_text, locale=locale, spoken=retrieval_query, age_months=age_months,
            name=baby_name,
        )
        if settings.implicit_subject_expansion else None
    )
    subject_embedding: list[float] | None = None

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
            qe = await embed_texts([corpus_text])
            evidence_embedding = qe[0] if qe else None
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
        texts = [retrieval_query]
        if corpus_text != retrieval_query:
            texts.append(corpus_text)
        corpus_index = len(texts) - 1
        if widened is not None:
            texts.append(widened)
        widened_index = len(texts) - 1
        if subject is not None:
            texts.append(subject)
        query_embeds = await embed_texts(texts)
        if not query_embeds:
            raise RuntimeError("embed_texts returned empty — cannot retrieve chunks")
        query_embedding = query_embeds[0]
        evidence_embedding = query_embeds[corpus_index]
        if widened is not None and len(query_embeds) > widened_index:
            widened_embedding = query_embeds[widened_index]
        if subject is not None and len(query_embeds) > len(texts) - 1:
            subject_embedding = query_embeds[len(texts) - 1]
        chunks = await retrieve_relevant_chunks(
            scope=scope,
            query_embedding=query_embedding,
            top_k=8,
            max_distance=settings.patient_max_distance,
            # The lexical half matches the words she just typed. The history
            # tail in `retrieval_query` is for the embedding, which needs the
            # conversation to resolve "and at 8 months?"; fed to a keyword
            # search it would only dilute the question.
            query_text=question,
            locale=locale,
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
    evidence_matches = await _retrieve_evidence_for_query(
        evidence_embedding, query_text=question, locale=locale
    )
    also = [
        await _retrieve_evidence_for_query(extra, query_text=question, locale=locale)
        for extra in (widened_embedding, subject_embedding) if extra is not None
    ]
    if also:
        evidence_matches = merge_by_best_distance(
            [evidence_matches, *also], top_k=4, relative_margin=settings.evidence_relative_margin
        )
    return Retrieved(
        evidence=evidence_matches, patient_context=patient_context or None, citations=citations
    )


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
    """The chat's turn: the agent graph (agent/graph.py, AGENT_GRAPH step 5).

    guard -> route -> retrieve (her record + evidence) -> decide -> plan |
    answer -> compose, streamed. The chat page shows text and source cards
    and nothing else, so its graph has no buttons (a fever without a reading
    is answered with what there is) and no writes (a diary line is answered,
    not recorded); her own data is a question over her record.

    `age_months` is the active profile's age, resolved by the caller (the
    router and the agent both have a session; this function must not open
    one mid-stream). It gates the age-dependent red flags, above all "under
    3 months with a fever of 38 C or more" (NICE NG143 1.2.12). When it is
    None the detector still runs on any age the parent wrote in the question
    itself.

    `profile_id` is the SAME resolved profile the age came from, and it is
    what keeps the two children of one account apart: retrieval and the
    temporal query are both scoped to it (audit 4.1). None means "the whole
    account", which is what an account with no profile at all still gets.

    The guarantees the chat carried before the graph are now the graph's:
    red flags first, ahead of retrieval and any model call (audit 3.3), and
    the hard refusal in code when nothing survived the cut-offs on either
    side (no evidence AND nothing of her record).
    """
    scope = Scope(user_id=user_id, profile_id=profile_id)

    # Names are looked up at call time, so the tests' patches on this module
    # (embed_texts, retrieve_relevant_chunks, _stream_llm_tokens, ...) reach
    # the graph.
    async def _route(message: str, **kwargs):
        return await log_route("chat", message, **kwargs)

    async def _retrieve(state) -> Retrieved:
        facts = state.get("facts")
        return await retrieve_for_account(
            scope, question=state["message"], history=history, locale=locale,
            age_months=facts.age_months if facts is not None else None,
            baby_name=facts.display_name if facts is not None else None,
        )

    def _stream(system_prompt: str, user_message: str) -> AsyncIterator[str]:
        return _guarded_stream(system_prompt, user_message, history=history)

    deps = GraphDeps(route=_route, retrieve=_retrieve, stream=_stream, can_ask=False)
    state = {
        "surface": "chat",
        "locale": locale,
        "country": country,
        "message": question,
        "account": True,
        "facts": ProfileFacts(profile_id, None, None, None, age_months),
        "history": history or [],
    }
    try:
        async for event in stream_graph(state, deps):
            if event["type"] == "token":
                yield ChatEvent(type="token", content=event["content"])
            elif event["type"] == "final":
                final = event["state"]
                yield ChatEvent(
                    type="final",
                    citations=list(final.get("citations") or []),
                    evidence_citations=list(final.get("evidence_citations") or []),
                )
    except Exception as exc:  # noqa: BLE001 — surface to client as error event
        logger.exception("answer_question_streaming failed: %s", exc)
        yield ChatEvent(type="error", content=str(exc))
