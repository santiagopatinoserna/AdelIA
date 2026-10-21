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

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from adelia.clinical import red_flags
from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.demo.fixture import (
    DEFAULT_LOCALE,
    demo_patient_context,
    demo_profile,
    retrieval_query,
)
from adelia.enrichment.evidence_retrieval import (
    evidence_citations_for_response,
    format_evidence_for_prompt,
    retrieve_evidence,
)
from adelia.services import funnel
from adelia.services.answer_contract import (
    chat_system_prompt,
    interface_disclaimer,
    no_evidence_reply,
    red_flag_reply,
)
from adelia.services.chat_orchestrator import generate_answer
from adelia.workers.embed import embed_texts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])

DEMO_DISABLED_DETAIL = "Demo disabled"
DEMO_BUDGET_DETAIL = "Demo budget exhausted for today"


class DemoQuestion(BaseModel):
    question: str = Field(min_length=3)
    locale: str = DEFAULT_LOCALE


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

    The response shape mirrors the chat's `final` SSE event so the demo page
    renders citations with the same components:

        answer              the text to show (always present)
        evidence_citations  [ev_N] cards from evidence_chunks, with real URLs
        kind                "answer" | "red_flag" | "no_evidence" — what the
                            code decided, so the page can style a referral
                            differently from an answer
        disclaimer          the fixed clinical line, in the visitor's language
    """
    _require_demo()
    locale = (payload.locale or DEFAULT_LOCALE).split("-")[0].lower()
    question = payload.question.strip()
    if len(question) > settings.demo_max_question_chars:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Question longer than {settings.demo_max_question_chars} characters",
        )

    # Red flags before anything else, exactly as in the chat: no embedding, no
    # retrieval, no model. A demo that dosed paracetamol for a feverish
    # two-month-old would be a worse advert than no demo at all.
    #
    # It is also ahead of the budget, deliberately: a referral costs one regex
    # and nothing else, so a parent who arrives frightened must never be told
    # "come back tomorrow". The consequence is that the "demo_ask" counter
    # measures paid attempts, not questions.
    flag = red_flags.detect(question, locale=locale, age_months=None)
    if flag is not None:
        logger.info("demo: red flag %s fired", flag.code)
        return {
            "kind": "red_flag",
            "answer": red_flag_reply(flag.code, locale),
            "evidence_citations": [red_flags.citation_for(flag)],
            "disclaimer": interface_disclaimer(locale),
        }

    # Daily ceiling. Counted with the atomic upsert that returns the new
    # value, so concurrent callers cannot both see "one under the limit".
    # A counting failure must not open the tap: treat it as exhausted.
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

    try:
        # The embedding carries the question WITHOUT the invented baby's name: a
        # first name is not clinical content and, measured, it pushed the demo's
        # own first suggestion past the relevance cut-off (see fixture.py).
        embeds = await embed_texts([retrieval_query(question, locale)])
    except Exception as exc:  # noqa: BLE001 — no key, no network, provider down
        logger.warning("demo: embedding failed (%s)", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Demo unavailable"
        )
    if not embeds:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Demo unavailable"
        )

    async with AsyncSessionLocal() as session:
        matches = await retrieve_evidence(
            session,
            query_embedding=embeds[0],
            specialties=["pediatrics"],
            top_k=4,
            max_distance=settings.evidence_max_distance,
            relative_margin=settings.evidence_relative_margin,
        )

    # Nothing in the corpus supports an answer: refuse in code, as the chat
    # does, rather than let the model improvise about somebody's baby.
    if not matches:
        return {
            "kind": "no_evidence",
            "answer": no_evidence_reply(locale),
            "evidence_citations": [],
            "disclaimer": interface_disclaimer(locale),
        }

    citations = evidence_citations_for_response(matches)
    user_message = "\n\n".join(
        [
            f"Pregunta del usuario: {question}\n",
            f"## Patient data (cite as [N]):\n{demo_patient_context(locale)}",
            format_evidence_for_prompt(matches),
        ]
    )
    try:
        answer = await generate_answer(
            chat_system_prompt(locale),
            user_message,
            provider=settings.demo_llm_provider or None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("demo: generation failed (%s)", exc)
        # Retrieval worked, generation did not. The corpus fragments are the
        # honest thing to show: they are the real citations the demo promises,
        # and the page renders them under a "could not compose an answer" note.
        return {
            "kind": "evidence_only",
            "answer": "",
            "evidence_citations": citations,
            "disclaimer": interface_disclaimer(locale),
        }

    return {
        "kind": "answer",
        "answer": answer,
        "evidence_citations": citations,
        "disclaimer": interface_disclaimer(locale),
    }
