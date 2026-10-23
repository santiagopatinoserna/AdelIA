from __future__ import annotations
from typing import AsyncIterator
from uuid import UUID, uuid4

from adelia.agent.events import AgentEvent
from adelia.agent import cards
from adelia.agent.graph import GraphDeps, Retrieved, WriteOutcome, stream_graph
from adelia.agent.route import log_route
from adelia.agent.tools import TOOLS, is_write_tool
from adelia.agent.executor import execute_tool
from adelia.agent.provider import get_provider
from adelia.enrichment.profile_service import load_profile_facts
from adelia.services.answer_contract import agent_system_prompt
from adelia.services.citations import prune_and_renumber
from adelia.services.scope import Scope

MAX_STEPS = 3

# Bounds for a history that arrives from a browser. routers/agent.py trims to
# these same numbers at the door and rejects only a `system` role; this is the
# second line of defence, because run_turn is also called directly
# (tests, future surfaces) and because a `system` turn smuggled into the
# transcript would override the guardrails below. Now genuinely the pair
# routers/chat.py:30-31 uses, which the comment always claimed.
HISTORY_MAX_MESSAGES = 12
HISTORY_MAX_CHARS_PER_MESSAGE = 2000
ALLOWED_HISTORY_ROLES = ("user", "assistant")


def sanitize_history(history: list[dict] | None) -> list[dict]:
    """Keep only user/assistant turns, capped in count and length.

    The system prompt is NEVER taken from the caller: _system_prompt(locale)
    rebuilds it on every turn from services/answer_contract.
    """
    clean: list[dict] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in ALLOWED_HISTORY_ROLES:
            continue  # 'system' and anything else: dropped, not trusted
        content = item.get("content")
        if isinstance(content, str):
            content = content[:HISTORY_MAX_CHARS_PER_MESSAGE]
        elif not isinstance(content, list):
            continue  # tool_result/tool_use blocks are lists; scalars are not
        clean.append({"role": role, "content": content})
    return clean[-HISTORY_MAX_MESSAGES:]

# The agent's whole system prompt used to be the three persona sentences now
# kept in services/answer_contract._AGENT_PERSONA: no citation obligation, no
# disclaimer, no "say you don't know". /dashboard renders this agent, not the
# chat, so the parent's first question was answered with none of the clinical
# safeguards the chat has carried since v0.1.1. Both surfaces now compose the
# same contract from the same module.


def _system_prompt(locale: str) -> str:
    return agent_system_prompt(locale)


async def run_turn(*, user_id: UUID, profile_id: UUID | None, message: str,
                   history: list[dict] | None = None, card_action: dict | None = None,
                   locale: str = "es",
                   clarification: dict | None = None) -> AsyncIterator[AgentEvent]:
    """One /dashboard turn through the agent graph (AGENT_GRAPH steps 4-5).

    Replaces `run_agent_turn`, the model-and-tools loop that answered every
    turn here. The graph decides first: a red flag is the referral (no model,
    no key needed), a plan or a fact question takes the chat's contract path
    over her record and the evidence, a diary line becomes a confirmation
    card, a fever without a reading gets one question with buttons, and her
    own data, or anything the router cannot place, goes to the tool loop
    below (`_track`), now bounded to MAX_STEPS. A confirmed card goes
    straight to its write.
    """
    from adelia.services import chat_orchestrator

    messages = sanitize_history(history)
    # Who the turn is about, once. Every clinical tool needs the age and the
    # sex, and none of them should open a session to ask (audit 3.5, 3.9).
    facts = await load_profile_facts(user_id=user_id, profile_id=profile_id)
    pid = facts.profile_id or profile_id
    scope = Scope(user_id=user_id, profile_id=pid)
    text_history = [m for m in messages if isinstance(m.get("content"), str)]

    async def _route(text: str, **kwargs):
        return await log_route("agent", text, **kwargs)

    async def _retrieve(state) -> Retrieved:
        return await chat_orchestrator.retrieve_for_account(
            scope, question=state["message"], history=text_history, locale=locale
        )

    def _stream(system_prompt: str, user_message: str):
        return chat_orchestrator._guarded_stream(system_prompt, user_message,
                                                 history=text_history)

    async def _write_tool(name: str, args: dict) -> WriteOutcome:
        outcome = await _run_write_tool(name, args, user_id=user_id, profile_id=profile_id,
                                        locale=locale)
        return WriteOutcome(text=outcome.text, card=outcome.card)

    def _track_for(state):
        return _track(state, messages=messages, user_id=user_id, profile_id=profile_id,
                      locale=locale, facts=facts)

    deps = GraphDeps(
        route=_route, retrieve=_retrieve, stream=_stream,
        can_ask=True, can_write=True, record_store=_DbRecordStore(user_id, pid),
        write_tool=_write_tool, track=_track_for,
    )
    state = {
        "surface": "agent", "locale": locale, "message": message or "", "account": True,
        "facts": facts, "history": messages, "card_action": card_action,
        "clarification": clarification,
    }
    try:
        async for event in stream_graph(state, deps):
            kind = event["type"]
            if kind == "token":
                yield AgentEvent(type="token", content=event["content"])
            elif kind == "card":
                yield AgentEvent(type="card", card=event["card"])
            elif kind == "tool_call":
                yield AgentEvent(type="tool_call", tool_name=event["tool_name"])
            elif kind == "final":
                final = event["state"]
                yield AgentEvent(
                    type="final",
                    citations=[_as_dict(c) for c in final.get("citations") or []],
                    evidence_citations=list(final.get("evidence_citations") or []),
                )
    except Exception as exc:  # noqa: BLE001
        yield AgentEvent(type="error", content=str(exc))


def _as_dict(citation) -> dict:
    return citation.model_dump(mode="json") if hasattr(citation, "model_dump") else citation


async def _track(state, *, messages: list[dict], user_id: UUID, profile_id: UUID | None,
                 locale: str, facts) -> AsyncIterator[dict]:
    """The graph's `track` node for the agent: the model with the tools, MAX_STEPS at most.

    Her own data (percentiles, vaccines due, her reports and lab results),
    briefings and profile fixes, and whatever the router could not place.
    The provider is resolved LATE, here and not when the turn starts: a
    missing or broken LLM key used to kill the whole stream, red-flag
    referral included (2026-08-31), and the guard has already run by now.
    Write tools are never run here: they become a confirmation card and the
    turn pauses until she confirms (principle 3).
    """
    provider = get_provider()
    convo = list(messages) + [{"role": "user", "content": state["message"]}]
    # Citations accumulated across every tool call of the turn, so the final
    # SSE frame carries one contiguous numbering (services/citations).
    turn_citations: list[dict] = []
    turn_evidence: list[dict] = []
    answer: list[str] = []

    def _result() -> dict:
        return {"type": "result", "answer": "".join(answer), "citations": turn_citations,
                "evidence_citations": turn_evidence}

    for _ in range(MAX_STEPS):
        assistant_text = ""
        tool_calls: list[dict] = []
        async for ev in provider.stream_step(system=_system_prompt(locale), messages=convo,
                                             tools=TOOLS):
            if ev["type"] == "token":
                assistant_text += ev["text"]
                yield {"type": "token", "content": ev["text"]}
            elif ev["type"] == "tool_call":
                tool_calls.append(ev)
        answer.append(assistant_text)
        if not tool_calls:
            yield _result()
            return
        # record the assistant turn (text + tool_use) for the next model call
        convo.append({"role": "assistant", "content": _assistant_blocks(assistant_text, tool_calls)})
        tool_results = []
        for tc in tool_calls:
            yield {"type": "tool_call", "tool_name": tc["name"]}
            if is_write_tool(tc["name"]):
                confirm = cards.card_confirm(uuid4().hex[:12], _confirm_title(tc["name"], locale),
                                             tc["name"], tc["args"])
                yield {"type": "card", "card": confirm}
                yield _result()  # pause: wait for the user's confirm action
                return
            outcome = await execute_tool(tc["name"], tc["args"], user_id=user_id,
                                         profile_id=profile_id, locale=locale, facts=facts)
            if outcome.card:
                yield {"type": "card", "card": outcome.card}
            # Drop the citations the tool's answer never referenced and
            # continue the turn's numbering, so the markers the model
            # copies into its reply point at the cards the parent sees.
            text, kept_citations, kept_evidence = prune_and_renumber(
                outcome.text, outcome.citations, outcome.evidence_citations,
                citation_offset=len(turn_citations),
                evidence_offset=len(turn_evidence),
            )
            turn_citations.extend(kept_citations)
            turn_evidence.extend(kept_evidence)
            tool_results.append({"type": "tool_result", "tool_use_id": tc["id"], "content": text})
        convo.append({"role": "user", "content": tool_results})
    yield _result()


class _DbRecordStore:
    """Observations for one child of one account (agent/record, migration 0023)."""

    def __init__(self, user_id: UUID, profile_id: UUID | None):
        self.user_id, self.profile_id = user_id, profile_id

    async def save(self, draft) -> None:
        from adelia.db import AsyncSessionLocal
        from adelia.services.observations import add_observation

        async with AsyncSessionLocal() as session:
            await add_observation(
                session, user_id=self.user_id, profile_id=self.profile_id, kind=draft.kind,
                value=draft.value, unit=draft.unit, text=draft.text,
                observed_at=draft.observed_at, source="agent",
            )
            await session.commit()

    async def previous(self, kind: str, before):
        from adelia.agent.record import as_draft
        from adelia.db import AsyncSessionLocal
        from adelia.services.observations import previous_comparable

        async with AsyncSessionLocal() as session:
            row = await previous_comparable(
                session, scope=Scope(user_id=self.user_id, profile_id=self.profile_id),
                kind=kind, before=before,
            )
            return as_draft(row) if row is not None else None


def _assistant_blocks(text: str, tool_calls: list[dict]) -> list[dict]:
    blocks: list[dict] = []
    if text:
        blocks.append({"type": "text", "text": text})
    for tc in tool_calls:
        blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["args"]})
    return blocks

def _confirm_title(name: str, locale: str) -> str:
    titles = {"generar_briefing": {"es": "¿Genero el briefing para el especialista?",
                                   "en": "Generate the briefing for the specialist?",
                                   "fr": "Générer le briefing pour le spécialiste ?"},
              "completar_perfil": {"es": "¿Guardo este dato en el perfil?",
                                   "en": "Save this to the profile?",
                                   "fr": "Enregistrer dans le profil ?"}}
    return titles.get(name, {}).get(locale, titles.get(name, {}).get("es", "¿Confirmas?"))

def _to_specialty(raw: str):
    from adelia.schemas import Specialty
    try:
        return Specialty(raw.strip().lower())
    except ValueError:
        return Specialty.DEFAULT

async def _run_write_tool(name: str, args: dict, *, user_id: UUID, profile_id: UUID | None,
                          locale: str):
    from adelia.agent.executor import ToolOutcome
    from adelia.enrichment import profile_service
    from adelia.db import AsyncSessionLocal
    if name == "generar_briefing":
        from adelia.services import briefing_orchestrator
        from adelia.services.briefing_repo import create_briefing
        specialty = _to_specialty(args["specialty"])
        async with AsyncSessionLocal() as session:
            # Same child the turn is about: the agent's briefing used to be
            # built from the whole account, so a mother of two got a briefing
            # for her newborn carrying her four-year-old's history (audit 4.1).
            pid = await profile_service.resolve_profile_id(
                session, user_id=user_id, profile_id=profile_id
            )
            briefing = await create_briefing(session, user_id=user_id,
                                             target_specialty=specialty, profile_id=pid)
            await session.commit()
            bid = briefing.id
        await briefing_orchestrator.run(briefing_id=bid, user_id=user_id,
                                        target_specialty=specialty, locale=locale,
                                        profile_id=pid)
        from adelia.agent import cards
        return ToolOutcome(text="Briefing generado.",
                           card=cards.card_briefing(bid.hex[:12], str(bid), specialty.value, "ready", ""))
    if name == "completar_perfil":
        from datetime import date as _date
        field = args.get("field")
        value = args.get("value")
        async with AsyncSessionLocal() as session:
            pid = await profile_service.resolve_profile_id(session, user_id=user_id, profile_id=profile_id)
            if pid is not None:
                kwargs: dict = {}
                if field == "date_of_birth":
                    kwargs["date_of_birth"] = _date.fromisoformat(value)
                elif field == "sex":
                    kwargs["sex"] = value
                elif field == "display_name":
                    kwargs["display_name"] = value
                if kwargs:
                    await profile_service.update_profile(session, profile_id=pid, user_id=user_id, **kwargs)
            await session.commit()
        return ToolOutcome(text="Dato guardado en el perfil.")
    return ToolOutcome(text="(nada que hacer)")
