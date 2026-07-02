from __future__ import annotations
from typing import AsyncIterator
from uuid import UUID, uuid4

from adelia.agent.events import AgentEvent
from adelia.agent import cards
from adelia.agent.tools import TOOLS, is_write_tool
from adelia.agent.executor import execute_tool
from adelia.agent.provider import get_provider

MAX_STEPS = 5

_RULES = {
    "es": "Eres AdelIA, una asistente de salud cálida y clara para madres ocupadas. "
          "Responde corto y sin jerga. Usa las herramientas para consultar datos; nunca inventes. "
          "Para acciones que escriben o comparten, propón y espera confirmación.",
    "en": "You are AdelIA, a warm, clear health assistant for busy moms. Be brief, no jargon. "
          "Use tools to look up data; never make things up. For write/share actions, propose and wait for confirmation.",
    "fr": "Tu es AdelIA, une assistante santé chaleureuse et claire pour les mamans occupées. "
          "Sois brève, sans jargon. Utilise les outils pour consulter les données ; n'invente jamais. "
          "Pour les actions d'écriture/partage, propose et attends la confirmation.",
}

def _system_prompt(locale: str) -> str:
    return _RULES.get(locale, _RULES["es"])

async def run_agent_turn(*, user_id: UUID, profile_id: UUID | None, message: str,
                         history: list[dict] | None = None, card_action: dict | None = None,
                         locale: str = "es") -> AsyncIterator[AgentEvent]:
    provider = get_provider()
    messages: list[dict] = list(history or [])

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
    try:
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
                yield AgentEvent(type="final")
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
                                             profile_id=profile_id, locale=locale)
                if outcome.card:
                    yield AgentEvent(type="card", card=outcome.card)
                tool_results.append({"type": "tool_result", "tool_use_id": tc["id"], "content": outcome.text})
            messages.append({"role": "user", "content": tool_results})
        yield AgentEvent(type="final")
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
            briefing = await create_briefing(session, user_id=user_id, target_specialty=specialty)
            await session.commit()
            bid = briefing.id
        await briefing_orchestrator.run(briefing_id=bid, user_id=user_id,
                                        target_specialty=specialty, locale=locale)
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
