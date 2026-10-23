"""The agent graph (docs/specs/AGENT_GRAPH.md), build step 2: the demo.

    guard -> admit -> route -> retrieve -> decide -> plan | answer | experience_only
                                                        -> compose

Until this module every question got the four-section action plan, even
"¿a qué edad gatean?", and the route node (agent/route.py) was only logged.
Here its decision picks the contract: `question` gets the short answer
(answer_contract shape "question"), everything else keeps the plan, which is
the path with the most safeguards.

What the graph guarantees, whatever surface runs it:

  * `guard` runs first, deterministically (clinical/red_flags), and a flagged
    message goes straight to `compose`: no spending gate, no route, no
    embedding, no model. A frightened parent is never told "come back
    tomorrow".
  * `decide` fixes `kind` from the clinical evidence alone. Experience (what
    other mothers say) is read only afterwards, feeds only the plan, and with
    no evidence may only replace the refusal under its own fenced contract
    (decision 3).
  * Generation failing costs the answer, not the sources (`evidence_only`).

Surfaces inject what costs money or reaches a network through `GraphDeps`, so
the demo keeps its own provider and spending gate, and the tests run every
path without a key or a database.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypedDict

# langgraph depends on langsmith, whose tracer ships the whole state (a baby's
# health question, her record) to a US service when two environment variables
# say so. Off by construction, before langgraph is imported, so no deploy-time
# variable can turn it on for this process.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.runtime import Runtime  # noqa: E402

from adelia.agent.route import RouteDecision  # noqa: E402
from adelia.clinical import red_flags  # noqa: E402
from adelia.config import settings  # noqa: E402
from adelia.db import AsyncSessionLocal  # noqa: E402
from adelia.enrichment.evidence_retrieval import (  # noqa: E402
    evidence_citations_for_response,
    format_evidence_for_prompt,
    format_experience_for_prompt,
)
from adelia.enrichment.profile_service import ProfileFacts  # noqa: E402
from adelia.services.answer_contract import (  # noqa: E402
    PLAN_HEADINGS,
    chat_system_prompt,
    experience_only_contract,
    experience_only_opening,
    interface_disclaimer,
    no_evidence_reply,
    red_flag_reply,
)

logger = logging.getLogger(__name__)

DEFAULT_LOCALE = "es"


class GraphUnavailable(Exception):
    """Retrieval could not run (no key, provider down). The surface says so
    (the demo answers 503); the graph never improvises an answer instead."""


class AgentState(TypedDict, total=False):
    # Input
    surface: str
    locale: str
    message: str
    account: bool
    facts: ProfileFacts | None
    # Decisions
    flag: Any
    intent: str
    intent_confidence: float
    intent_via: str
    missing: list[str]
    # Retrieval
    query_embedding: list[float]
    evidence: list
    experience: list
    kind: str
    # Output
    answer: str
    evidence_citations: list[dict]
    disclaimer: str


Generate = Callable[[str, str], Awaitable[str]]


@dataclass(frozen=True)
class GraphDeps:
    """What a surface lends the graph for one run.

    `route` is `agent.route.route` with the surface's provider bound (and,
    usually, its log line). `admit` is the surface's spending gate, called
    after the guard and before the first paid call; it raises to refuse.
    `patient_context` is the record block the model may cite as [N] (the
    demo's invented baby); None when there is no record.
    """

    route: Callable[..., Awaitable[RouteDecision]]
    embed: Callable[[list[str]], Awaitable[list[list[float]]]]
    retrieve_evidence: Callable[..., Awaitable[list]]
    retrieve_experience: Callable[..., Awaitable[list]]
    generate: Generate
    admit: Callable[[], Awaitable[None]] | None = None
    patient_context: str | None = None
    retrieval_text: Callable[[str], str] = field(default=lambda message: message)


def _lang(state: AgentState) -> str:
    locale = state.get("locale") or DEFAULT_LOCALE
    return locale if locale in PLAN_HEADINGS else DEFAULT_LOCALE


def _age(state: AgentState) -> int | None:
    facts = state.get("facts")
    return facts.age_months if facts is not None else None


# --- guard, admit, route ----------------------------------------------------


async def guard(state: AgentState) -> dict:
    """Red flags, in code, before anything else (audit 3.3)."""
    locale = state.get("locale") or DEFAULT_LOCALE
    flag = red_flags.detect(state["message"], locale=locale, age_months=_age(state))
    if flag is None:
        return {"flag": None}
    logger.info("graph: red flag %s fired (surface=%s)", flag.code, state.get("surface"))
    return {
        "flag": flag,
        "kind": "red_flag",
        "answer": red_flag_reply(flag.code, locale),
        "evidence_citations": [red_flags.citation_for(flag)],
    }


def _after_guard(state: AgentState) -> str:
    return "compose" if state.get("flag") is not None else "admit"


async def admit(state: AgentState, runtime: Runtime[GraphDeps]) -> dict:
    """The surface's spending gate. A refusal propagates to the caller."""
    if runtime.context.admit is not None:
        await runtime.context.admit()
    return {}


async def route_node(state: AgentState, runtime: Runtime[GraphDeps]) -> dict:
    """What does she want? Rules first, then the small model under its deadline."""
    decision = await runtime.context.route(
        state["message"],
        locale=state.get("locale") or DEFAULT_LOCALE,
        has_account=bool(state.get("account")),
        facts=state.get("facts"),
    )
    return {
        "intent": decision.intent,
        "intent_confidence": decision.confidence,
        "intent_via": decision.via,
        "missing": list(decision.missing),
    }


# --- retrieve and decide ----------------------------------------------------


async def retrieve(state: AgentState, runtime: Runtime[GraphDeps]) -> dict:
    deps = runtime.context
    try:
        embeds = await deps.embed([deps.retrieval_text(state["message"])])
    except Exception as exc:  # noqa: BLE001 - no key, no network, provider down
        logger.warning("graph: embedding failed (%s)", type(exc).__name__)
        raise GraphUnavailable("embedding failed") from exc
    if not embeds:
        raise GraphUnavailable("embedding returned nothing")
    async with AsyncSessionLocal() as session:
        evidence = await deps.retrieve_evidence(
            session,
            query_embedding=embeds[0],
            specialties=["pediatrics"],
            top_k=4,
            max_distance=settings.evidence_max_distance,
            relative_margin=settings.evidence_relative_margin,
        )
    return {"evidence": list(evidence), "query_embedding": embeds[0]}


async def decide(state: AgentState) -> dict:
    """`kind` from the clinical evidence alone; experience never decides."""
    return {"kind": "answer" if state.get("evidence") else "no_evidence"}


def _after_decide(state: AgentState) -> str:
    if state["kind"] == "no_evidence":
        return "experience_only"
    if state.get("intent") == "question":
        return "answer"
    return "plan"


async def _experience_for(state: AgentState, deps: GraphDeps) -> list:
    """Best-effort by design: a failure costs the section, never the request."""
    try:
        async with AsyncSessionLocal() as session:
            return list(await deps.retrieve_experience(
                session,
                query_embedding=state["query_embedding"],
                top_k=3,
                max_distance=settings.evidence_max_distance,
                relative_margin=settings.evidence_relative_margin,
            ))
    except Exception as exc:  # noqa: BLE001 - the section is optional, the answer is not
        logger.warning("graph: experience retrieval failed (%s)", type(exc).__name__)
        return []


# --- plan and answer --------------------------------------------------------


def _user_message(state: AgentState, deps: GraphDeps, experience: list) -> str:
    blocks = [f"Pregunta del usuario: {state['message']}\n"]
    if deps.patient_context:
        blocks.append(f"## Patient data (cite as [N]):\n{deps.patient_context}")
    blocks.append(format_evidence_for_prompt(state["evidence"]))
    if experience:
        blocks.append(format_experience_for_prompt(experience))
    return "\n\n".join(blocks)


async def _compose_with_model(
    state: AgentState, deps: GraphDeps, *, shape: str, experience: list
) -> dict:
    locale = state.get("locale") or DEFAULT_LOCALE
    try:
        answer = await deps.generate(
            chat_system_prompt(locale, shape=shape),
            _user_message(state, deps, experience),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("graph: generation failed (%s)", type(exc).__name__)
        # Retrieval worked, generation did not: the corpus fragments are the
        # honest thing to show, under a "could not compose an answer" note.
        return {"kind": "evidence_only", "answer": "", "experience": []}
    return {"answer": answer, "experience": experience}


async def plan(state: AgentState, runtime: Runtime[GraphDeps]) -> dict:
    """The action plan, and the one place experience may add a section."""
    experience = await _experience_for(state, runtime.context)
    return await _compose_with_model(state, runtime.context, shape="plan", experience=experience)


async def answer(state: AgentState, runtime: Runtime[GraphDeps]) -> dict:
    """A fact or an explanation: one sentence, up to three cited bullets."""
    return await _compose_with_model(state, runtime.context, shape="question", experience=[])


# --- experience only (decision 3) -------------------------------------------

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


async def experience_only(state: AgentState, runtime: Runtime[GraphDeps]) -> dict:
    """No evidence: the coded refusal, or what other mothers say, fenced.

    A fixed opening sentence from the contract, then one "Lo que cuentan
    otras madres" section the model wrote from the [ex_N] fragments and
    nothing else. No patient data goes into the prompt: there is nothing
    clinical to relate it to, and a [N] marker in the output discards it.
    """
    lang = _lang(state)
    refusal = {"kind": "no_evidence", "answer": no_evidence_reply(lang), "experience": []}
    experience = await _experience_for(state, runtime.context)
    if not experience:
        return refusal
    user_message = "\n\n".join([
        f"Pregunta del usuario: {state['message']}\n",
        format_experience_for_prompt(experience),
    ])
    try:
        body = await runtime.context.generate(experience_only_contract(lang), user_message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("graph: experience-only generation failed (%s)", type(exc).__name__)
        return refusal
    if not experience_only_body_is_clean(body, lang):
        logger.info("graph: experience-only output discarded, refusing instead")
        return refusal
    return {
        "kind": "experience_only",
        "answer": f"{experience_only_opening(lang)}\n\n{body.strip()}",
        "experience": experience,
    }


# --- compose ----------------------------------------------------------------


async def compose(state: AgentState) -> dict:
    """The response the surfaces send: citations by kind, and the fixed disclaimer.

    Experience cards go after the clinical ones, labelled by `tier`. The
    evidence_only branch shows the clinical list alone: without an answer
    around them to say which is which, a blog post in that list would read
    as a guideline.
    """
    kind = state["kind"]
    if kind == "red_flag":
        citations = list(state.get("evidence_citations") or [])
    elif kind == "no_evidence":
        citations = []
    else:
        citations = []
        if kind in ("answer", "evidence_only"):
            citations = evidence_citations_for_response(state.get("evidence") or [])
        if kind in ("answer", "experience_only") and state.get("experience"):
            citations += evidence_citations_for_response(
                state["experience"], tag_prefix="ex", tier="experience"
            )
    return {
        "evidence_citations": citations,
        "disclaimer": interface_disclaimer(state.get("locale") or DEFAULT_LOCALE),
        "answer": state.get("answer", ""),
    }


def build_graph():
    g = StateGraph(AgentState, context_schema=GraphDeps)
    g.add_node("guard", guard)
    g.add_node("admit", admit)
    g.add_node("route", route_node)
    g.add_node("retrieve", retrieve)
    g.add_node("decide", decide)
    g.add_node("plan", plan)
    g.add_node("answer", answer)
    g.add_node("experience_only", experience_only)
    g.add_node("compose", compose)

    g.add_edge(START, "guard")
    g.add_conditional_edges("guard", _after_guard, ["compose", "admit"])
    g.add_edge("admit", "route")
    g.add_edge("route", "retrieve")
    g.add_edge("retrieve", "decide")
    g.add_conditional_edges("decide", _after_decide, ["plan", "answer", "experience_only"])
    for node in ("plan", "answer", "experience_only"):
        g.add_edge(node, "compose")
    g.add_edge("compose", END)
    return g.compile()


GRAPH = build_graph()


async def run_graph(state: AgentState, deps: GraphDeps) -> AgentState:
    """One turn through the graph. Raises GraphUnavailable, or whatever
    `deps.admit` raises; never returns a partial answer."""
    return await GRAPH.ainvoke(state, context=deps)
