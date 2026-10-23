"""The agent graph (docs/specs/AGENT_GRAPH.md): one graph, three surfaces.

    absorb -> write                                  (a confirmed card)
           -> guard -> admit -> route -> clarify     (one question, buttons)
                                       | record      (a diary line, account only)
                                       | track       (her own data: tools, 3 steps)
                                       | retrieve -> decide -> plan | answer | experience_only
                    -> compose

Until build step 2 every question got the four-section action plan, even
"¿a qué edad gatean?", the agent behind /dashboard ran its own model-and-
tools loop (agent/orchestrator.run_agent_turn, retired in step 5) and the
chat its own pipeline. Here the route node's decision picks the contract,
and the demo, the chat and the agent run this same graph.

What the graph guarantees, whatever surface runs it:

  * `guard` runs first, deterministically (clinical/red_flags), and a flagged
    message goes straight to `compose`: no spending gate, no route, no
    embedding, no model. A frightened parent is never told "come back
    tomorrow".
  * At most one clarify question per turn, and only with buttons; the next
    turn answers with what there is (principle 2).
  * Nothing is written without a confirmation card, and what comes back from
    the card is validated again (principle 3).
  * `decide` fixes `kind` from the clinical evidence (and, with an account,
    her own record). Experience (what other mothers say) is read only
    afterwards, feeds only the plan, and with no evidence may only replace
    the refusal under its own fenced contract (decision 3).

Surfaces lend what costs money, reaches a network or a database, or that
only they can show, through `GraphDeps`:

  demo   no account; evidence + experience; buttons; no writes; JSON response
  chat   account; her record + evidence; streams; no buttons, no cards
  agent  account; her record + evidence; streams; buttons, cards, writes and
         the tool loop (`track`), which also takes what the router cannot
         place, as the agent always did

Streaming surfaces read the nodes' events (`token`, `card`, `tool_call`)
through LangGraph's custom stream (`stream_graph`); the demo reads the final
state (`run_graph`).
"""
from __future__ import annotations

import dataclasses
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol, TypedDict
from zoneinfo import ZoneInfo

# langgraph depends on langsmith, whose tracer ships the whole state (a baby's
# health question, her record) to a US service when two environment variables
# say so. Off by construction, before langgraph is imported, so no deploy-time
# variable can turn it on for this process.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from langgraph.config import get_stream_writer  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.runtime import Runtime  # noqa: E402

from adelia.agent import record as rec  # noqa: E402
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
    CLARIFY_AGE_FLOOR,
    PLAN_HEADINGS,
    chat_system_prompt,
    clarification_sentence,
    clarify_question,
    experience_only_contract,
    experience_only_opening,
    interface_disclaimer,
    missing_fact_note,
    no_evidence_reply,
    red_flag_reply,
)

logger = logging.getLogger(__name__)

DEFAULT_LOCALE = "es"
#: The time zone a diary line's "a las 5" is read in. Both countries AdelIA
#: serves today (ES, FR) are on it.
LOCAL_TZ = ZoneInfo("Europe/Madrid")


class GraphUnavailable(Exception):
    """Retrieval could not run (no key, provider down). The surface says so
    (the demo answers 503); the graph never improvises an answer instead."""


class AgentState(TypedDict, total=False):
    # Input
    surface: str
    locale: str
    country: str | None
    message: str
    account: bool
    facts: ProfileFacts | None
    history: list[dict]
    #: The card she confirmed: {"intent", "tool_name", "tool_args"}.
    card_action: dict | None
    #: Her answer to last turn's clarify question: {"field", "value"}.
    clarification: dict | None
    clarified: bool
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
    patient_context: str | None
    kind: str
    # Output
    answer: str
    streamed: bool
    citations: list
    evidence_citations: list[dict]
    disclaimer: str
    clarify: dict


Generate = Callable[[str, str], Awaitable[str]]
Stream = Callable[[str, str], AsyncIterator[str]]


@dataclass(frozen=True)
class Retrieved:
    """What an account surface's retrieval found: her record and the evidence."""

    evidence: list
    patient_context: str | None = None
    #: Citations into her own documents, in the order of the [N] markers.
    citations: list = field(default_factory=list)


class RecordStore(Protocol):
    async def save(self, draft: rec.RecordDraft) -> None: ...

    async def previous(self, kind: str, before: datetime) -> rec.RecordDraft | None: ...


@dataclass
class WriteOutcome:
    text: str
    card: dict | None = None


@dataclass(frozen=True)
class GraphDeps:
    """What a surface lends the graph for one run.

    `route` is `agent.route.route` with the surface's provider bound (and its
    log line). Retrieval is either the demo's pair (`embed` +
    `retrieve_evidence` over the corpus) or an account's `retrieve` (her
    record and the evidence, the chat pipeline). Generation is either
    `generate` (one string) or `stream` (tokens, emitted as they come).
    `admit` is the surface's spending gate, called after the guard and
    before the first paid call; it raises to refuse.
    """

    route: Callable[..., Awaitable[RouteDecision]]
    # Demo-style retrieval and generation
    embed: Callable[[list[str]], Awaitable[list[list[float]]]] | None = None
    retrieve_evidence: Callable[..., Awaitable[list]] | None = None
    retrieve_experience: Callable[..., Awaitable[list]] | None = None
    generate: Generate | None = None
    admit: Callable[[], Awaitable[None]] | None = None
    patient_context: str | None = None
    retrieval_text: Callable[[str], str] = field(default=lambda message: message)
    # Account surfaces
    retrieve: Callable[["AgentState"], Awaitable[Retrieved]] | None = None
    stream: Stream | None = None
    #: The surface can show a question with buttons (the chat page cannot).
    can_ask: bool = True
    #: The surface can show a confirmation card and write after it.
    can_write: bool = False
    record_store: RecordStore | None = None
    write_tool: Callable[[str, dict], Awaitable[WriteOutcome]] | None = None
    #: The tool loop: yields {"type": "token"|"card"|"tool_call", ...} and one
    #: final {"type": "result", "answer", "citations", "evidence_citations"}.
    track: Callable[["AgentState"], AsyncIterator[dict]] | None = None
    complete_json: Callable[..., Awaitable[str]] | None = None
    now: Callable[[], datetime] = field(default=lambda: datetime.now(LOCAL_TZ))


def _locale(state: AgentState) -> str:
    return state.get("locale") or DEFAULT_LOCALE


def _lang(state: AgentState) -> str:
    locale = _locale(state)
    return locale if locale in PLAN_HEADINGS else DEFAULT_LOCALE


def _age(state: AgentState) -> int | None:
    facts = state.get("facts")
    return facts.age_months if facts is not None else None


def _emit(event: dict) -> None:
    """Hand an event to a streaming surface (no-op when nobody streams)."""
    get_stream_writer()(event)


# --- absorb, write ------------------------------------------------------------


async def absorb(state: AgentState) -> dict:
    """Fold her answer to the clarify question into this turn.

    The line goes INTO the message, so the guard sees it ("Temperatura: 39
    °C o más") and the model reads it next to her question. An age band
    fills a missing age with the band's youngest month (CLARIFY_AGE_FLOOR),
    so the answer can only make the guard stricter; a known age is never
    overwritten. Any answer, even one we cannot read, spends the turn's one
    question: `clarified` stops a second.
    """
    answer = state.get("clarification")
    if not answer:
        return {"clarified": False}
    field_name, value = str(answer.get("field", "")), str(answer.get("value", ""))
    update: dict = {"clarified": True}
    sentence = clarification_sentence(field_name, value, _locale(state))
    if sentence is None:
        logger.info("graph: unreadable clarification ignored (field=%s)", field_name)
        return update
    update["message"] = f"{state['message']}\n{sentence}"
    facts = state.get("facts")
    if field_name == "age" and value in CLARIFY_AGE_FLOOR and (
        facts is None or facts.age_months is None
    ):
        floor = CLARIFY_AGE_FLOOR[value]
        update["facts"] = (
            dataclasses.replace(facts, age_months=floor) if facts is not None
            else ProfileFacts(None, None, None, None, floor)
        )
    return update


def _after_absorb(state: AgentState) -> str:
    action = state.get("card_action") or {}
    return "write" if action.get("intent") == "confirm" else "guard"


_RECORD_REFUSED = {
    "es": "No he podido anotarlo: los datos de la tarjeta no son válidos. Escríbemelo otra vez.",
    "en": "I could not note it: the card's data is not valid. Please write it to me again.",
    "fr": "Je n’ai pas pu le noter : les données de la carte ne sont pas valides. "
          "Réécris-le-moi.",
}


async def write(state: AgentState, runtime: Runtime[GraphDeps]) -> dict:
    """She confirmed a card: run that write, and only that one (principle 3)."""
    deps, action = runtime.context, state.get("card_action") or {}
    name, args = action.get("tool_name"), action.get("tool_args") or {}
    if name == rec.RECORD_TOOL and deps.can_write and deps.record_store is not None:
        now = deps.now()
        draft = rec.validate_args(args, now=now)
        if draft is None:
            return {"kind": "recorded", "answer": _RECORD_REFUSED[_lang(state)]}
        flag = rec.value_flag(draft, age_months=_age(state))
        if flag is not None:
            return _referral(state, flag)
        previous = await deps.record_store.previous(draft.kind, draft.observed_at)
        await deps.record_store.save(draft)
        return {
            "kind": "recorded",
            "answer": rec.recorded_reply(draft, previous, locale=_locale(state), now=now),
        }
    if deps.write_tool is None:
        return {"kind": "recorded", "answer": ""}
    outcome = await deps.write_tool(name, args)
    if outcome.card:
        _emit({"type": "card", "card": outcome.card})
    return {"kind": "recorded", "answer": outcome.text}


# --- guard, admit, route ----------------------------------------------------


def _referral(state: AgentState, flag) -> dict:
    return {
        "flag": flag,
        "kind": "red_flag",
        "answer": red_flag_reply(flag.code, _locale(state), country=state.get("country")),
        "evidence_citations": [red_flags.citation_for(flag)],
    }


async def guard(state: AgentState) -> dict:
    """Red flags, in code, before anything else (audit 3.3)."""
    flag = red_flags.detect(state["message"], locale=_locale(state), age_months=_age(state))
    if flag is None:
        return {"flag": None}
    logger.info("graph: red flag %s fired (surface=%s)", flag.code, state.get("surface"))
    return _referral(state, flag)


def _after_guard(state: AgentState) -> str:
    return "compose" if state.get("flag") is not None else "admit"


async def admit(state: AgentState, runtime: Runtime[GraphDeps]) -> dict:
    """The surface's spending gate. A refusal propagates to the caller."""
    if runtime.context.admit is not None:
        await runtime.context.admit()
    return {}


async def route_node(state: AgentState, runtime: Runtime[GraphDeps]) -> dict:
    """What does she want? Rules first, then the small model under its deadline.

    Then what this surface can do about it: a question with buttons only
    where buttons can be shown, a record only with an account and a card, the
    tool loop only where there is one (elsewhere her own data is a question
    over her record). What the router cannot place (`other`, or the fallback
    when the model is down) goes to the tool loop where there is one, as the
    agent always did, and to the plan everywhere else.
    """
    deps = runtime.context
    decision = await deps.route(
        state["message"],
        locale=_locale(state),
        has_account=bool(state.get("account")),
        facts=state.get("facts"),
    )
    intent, missing = decision.intent, list(decision.missing)
    if intent == "clarify":
        # One question, only one we can ask with buttons, and never twice in
        # a row (principle 2): otherwise answer with what there is.
        askable = [f for f in missing if clarify_question(f, _locale(state)) is not None]
        if state.get("clarified") or not askable or not deps.can_ask:
            intent = "plan"
        else:
            missing = askable[:1]
    if intent == "record" and not (
        state.get("account") and deps.can_write and deps.record_store is not None
    ):
        intent = "plan"
    if intent in ("other",) or decision.via == "fallback":
        intent = "track" if deps.track is not None else "plan"
    if intent == "track" and deps.track is None:
        intent = "question"
    return {
        "intent": intent,
        "intent_confidence": decision.confidence,
        "intent_via": decision.via,
        "missing": missing,
    }


def _after_route(state: AgentState) -> str:
    intent = state.get("intent")
    if intent in ("clarify", "record", "track"):
        return intent
    return "retrieve"


async def clarify(state: AgentState) -> dict:
    """One concrete question of one line, with two or three buttons."""
    field_name = state["missing"][0]
    question = clarify_question(field_name, _locale(state))
    payload = {"field": field_name, **question}
    # A streaming surface gets it as a card; the original message rides along
    # so the page can send it back with the button's value.
    _emit({"type": "card", "card": {
        "type": "clarify", "id": f"clarify-{field_name}",
        "payload": {**payload, "message": state["message"]}, "actions": [],
    }})
    return {"kind": "clarify", "answer": question["question"], "clarify": payload}


# --- record and track ----------------------------------------------------------


async def record(state: AgentState, runtime: Runtime[GraphDeps]) -> dict:
    """A diary line: extract, guard the value, and propose the card. No write yet."""
    deps = runtime.context
    now = deps.now()
    draft = await rec.extract_record(
        state["message"], locale=_locale(state), now=now, complete_json=deps.complete_json
    )
    flag = rec.value_flag(draft, age_months=_age(state))
    if flag is not None:
        logger.info("graph: recorded value raised %s, referral instead of the card", flag.code)
        return _referral(state, flag)
    _emit({"type": "card", "card": rec.confirm_card(draft, locale=_locale(state), now=now)})
    return {"kind": "confirm", "answer": ""}


async def track(state: AgentState, runtime: Runtime[GraphDeps]) -> dict:
    """Her own data through the tools, in a bounded loop (agent/orchestrator)."""
    result: dict = {}
    async for event in runtime.context.track(state):
        if event.get("type") == "result":
            result = event
        else:
            _emit(event)
    return {
        "kind": "tracked",
        "streamed": True,
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "evidence_citations": result.get("evidence_citations", []),
    }


# --- retrieve and decide ----------------------------------------------------


async def retrieve(state: AgentState, runtime: Runtime[GraphDeps]) -> dict:
    deps = runtime.context
    if deps.retrieve is not None:
        found = await deps.retrieve(state)
        return {
            "evidence": list(found.evidence),
            "patient_context": found.patient_context,
            "citations": list(found.citations),
        }
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
    """`kind` from the clinical evidence and her own record; experience never decides.

    Nothing survived the cut-offs on either side: the code refuses, the model
    is never asked (audit 3.1).
    """
    grounded = bool(state.get("evidence")) or bool(state.get("patient_context"))
    return {"kind": "answer" if grounded else "no_evidence"}


def _after_decide(state: AgentState) -> str:
    if state["kind"] == "no_evidence":
        return "experience_only"
    if state.get("intent") == "question":
        return "answer"
    return "plan"


async def _experience_for(state: AgentState, deps: GraphDeps) -> list:
    """Best-effort by design: a failure costs the section, never the request."""
    if deps.retrieve_experience is None or not state.get("query_embedding"):
        return []
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
    patient = state.get("patient_context") or deps.patient_context
    if patient:
        blocks.append(f"## Patient data (cite as [N]):\n{patient}")
    if state.get("evidence"):
        blocks.append(format_evidence_for_prompt(state["evidence"]))
    if experience:
        blocks.append(format_experience_for_prompt(experience))
    if state.get("clarified") and state.get("missing"):
        note = missing_fact_note(state["missing"])
        if note:
            blocks.append(note)
    return "\n\n".join(blocks)


async def _compose_with_model(
    state: AgentState, deps: GraphDeps, *, shape: str, experience: list
) -> dict:
    system = chat_system_prompt(_locale(state), shape=shape)
    user = _user_message(state, deps, experience)
    if deps.stream is not None:
        # A streaming surface: tokens go out as they come, and a provider
        # failure is the surface's error event, as it always was in the chat.
        pieces: list[str] = []
        async for piece in deps.stream(system, user):
            pieces.append(piece)
            _emit({"type": "token", "content": piece})
        return {"answer": "".join(pieces), "experience": experience, "streamed": True}
    try:
        answer = await deps.generate(system, user)
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
    Surfaces without the experience tier (the chat, the agent) refuse.
    """
    lang = _lang(state)
    refusal = {"kind": "no_evidence", "answer": no_evidence_reply(lang), "experience": []}
    deps = runtime.context
    experience = await _experience_for(state, deps)
    if not experience or deps.generate is None:
        return refusal
    user_message = "\n\n".join([
        f"Pregunta del usuario: {state['message']}\n",
        format_experience_for_prompt(experience),
    ])
    try:
        body = await deps.generate(experience_only_contract(lang), user_message)
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
    as a guideline. An answer that was not streamed token by token (a
    referral, a refusal, a recorded line) goes out as one token, so a
    streaming surface shows it like any other answer.
    """
    kind = state["kind"]
    patient = list(state.get("citations") or [])
    if kind in ("red_flag", "tracked"):
        evidence = list(state.get("evidence_citations") or [])
    elif kind in ("no_evidence", "clarify", "confirm", "recorded"):
        evidence, patient = [], []
    else:
        evidence = []
        if kind in ("answer", "evidence_only"):
            evidence = evidence_citations_for_response(state.get("evidence") or [])
        if kind in ("answer", "experience_only") and state.get("experience"):
            evidence += evidence_citations_for_response(
                state["experience"], tag_prefix="ex", tier="experience"
            )
        if kind != "answer":
            patient = []
    text = state.get("answer", "")
    if text and not state.get("streamed") and kind not in ("clarify", "confirm"):
        _emit({"type": "token", "content": text})
    return {
        "evidence_citations": evidence,
        "citations": patient,
        "disclaimer": interface_disclaimer(_locale(state)),
        "answer": text,
    }


def build_graph():
    g = StateGraph(AgentState, context_schema=GraphDeps)
    for name, node in (
        ("absorb", absorb), ("write", write), ("guard", guard), ("admit", admit),
        ("route", route_node), ("clarify", clarify), ("record", record), ("track", track),
        ("retrieve", retrieve), ("decide", decide), ("plan", plan), ("answer", answer),
        ("experience_only", experience_only), ("compose", compose),
    ):
        g.add_node(name, node)

    g.add_edge(START, "absorb")
    g.add_conditional_edges("absorb", _after_absorb, ["write", "guard"])
    g.add_edge("write", "compose")
    g.add_conditional_edges("guard", _after_guard, ["compose", "admit"])
    g.add_edge("admit", "route")
    g.add_conditional_edges("route", _after_route, ["clarify", "record", "track", "retrieve"])
    for node in ("clarify", "record", "track"):
        g.add_edge(node, "compose")
    g.add_edge("retrieve", "decide")
    g.add_conditional_edges("decide", _after_decide, ["plan", "answer", "experience_only"])
    for node in ("plan", "answer", "experience_only"):
        g.add_edge(node, "compose")
    g.add_edge("compose", END)
    return g.compile()


GRAPH = build_graph()


async def run_graph(state: AgentState, deps: GraphDeps) -> AgentState:
    """One turn through the graph, final state only (the demo). Raises
    GraphUnavailable, or whatever `deps.admit` raises; never returns a
    partial answer."""
    return await GRAPH.ainvoke(state, context=deps)


async def stream_graph(state: AgentState, deps: GraphDeps) -> AsyncIterator[dict]:
    """One turn, streamed: the nodes' events as they happen, then
    {"type": "final", "state": <final state>}. Exceptions propagate."""
    final: dict = {}
    async for mode, chunk in GRAPH.astream(
        state, context=deps, stream_mode=["custom", "values"]
    ):
        if mode == "custom":
            yield chunk
        else:
            final = chunk
    yield {"type": "final", "state": final}
