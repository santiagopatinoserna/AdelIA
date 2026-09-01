from __future__ import annotations
from typing import AsyncIterator
from uuid import UUID, uuid4

from adelia.agent.events import AgentEvent
from adelia.agent import cards
from adelia.agent.tools import TOOLS, is_write_tool
from adelia.agent.executor import execute_tool
from adelia.agent.provider import get_provider
from adelia.clinical import red_flags
from adelia.enrichment.profile_service import load_profile_facts
from adelia.services.answer_contract import agent_system_prompt, red_flag_reply
from adelia.services.citations import prune_and_renumber

MAX_STEPS = 5

# Bounds for a history that arrives from a browser. routers/agent.py trims to
# these same numbers at the door and rejects only a `system` role; this is the
# second line of defence, because run_agent_turn is also called directly
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


async def run_agent_turn(*, user_id: UUID, profile_id: UUID | None, message: str,
                         history: list[dict] | None = None, card_action: dict | None = None,
                         locale: str = "es") -> AsyncIterator[AgentEvent]:
    # The provider is resolved LATE, right before the model loop. It used to
    # be the first statement of the turn, which meant a missing or broken LLM
    # key killed the whole stream, red-flag referral included: the one answer
    # that needs no model was the one a missing model prevented. Verified on
    # 2026-08-31 against a stack with no key, where "des taches qui ne
    # s'effacent pas" returned an empty stream instead of the referral.
    messages: list[dict] = sanitize_history(history)
    # Who the turn is about, once. Every clinical tool needs the age and the
    # sex, and none of them should open a session to ask (audit 3.5, 3.9).
    facts = await load_profile_facts(user_id=user_id, profile_id=profile_id)

    # Red flags before the model, exactly as in the chat (audit 3.3). This is
    # the screen a parent lands on, so it is the screen where "my 2-month-old
    # is at 38.2, do I give her paracetamol?" actually gets typed.
    if message and not card_action:
        flag = red_flags.detect(message, locale=locale, age_months=facts.age_months)
        if flag is not None:
            yield AgentEvent(type="token", content=red_flag_reply(flag.code, locale))
            yield AgentEvent(
                type="final",
                evidence_citations=[red_flags.citation_for(flag)],
            )
            return

    # A confirm action arriving from the UI = execute the previously-proposed write tool now.
    if card_action and card_action.get("intent") == "confirm":
        name = card_action["tool_name"]
        args = card_action.get("tool_args", {})
        try:
            outcome = await _run_write_tool(name, args, user_id=user_id, profile_id=profile_id, locale=locale)
            if outcome.card:
                yield AgentEvent(type="card", card=outcome.card)
            yield AgentEvent(type="token", content=outcome.text)
            yield AgentEvent(type="final")
        except Exception as exc:  # noqa: BLE001
            yield AgentEvent(type="error", content=str(exc))
        return

    messages.append({"role": "user", "content": message})
    # Citations accumulated across every tool call of the turn, so the final
    # SSE frame carries one contiguous numbering (services/citations).
    turn_citations: list[dict] = []
    turn_evidence: list[dict] = []
    try:
        provider = get_provider()
        for _ in range(MAX_STEPS):
            assistant_text = ""
            tool_calls: list[dict] = []
            async for ev in provider.stream_step(system=_system_prompt(locale), messages=messages, tools=TOOLS):
                if ev["type"] == "token":
                    assistant_text += ev["text"]
                    yield AgentEvent(type="token", content=ev["text"])
                elif ev["type"] == "tool_call":
                    tool_calls.append(ev)
                elif ev["type"] == "stop":
                    pass
            if not tool_calls:
                yield AgentEvent(type="final", citations=turn_citations,
                                 evidence_citations=turn_evidence)
                return
            # record the assistant turn (text + tool_use) for the next model call
            messages.append({"role": "assistant", "content": _assistant_blocks(assistant_text, tool_calls)})
            tool_results = []
            for tc in tool_calls:
                yield AgentEvent(type="tool_call", tool_name=tc["name"])
                if is_write_tool(tc["name"]):
                    confirm = cards.card_confirm(uuid4().hex[:12], _confirm_title(tc["name"], locale),
                                                 tc["name"], tc["args"])
                    yield AgentEvent(type="card", card=confirm)
                    yield AgentEvent(type="final")  # pause: wait for the user's confirm action
                    return
                outcome = await execute_tool(tc["name"], tc["args"], user_id=user_id,
                                             profile_id=profile_id, locale=locale,
                                             facts=facts)
                if outcome.card:
                    yield AgentEvent(type="card", card=outcome.card)
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
            messages.append({"role": "user", "content": tool_results})
        yield AgentEvent(type="final", citations=turn_citations,
                         evidence_citations=turn_evidence)
    except Exception as exc:  # noqa: BLE001
        yield AgentEvent(type="error", content=str(exc))

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
