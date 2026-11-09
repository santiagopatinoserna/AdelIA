"""The agent graph (docs/specs/AGENT_GRAPH.md): one graph, three surfaces.

    absorb -> write                                  (a confirmed card)
           -> thread -> guard -> admit -> route -> clarify   (one round, buttons)
                                                 | record    (a diary line, account only)
                                                 | track     (her own data: tools, 3 steps)
                                                 | retrieve -> decide -> plan | answer
                                                                       | experience_only
                                                                       | clarify
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
  * At most one clarify round per topic, and only with buttons (one question,
    or two where the surface shows them); the next turn answers with what
    there is (principle 2). `thread` (agent/conversation.py) reads the
    transcript the surface sent: a follow-up is searched with her words in
    the topic, a correction drops the answers she rejected, a new topic
    carries nothing of the old one (2026-11-09).
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

from adelia.agent import conversation  # noqa: E402
from adelia.agent import implicit_subject  # noqa: E402
from adelia.agent import lay_terms  # noqa: E402
from adelia.agent import record as rec  # noqa: E402
from adelia.agent import warning_signs  # noqa: E402
from adelia.agent.route import RouteDecision, route_by_rules  # noqa: E402
from adelia.clinical import red_flags  # noqa: E402
from adelia.clinical.golden import is_refusal  # noqa: E402
from adelia.clinical.age_scope import child_outside_scope  # noqa: E402
from adelia.config import settings  # noqa: E402
from adelia.db import AsyncSessionLocal  # noqa: E402
from adelia.enrichment.evidence_retrieval import (  # noqa: E402
    add_warning_fragments,
    evidence_citations_for_response,
    format_evidence_for_prompt,
    format_experience_for_prompt,
    merge_by_best_distance,
)
from adelia.enrichment.profile_service import ProfileFacts  # noqa: E402
from adelia.services.answer_contract import (  # noqa: E402
    CLARIFY_AGE_FLOOR,
    CLARIFY_QUESTIONS,
    PLAN_HEADINGS,
    chat_system_prompt,
    clarification_sentence,
    clarify_free_text,
    clarify_question,
    experience_only_contract,
    experience_only_opening,
    interface_disclaimer,
    missing_fact_note,
    no_evidence_reply,
    out_of_scope_age_reply,
    red_flag_reply,
)
from adelia.services.citations import markers_in  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_LOCALE = "es"
#: The time zone a diary line's "a las 5" is read in. Both countries AdelIA
#: serves today (ES, FR) are on it.
LOCAL_TZ = ZoneInfo("Europe/Madrid")

#: The questions a surface can show. The demo page and its proxy know the two
#: of build step 3 and one at a time; the agent canvas shows them all, two per
#: card (agent/orchestrator lends ACCOUNT_CLARIFY_FIELDS and clarify_round=2).
DEMO_CLARIFY_FIELDS: frozenset[str] = frozenset({"age", "temperature"})
ACCOUNT_CLARIFY_FIELDS: frozenset[str] = frozenset(CLARIFY_QUESTIONS)
#: What the routing model may call a missing fact, in our questions' names.
_MISSING_ALIASES = {"duration": "since_when"}


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
    #: Her answers to a two-question card, in order: [{"field", "value"}, ...].
    clarifications: list[dict] | None
    clarified: bool
    #: Where this turn sits in the conversation (agent/conversation.Conversation).
    conversation: Any
    #: What retrieval searches: her words in this topic (conversation.search_query).
    search_query: str
    # Decisions
    flag: Any
    #: The guard refused a question about a child of 3 or more (age_scope).
    out_of_scope: bool
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
    #: The retrieval text rendered for the Spanish corpus, given the locale
    #: (agent/corpus_query.py). Never raises. None embeds the retrieval text.
    corpus_text: Callable[[str, str], Awaitable[str]] | None = None
    # Account surfaces
    retrieve: Callable[["AgentState"], Awaitable[Retrieved]] | None = None
    stream: Stream | None = None
    #: The surface can show a question with buttons (the chat page cannot).
    can_ask: bool = True
    #: Which questions it can show, and how many in one card.
    clarify_fields: frozenset[str] = DEMO_CLARIFY_FIELDS
    clarify_round: int = 1
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
    answers = list(state.get("clarifications") or [])
    if not answers and state.get("clarification"):
        answers = [state["clarification"]]
    if not answers:
        return {"clarified": False}
    update: dict = {"clarified": True}
    lines: list[str] = []
    facts = state.get("facts")
    for answer in answers[:2]:
        if not isinstance(answer, dict):
            continue
        field_name, value = str(answer.get("field", "")), str(answer.get("value", ""))
        sentence = clarification_sentence(field_name, value, _locale(state))
        if sentence is None:
            logger.info("graph: unreadable clarification ignored (field=%s)", field_name)
            continue
        lines.append(sentence)
        if field_name == "age" and value in CLARIFY_AGE_FLOOR and (
            facts is None or facts.age_months is None
        ):
            floor = CLARIFY_AGE_FLOOR[value]
            facts = (
                dataclasses.replace(facts, age_months=floor) if facts is not None
                else ProfileFacts(None, None, None, None, floor)
            )
            update["facts"] = facts
    if lines:
        update["message"] = "\n".join([state["message"], *lines])
    return update


def _after_absorb(state: AgentState) -> str:
    action = state.get("card_action") or {}
    return "write" if action.get("intent") == "confirm" else "thread"


async def thread(state: AgentState) -> dict:
    """Where this turn sits in the conversation, by rules (agent/conversation).

    Before the guard and free: no model, no database. Her answer to a clarify
    question in words is read under the question it answers, so the guard
    sees both, as it does with a button. A surface without a transcript (the
    demo) gets a first turn, searched and answered exactly as before.
    """
    c = conversation.read(
        state["message"], state.get("history"), clarified=bool(state.get("clarified"))
    )
    if c.kind != "new" or c.via != "first":
        logger.info(
            "graph: turn=%s via=%s asked=%s refused=%s behaviour=%s (surface=%s)",
            c.kind, c.via, c.asked, c.refused, c.behaviour, state.get("surface"),
        )
    return {"conversation": c, "message": c.message, "search_query": c.search_query}


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
    """Red flags, in code, before anything else (audit 3.3); then the age scope.

    A child of 3 or more with no baby in the message is refused here, after
    the red flags so a choking 5-year-old still gets the referral, and before
    any embedding so the infant corpus is never cited for him (handoff 4.1,
    clinical/age_scope).
    """
    flag = red_flags.detect(state["message"], locale=_locale(state), age_months=_age(state))
    if flag is not None:
        logger.info("graph: red flag %s fired (surface=%s)", flag.code, state.get("surface"))
        return _referral(state, flag)
    if child_outside_scope(state["message"]):
        logger.info("graph: child of 3 or more, refused (surface=%s)", state.get("surface"))
        return {
            "flag": None,
            "out_of_scope": True,
            "kind": "no_evidence",
            "answer": out_of_scope_age_reply(_locale(state)),
        }
    return {"flag": None}


def _after_guard(state: AgentState) -> str:
    stop = state.get("flag") is not None or state.get("out_of_scope")
    return "compose" if stop else "admit"


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
    c = state.get("conversation")
    kwargs: dict = {
        "locale": _locale(state),
        "has_account": bool(state.get("account")),
        "facts": state.get("facts"),
    }
    # One round per topic (principle 2): a button pressed this turn, or a
    # question already asked in this topic, and the graph answers with what
    # there is.
    spent = bool(state.get("clarified")) or (c is not None and c.asked)
    if c is not None and deps.can_ask and not spent:
        # A behaviour worry is asked before any answer (2026-11-09). Unless the
        # free rules place it elsewhere (her own data, a diary line), the
        # routing model is not paid, nor waited for, to then ask anyway.
        first = _round(conversation.ask_first(c, state.get("facts")), deps, _locale(state))
        ruled = route_by_rules(c.route_text, **kwargs) if first else None
        if first and (ruled is None or ruled.intent in ("plan", "question", "clarify")):
            logger.info("graph: asked before routing (%s, surface=%s)",
                        ",".join(first), state.get("surface"))
            return {"intent": "clarify", "intent_confidence": 1.0, "intent_via": "rule",
                    "missing": first}
    route_text = c.route_text if c is not None else state["message"]
    if c is not None and c.kind == "follow_up" and c.via != "clarify":
        # A diary line or her own data says so by itself ("Ha hecho 3 cacas
        # hoy" after a question about green stools): routed with the topic it
        # would read as a question, and the card would never come.
        alone = route_by_rules(state["message"], **kwargs)
        if alone is not None and alone.intent in ("record", "track"):
            route_text = state["message"]
    if c is not None and c.route_history:
        # The same call as always, now reading the tail of the thread; the
        # model is only consulted when the routing rules abstain.
        kwargs["history"] = c.route_history
    decision = await deps.route(route_text, **kwargs)
    update: dict = {}
    if c is not None and not c.decided and decision.via == "model":
        c = conversation.with_kind(c, decision.turn, search_query=decision.search_query)
        update = {"conversation": c, "search_query": c.search_query}
    intent = decision.intent
    missing = [_MISSING_ALIASES.get(f, f) for f in decision.missing]
    if intent == "clarify":
        askable = _askable(missing, deps, _locale(state))
        if spent or not askable or not deps.can_ask:
            intent = "plan"
        else:
            missing = askable[:deps.clarify_round]
    if intent == "record" and not (
        state.get("account") and deps.can_write and deps.record_store is not None
    ):
        intent = "plan"
    if intent in ("other",) or decision.via == "fallback":
        # A behaviour worry or a correction is answered on the contract path,
        # never in the tool loop's free format.
        contract = c is not None and (c.behaviour or c.kind == "correction")
        intent = "track" if deps.track is not None and not contract else "plan"
    if intent == "track" and deps.track is None:
        intent = "question"
    return {
        **update,
        "intent": intent,
        "intent_confidence": decision.confidence,
        "intent_via": decision.via,
        "missing": missing,
    }


def _askable(fields: list[str], deps: GraphDeps, locale: str) -> list[str]:
    return [
        f for f in fields
        if f in deps.clarify_fields and clarify_question(f, locale) is not None
    ]


def _round(fields: list[str], deps: GraphDeps, locale: str) -> list[str]:
    """A whole round this surface can show, or nothing: half a round asks the
    wrong question (the demo knows the age, not the signals at home)."""
    askable = _askable(fields, deps, locale)
    if not fields or askable != fields or len(fields) > deps.clarify_round:
        return []
    return fields


def _after_route(state: AgentState) -> str:
    intent = state.get("intent")
    if intent in ("clarify", "record", "track"):
        return intent
    return "retrieve"


async def clarify(state: AgentState) -> dict:
    """One concrete question of one line, with two or three buttons.

    Two where the surface shows them (the agent): the card then lists both
    under `questions` and says she may write instead. The first stays at the
    top level, the shape the demo page reads.
    """
    fields = list(state["missing"])
    questions = [{"field": f, **clarify_question(f, _locale(state))} for f in fields]
    payload = dict(questions[0])
    if len(questions) > 1:
        payload["questions"] = questions
        payload["free"] = clarify_free_text(_locale(state))
    # A streaming surface gets it as a card; her question (in a follow-up,
    # her words in the topic) rides along so the page can send it back with
    # the buttons' values.
    c = state.get("conversation")
    message = c.route_text if c is not None else state["message"]
    _emit({"type": "card", "card": {
        "type": "clarify", "id": "clarify-" + "-".join(fields),
        "payload": {**payload, "message": message}, "actions": [],
    }})
    asked = "\n".join(q["question"] for q in questions)
    return {"kind": "clarify", "answer": asked, "clarify": payload}


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
    spoken = deps.retrieval_text(state.get("search_query") or state["message"])
    text = spoken
    if deps.corpus_text is not None:
        text = await deps.corpus_text(spoken, _locale(state))
    # Her words, rendered in the corpus's terms, as a second search
    # (agent/lay_terms.py). Off by default: then the lexicon is not read and
    # the calls below are the ones this node always made.
    widened = lay_terms.expanded_query(text) if settings.lay_query_expansion else None
    texts = [text] if widened is None else [text, widened]
    # The baby she did not name, put back, as its own search
    # (agent/implicit_subject.py). Off by default, and then not read either.
    subject_index = None
    if settings.implicit_subject_expansion:
        facts = state.get("facts")
        subject = implicit_subject.subject_query(
            text, locale=_locale(state), spoken=spoken, age_months=_age(state),
            name=facts.display_name if facts is not None else None,
        )
        if subject is not None:
            texts.append(subject)
            subject_index = len(texts) - 1
    # A plan's "Cuándo ir al médico", from the library (agent/warning_signs.py):
    # the same topic plus the warning-sign words, embedded in the same call and
    # searched only if the main search found evidence. Off by default, and a
    # short answer never runs it.
    warning_index = None
    if settings.warning_signs_retrieval and state.get("intent") == "plan":
        texts.append(warning_signs.warning_query(widened or text, _locale(state)))
        warning_index = len(texts) - 1
    try:
        embeds = await deps.embed(texts)
    except Exception as exc:  # noqa: BLE001 - no key, no network, provider down
        logger.warning("graph: embedding failed (%s)", type(exc).__name__)
        raise GraphUnavailable("embedding failed") from exc
    if not embeds:
        raise GraphUnavailable("embedding returned nothing")
    cuts = {
        "specialties": ["pediatrics"],
        "top_k": 4,
        "max_distance": settings.evidence_max_distance,
        "relative_margin": settings.evidence_relative_margin,
    }
    async with AsyncSessionLocal() as session:
        evidence = await deps.retrieve_evidence(session, query_embedding=embeds[0], **cuts)
        also: list = []
        if widened is not None and len(embeds) > 1:
            also.append(await deps.retrieve_evidence(session, query_embedding=embeds[1], **cuts))
        if subject_index is not None and len(embeds) > subject_index:
            # Our rewrite of her words admits only under its own, stricter cut
            # (config.implicit_subject_max_distance has the measurement).
            subject_cut = min(cuts["max_distance"], settings.implicit_subject_max_distance)
            also.append(await deps.retrieve_evidence(
                session, query_embedding=embeds[subject_index],
                **{**cuts, "max_distance": subject_cut},
            ))
        if also:
            evidence = merge_by_best_distance(
                [evidence, *also], top_k=cuts["top_k"], relative_margin=cuts["relative_margin"]
            )
        if evidence and warning_index is not None and len(embeds) > warning_index:
            # The sources the plan cites, so their other paragraphs under the
            # cut-offs come back too (the croup guide's "cuándo acudir a urgencias").
            alarm = await deps.retrieve_evidence(
                session, query_embedding=embeds[warning_index], **cuts,
                cited_sources=list(dict.fromkeys(m.source_id for m in evidence)),
                cited_chunks=[m.chunk_id for m in evidence],
            )
            evidence = add_warning_fragments(evidence, alarm)
    # Other mothers are searched with her sentence alone: the experience tier
    # is not what the lexicon was measured for.
    return {"evidence": list(evidence), "query_embedding": embeds[0]}


async def decide(state: AgentState, runtime: Runtime[GraphDeps]) -> dict:
    """`kind` from the clinical evidence and her own record; experience never decides.

    Nothing survived the cut-offs on either side: the code refuses, the model
    is never asked (audit 3.1). Before refusing a worry she observed, one round
    of questions where the surface can ask and the topic has not had one: her
    answers go into the next search (2026-11-09, "sin evidencia no es un
    callejón"). Never for a fact question or a drug.
    """
    grounded = bool(state.get("evidence")) or bool(state.get("patient_context"))
    if grounded:
        return {"kind": "answer"}
    deps, c = runtime.context, state.get("conversation")
    if c is not None and deps.can_ask and not state.get("clarified"):
        fields = _round(
            conversation.ask_when_nothing_found(c, state.get("facts"), intent=state.get("intent")),
            deps, _locale(state),
        )
        if fields:
            return {"kind": "no_evidence", "intent": "clarify", "missing": fields}
    return {"kind": "no_evidence"}


def _after_decide(state: AgentState) -> str:
    if state["kind"] == "no_evidence":
        return "clarify" if state.get("intent") == "clarify" else "experience_only"
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
    c = state.get("conversation")
    question = c.prompt_question if c is not None else state["message"]
    blocks = [f"Pregunta del usuario: {question}\n"]
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
    if c is not None and (note := conversation.correction_note(c)):
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
        # A surface that sent a transcript gets back this topic's part of it
        # (agent/conversation): nothing of an earlier topic, nothing of an
        # answer she corrected.
        c = state.get("conversation")
        if state.get("history") and c is not None:
            tokens = deps.stream(system, user, history=c.model_history)
        else:
            tokens = deps.stream(system, user)
        pieces: list[str] = []
        async for piece in tokens:
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


_VISIT_NOTE = "note"


def _dead_end(state: AgentState, deps: GraphDeps, refusal: dict) -> dict:
    """The refusal, said once per topic, and what can still help.

    Santiago's conversation of 2026-11-09 met the same "no tengo evidencia"
    on every turn. The second time in a topic it is one short line that still
    sends her to the pediatrician. Her own words follow, to take to the visit,
    and a card offers to note them in her record: nothing of ours, no source,
    no advice. Only where she can write (the agent); the chat, text only,
    keeps the whole coded refusal every time.
    """
    c = state.get("conversation")
    can_note = state.get("account") and deps.can_write and deps.record_store is not None
    if c is None or not can_note:
        return refusal
    lang = _lang(state)
    text = conversation.no_evidence_again(lang) if c.refused else refusal["answer"]
    text = f"{text}\n\n{conversation.consult_note(c, lang)}"
    now = deps.now()
    draft = rec.RecordDraft(_VISIT_NOTE, None, None, now, conversation.visit_note(c))
    card = rec.confirm_card(draft, locale=_locale(state), now=now)
    card["payload"]["title"] = conversation.visit_card_title(lang)
    card["payload"]["body"] = draft.text
    _emit({"type": "card", "card": card})
    return {**refusal, "answer": text}


async def experience_only(state: AgentState, runtime: Runtime[GraphDeps]) -> dict:
    """No evidence: the coded refusal, or what other mothers say, fenced.

    A fixed opening sentence from the contract, then one "Lo que cuentan
    otras madres" section the model wrote from the [ex_N] fragments and
    nothing else. No patient data goes into the prompt: there is nothing
    clinical to relate it to, and a [N] marker in the output discards it.
    Surfaces without the experience tier (the chat, the agent) refuse.
    """
    lang = _lang(state)
    deps = runtime.context
    refusal = {"kind": "no_evidence", "answer": no_evidence_reply(lang), "experience": []}
    experience = await _experience_for(state, deps)
    if not experience or deps.generate is None:
        return _dead_end(state, deps, refusal)
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


def _cited_only(cards: list[dict], answer: str) -> list[dict]:
    """The clinical cards the model's answer actually cites, tags unchanged.

    Retrieval hands the model up to four fragments and it may use two. The
    other two used to go out as cards under an answer that never cites them,
    the shape audit 3.7 calls "looks sourced, is not" and the golden gate
    counts as orphan citations (threshold zero). Measured with Claude against
    the prod corpus on 2026-11-03 there were 23. The tags are kept rather than
    renumbered
    (`citations.prune_and_renumber`) because a streamed answer has already
    sent its [ev_N] markers to the parent.
    """
    _, used = markers_in(answer)
    tags = {f"ev_{i}" for i in used}
    return [c for c in cards if c.get("tag") in tags]


_EX_MARKER = re.compile(r"\[(ex_\d+)\]")


def _refuses(text: str) -> bool:
    """Whether the model's text carries the coded refusal, in any language.

    The same check the golden gate scores with (`golden.is_refusal`), over
    every locale: a parent may write in English under the Spanish locale and
    the model answers in her language.
    """
    return any(is_refusal(text, locale) for locale in PLAN_HEADINGS)


def _refusal_cards(evidence: list[dict], text: str) -> list[dict]:
    """The cards a text with the coded refusal in it may carry.

    Measured in prod on 2026-11-05 (demo, Claude): B8 refused the jaundice
    question and went out with a colic post from the mothers tier; B17
    refused tongue-tie with teethers, crying and babywearing underneath. A
    parent reads "no tengo evidencia" and then cards: it reads as sourced
    and unrelated at once. So such a text keeps only what it names: a whole
    refusal names nothing and carries no card. A mixed answer (B9, B11: one
    half cited, the coded refusal for the other) keeps its cited evidence
    (already pruned by `_cited_only`) and only the mothers it cites with
    [ex_N]: B9 had three sleep posts under a vegetables-and-melatonin answer.
    """
    named = set(_EX_MARKER.findall(text))
    return [c for c in evidence if c.get("tier") != "experience" or c.get("tag") in named]


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
        if kind == "answer":
            evidence = _cited_only(evidence, state.get("answer", ""))
        if kind in ("answer", "experience_only") and state.get("experience"):
            evidence += evidence_citations_for_response(
                state["experience"], tag_prefix="ex", tier="experience"
            )
        if kind != "answer":
            patient = []
        elif _refuses(state.get("answer", "")):
            evidence = _refusal_cards(evidence, state.get("answer", ""))
            if not markers_in(state.get("answer", ""))[0]:
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
        ("absorb", absorb), ("write", write), ("thread", thread), ("guard", guard),
        ("admit", admit),
        ("route", route_node), ("clarify", clarify), ("record", record), ("track", track),
        ("retrieve", retrieve), ("decide", decide), ("plan", plan), ("answer", answer),
        ("experience_only", experience_only), ("compose", compose),
    ):
        g.add_node(name, node)

    g.add_edge(START, "absorb")
    g.add_conditional_edges("absorb", _after_absorb, ["write", "thread"])
    g.add_edge("thread", "guard")
    g.add_edge("write", "compose")
    g.add_conditional_edges("guard", _after_guard, ["compose", "admit"])
    g.add_edge("admit", "route")
    g.add_conditional_edges("route", _after_route, ["clarify", "record", "track", "retrieve"])
    for node in ("clarify", "record", "track"):
        g.add_edge(node, "compose")
    g.add_edge("retrieve", "decide")
    g.add_conditional_edges(
        "decide", _after_decide, ["plan", "answer", "experience_only", "clarify"]
    )
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
