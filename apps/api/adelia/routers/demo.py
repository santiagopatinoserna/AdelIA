"""The public demo (audit 4.6): ask a real question, get real citations.

Until 2026-09-01 there was no way to see AdelIA answer anything without an
email, a magic link and a credit card, in that order. This router is the way:
no account, no session, no cookie.

What it can reach, and what it deliberately cannot:

  reads   evidence_chunks (the real clinical corpus) and a module-level dict
          (adelia.demo.fixture) holding an invented baby;
  writes  exactly one integer, the daily "demo_ask" counter, which is also the
          spending budget;
  cannot  see, create or modify any user, profile, document, chunk or chat
          session. There is no user_id anywhere in this file.

It is also a public endpoint that spends money on the LLM, so it carries three
brakes: a per-minute rate limit per IP (ratelimit.ROUTE_BUDGETS), a hard daily
ceiling counted in Postgres so it survives a restart, and a question-length
cap. Past the ceiling it answers 429 and says so.

The safety contract is the product's, not a demo-grade copy of it: red flags
fire first and never reach the model, an answer with no evidence behind it is
refused in code, and the same system prompt governs the wording.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from adelia.agent.graph import GraphDeps, GraphUnavailable, run_graph
from adelia.agent.route import log_route
from adelia.config import settings
from adelia.demo.fixture import (
    DEFAULT_LOCALE,
    demo_patient_context,
    demo_profile,
    retrieval_query,
)
from adelia.enrichment.evidence_retrieval import retrieve_evidence, retrieve_experience
from adelia.enrichment.profile_service import ProfileFacts
from adelia.services import funnel
from adelia.services.chat_orchestrator import generate_answer
from adelia.workers.embed import embed_texts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])

DEMO_DISABLED_DETAIL = "Demo disabled"
DEMO_BUDGET_DETAIL = "Demo budget exhausted for today"


class Clarification(BaseModel):
    """Her answer to last turn's clarify question (AGENT_GRAPH step 3).

    Only the two facts the graph knows how to ask; the value is checked
    against the buttons the API wrote (answer_contract.clarification_sentence)
    and anything else is ignored rather than passed to the guard or the model.
    """

    field: Literal["age", "temperature"]
    value: str = Field(min_length=1, max_length=16)


class DemoQuestion(BaseModel):
    question: str = Field(min_length=3)
    locale: str = DEFAULT_LOCALE
    #: Present on the second turn of a clarify: `question` is the first
    #: turn's question again, and this is the button she pressed.
    clarification: Clarification | None = None


def _require_demo() -> None:
    if not settings.demo_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=DEMO_DISABLED_DETAIL
        )


@router.get("/profile")
async def get_demo_profile(locale: str = Query(DEFAULT_LOCALE)) -> dict:
    """The invented baby the demo page renders. Same dict the prompt reads."""
    _require_demo()
    return demo_profile(locale)


@router.post("/ask")
async def ask_demo(payload: DemoQuestion) -> dict:
    """Answer one question about the demo baby, citing the real corpus.

    Runs the agent graph (agent/graph.py, AGENT_GRAPH build step 2). The
    response shape mirrors the chat's `final` SSE event so the demo page
    renders citations with the same components:

        answer              the text to show (always present)
        evidence_citations  [ev_N] cards from evidence_chunks, with real URLs,
                            followed by the [ex_N] cards of the experience
                            tier (what other mothers say), each carrying its
                            `tier` so the page labels and orders them
        kind                "answer" | "red_flag" | "no_evidence" |
                            "evidence_only" | "experience_only" | "clarify" - what the
                            code decided, so the page can style a referral
                            differently from an answer
        intent              what the route node decided ("question" gets the
                            short answer, "plan" the action plan, "clarify"
                            one question); null on a red flag, never routed
        clarify             only with kind "clarify": {field, question,
                            options: [{value, label}], skip: {value, label}};
                            the page sends the value back as `clarification`
        disclaimer          the fixed clinical line, in the visitor's language

    The graph lends nothing of the demo's to a real account and vice versa:
    the demo brings its own provider (`demo_llm_provider`), its invented baby
    as the only record, and its daily budget as the spending gate.
    """
    _require_demo()
    locale = (payload.locale or DEFAULT_LOCALE).split("-")[0].lower()
    question = payload.question.strip()
    if len(question) > settings.demo_max_question_chars:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Question longer than {settings.demo_max_question_chars} characters",
        )
    provider = settings.demo_llm_provider or None

    # Names are looked up at call time, not bound at import, so the tests'
    # patches on this module (embed_texts, retrieve_*, generate_answer,
    # log_route) reach the graph.
    async def _route(message: str, **kwargs):
        return await log_route("demo", message, provider=provider, **kwargs)

    async def _embed(texts: list[str]):
        return await embed_texts(texts)

    async def _retrieve_evidence(session, **kwargs):
        return await retrieve_evidence(session, **kwargs)

    async def _retrieve_experience(session, **kwargs):
        return await retrieve_experience(session, **kwargs)

    async def _generate(system_prompt: str, user_message: str) -> str:
        return await generate_answer(system_prompt, user_message, provider=provider)

    deps = GraphDeps(
        route=_route,
        embed=_embed,
        retrieve_evidence=_retrieve_evidence,
        retrieve_experience=_retrieve_experience,
        generate=_generate,
        admit=_admit,
        patient_context=demo_patient_context(locale),
        # The embedding carries the question WITHOUT the invented baby's name:
        # a first name is not clinical content and, measured, it pushed the
        # demo's own first suggestion past the relevance cut-off (fixture.py).
        retrieval_text=lambda message: retrieval_query(message, locale),
    )
    # The red flag runs before the gate, deliberately: a referral costs one
    # regex and nothing else, so a parent who arrives frightened must never
    # be told "come back tomorrow". The "demo_ask" counter therefore measures
    # paid attempts, not questions. The demo baby's age is on the page, so the
    # guard and the router both know it.
    try:
        out = await run_graph(
            {
                "surface": "demo",
                "locale": locale,
                "message": question,
                "account": False,
                "facts": ProfileFacts(None, None, None, None, demo_profile(locale)["age_months"]),
                "clarification": (
                    payload.clarification.model_dump() if payload.clarification else None
                ),
            },
            deps,
        )
    except GraphUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Demo unavailable"
        )
    response = {
        "kind": out["kind"],
        "intent": out.get("intent") if out["kind"] != "red_flag" else None,
        "answer": out.get("answer", ""),
        "evidence_citations": out.get("evidence_citations", []),
        "disclaimer": out["disclaimer"],
    }
    if out["kind"] == "clarify":
        response["clarify"] = out["clarify"]
    return response


async def _admit() -> None:
    """The daily ceiling, the demo's spending gate.

    Counted with the atomic upsert that returns the new value, so concurrent
    callers cannot both see "one under the limit". A counting failure must
    not open the tap: treat it as exhausted.
    """
    try:
        used = await funnel.bump("demo_ask")
    except Exception:  # noqa: BLE001
        logger.exception("demo: could not record the daily counter; refusing")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=DEMO_BUDGET_DETAIL
        )
    if used > settings.demo_daily_budget:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=DEMO_BUDGET_DETAIL
        )
