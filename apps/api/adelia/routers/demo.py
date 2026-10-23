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
import re

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from adelia.agent.route import spawn_route_log
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
    format_experience_for_prompt,
    retrieve_evidence,
    retrieve_experience,
)
from adelia.enrichment.profile_service import ProfileFacts
from adelia.services import funnel
from adelia.services.answer_contract import (
    PLAN_HEADINGS,
    chat_system_prompt,
    experience_only_contract,
    experience_only_opening,
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
        evidence_citations  [ev_N] cards from evidence_chunks, with real URLs,
                            followed by the [ex_N] cards of the experience
                            tier (what other mothers say), each carrying its
                            `tier` so the page labels and orders them
        kind                "answer" | "red_flag" | "no_evidence" |
                            "evidence_only" | "experience_only" — what the
                            code decided, so the page can style a referral
                            differently from an answer
        disclaimer          the fixed clinical line, in the visitor's language

    The experience tier (Kenza, 2026-10-22) is read only AFTER the clinical
    retrieval has decided whether there is evidence, and a red flag never
    gets that far. With evidence it feeds one optional section of the plan
    and nothing else (answer_contract), so a failure looking it up costs the
    section, not the answer. Without evidence (AGENT_GRAPH, decision 3) it is
    the only thing that may replace the refusal: kind `experience_only`, a
    fixed opening sentence and that one section, never a plan, never a
    doctor section, and the code discards the model's output if it strays.
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

    # Agent graph, build step 1 (docs/specs/AGENT_GRAPH.md): the route node
    # runs after the guard and is only measured. One log line, in the
    # background, with the demo's own provider; the answer below does not
    # read it. The demo baby's age is on the page, so the router knows it.
    spawn_route_log(
        "demo",
        question,
        locale=locale,
        has_account=False,
        facts=ProfileFacts(None, None, None, None, demo_profile(locale)["age_months"]),
        provider=settings.demo_llm_provider or None,
    )

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
    # does, rather than let the model improvise about somebody's baby. The
    # one thing that may replace the refusal is what other mothers say
    # (AGENT_GRAPH, decision 3), and only when that tier has a match.
    if not matches:
        experience = await _experience_for(embeds[0])
        if experience:
            reply = await _experience_only_reply(question, experience, locale)
            if reply is not None:
                return reply
        return {
            "kind": "no_evidence",
            "answer": no_evidence_reply(locale),
            "evidence_citations": [],
            "disclaimer": interface_disclaimer(locale),
        }

    citations = evidence_citations_for_response(matches)

    # What other mothers say: same engine, the other tier, the same cut-offs.
    # Best-effort by design, and only now that `kind` is settled.
    experience = await _experience_for(embeds[0])

    blocks = [
        f"Pregunta del usuario: {question}\n",
        f"## Patient data (cite as [N]):\n{demo_patient_context(locale)}",
        format_evidence_for_prompt(matches),
    ]
    if experience:
        blocks.append(format_experience_for_prompt(experience))
    user_message = "\n\n".join(blocks)
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

    # Experience cards after the clinical ones, labelled by `tier`. The
    # evidence_only branch above shows the clinical list alone: without an
    # answer around them to say which is which, a blog post in that list
    # would read as a guideline.
    return {
        "kind": "answer",
        "answer": answer,
        "evidence_citations": citations + evidence_citations_for_response(
            experience, tag_prefix="ex", tier="experience"
        ),
        "disclaimer": interface_disclaimer(locale),
    }


async def _experience_for(query_embedding: list[float]) -> list:
    """What other mothers say: same engine, the other tier, the same cut-offs.

    Best-effort by design: a failure here costs the section (or, with no
    evidence, the chance of an experience-only answer), never the request.
    """
    try:
        async with AsyncSessionLocal() as session:
            return await retrieve_experience(
                session,
                query_embedding=query_embedding,
                top_k=3,
                max_distance=settings.evidence_max_distance,
                relative_margin=settings.evidence_relative_margin,
            )
    except Exception as exc:  # noqa: BLE001 — the section is optional, the answer is not
        logger.warning("demo: experience retrieval failed (%s)", type(exc).__name__)
        return []


_HEADING = re.compile(r"^##\s+(.*?)\s*$", re.MULTILINE)
_CITATION = re.compile(r"\[([^\]]*)\]")
_EXPERIENCE_TAG = re.compile(r"^ex_\d+$")


def experience_only_body_is_clean(text: str, locale: str) -> bool:
    """Whether the model's output is exactly one mothers section with [ex_N] bullets.

    The rule the model reads (experience_only_contract) asks for the shape;
    this is the check that does not depend on the model obeying. Anything
    else, and the caller refuses as if there were no experience at all:
    another section (a doctor section above all), any citation that is not
    [ex_N] (a [ev_N] it was never given, a [N] patient marker), text before
    the heading, or a bullet with no citation.
    """
    text = text.strip()
    if not text:
        return False
    headings = _HEADING.findall(text)
    if headings != [PLAN_HEADINGS[locale]["mothers"]]:
        return False
    if not text.startswith("## "):
        return False
    citations = _CITATION.findall(text)
    if not citations or any(not _EXPERIENCE_TAG.match(c) for c in citations):
        return False
    bullets = [ln for ln in text.splitlines()[1:] if ln.strip()]
    if not bullets or not all(ln.lstrip().startswith(("-", "*")) for ln in bullets):
        return False
    return all(_CITATION.search(ln) for ln in bullets)


async def _experience_only_reply(question: str, experience: list, locale: str) -> dict | None:
    """The experience-only answer, or None to fall back to the refusal.

    Kind `experience_only` (AGENT_GRAPH, decision 3): a fixed opening
    sentence from the contract, then one "Lo que cuentan otras madres"
    section the model wrote from the [ex_N] fragments and nothing else. No
    patient data goes into the prompt: there is nothing clinical to relate it
    to, and a [N] marker in the output is one of the things that discard it.
    """
    lang = locale if locale in PLAN_HEADINGS else DEFAULT_LOCALE
    user_message = "\n\n".join([
        f"Pregunta del usuario: {question}\n",
        format_experience_for_prompt(experience),
    ])
    try:
        body = await generate_answer(
            experience_only_contract(lang),
            user_message,
            provider=settings.demo_llm_provider or None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("demo: experience-only generation failed (%s)", exc)
        return None
    if not experience_only_body_is_clean(body, lang):
        logger.info("demo: experience-only output discarded, refusing instead")
        return None
    return {
        "kind": "experience_only",
        "answer": f"{experience_only_opening(lang)}\n\n{body.strip()}",
        "evidence_citations": evidence_citations_for_response(
            experience, tag_prefix="ex", tier="experience"
        ),
        "disclaimer": interface_disclaimer(lang),
    }
