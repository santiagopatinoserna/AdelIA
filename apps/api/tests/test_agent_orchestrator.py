import pytest

from unittest.mock import patch
from uuid import uuid4
from adelia.agent.orchestrator import run_agent_turn

async def _collect(gen):
    return [e async for e in gen]

def _fake_provider(steps, seen_systems=None):
    class P:
        def __init__(self): self._i = 0
        async def stream_step(self, *, system, messages, tools):
            if seen_systems is not None:
                seen_systems.append(system)
            for ev in steps[self._i]:
                yield ev
            self._i += 1
    return P()

async def test_plain_answer_streams_tokens():
    steps = [[{"type": "token", "text": "Hola"}, {"type": "stop", "stop_reason": "end_turn"}]]
    with patch("adelia.agent.orchestrator.get_provider", return_value=_fake_provider(steps)):
        events = await _collect(run_agent_turn(user_id=uuid4(), profile_id=None, message="hi"))
    assert any(e.type == "token" and e.content == "Hola" for e in events)
    assert events[-1].type == "final"

async def test_read_tool_emits_card_then_final():
    steps = [
        [{"type": "tool_call", "id": "t1", "name": "evaluar_labs",
          "args": {"name": "Hb", "value": 9.0}}, {"type": "stop", "stop_reason": "tool_use"}],
        [{"type": "token", "text": "Tu Hb está baja."}, {"type": "stop", "stop_reason": "end_turn"}],
    ]
    from adelia.agent.executor import ToolOutcome
    from adelia.agent import cards
    outcome = ToolOutcome(text="Hb baja", card=cards.card_lab("l1", "Hb", 9.0, "g/dL", "low", "12-16", "Bajo"))
    with patch("adelia.agent.orchestrator.get_provider", return_value=_fake_provider(steps)), \
         patch("adelia.agent.orchestrator.execute_tool", return_value=outcome):
        events = await _collect(run_agent_turn(user_id=uuid4(), profile_id=None, message="¿mi Hb?"))
    assert any(e.type == "card" and e.card["type"] == "lab" for e in events)
    assert events[-1].type == "final"

async def test_write_tool_emits_confirm_and_stops():
    steps = [[{"type": "tool_call", "id": "t1", "name": "generar_briefing",
               "args": {"specialty": "peds"}}, {"type": "stop", "stop_reason": "tool_use"}]]
    with patch("adelia.agent.orchestrator.get_provider", return_value=_fake_provider(steps)):
        events = await _collect(run_agent_turn(user_id=uuid4(), profile_id=None, message="haz el briefing"))
    confirms = [e for e in events if e.type == "card" and e.card["type"] == "confirm"]
    assert confirms and confirms[0].card["payload"]["tool_name"] == "generar_briefing"


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
async def test_agent_system_prompt_carries_the_answer_contract(locale):
    """Audit 4.1: /dashboard renders this agent, not the chat, and its whole
    system prompt used to be three persona sentences. It must now be bound by
    the same contract the chat is: cite or do not interpret, closing
    disclaimer, and the exact wording for "I do not know"."""
    from adelia.services.answer_contract import answer_contract, no_evidence_reply

    seen: list[str] = []
    steps = [[{"type": "token", "text": "Hola"}, {"type": "stop", "stop_reason": "end_turn"}]]
    with patch("adelia.agent.orchestrator.get_provider",
               return_value=_fake_provider(steps, seen)):
        await _collect(run_agent_turn(user_id=uuid4(), profile_id=None,
                                      message="¿es normal?", locale=locale))

    assert len(seen) == 1
    system = seen[0]
    assert answer_contract(locale) in system
    assert no_evidence_reply(locale) in system
    assert "[ev_1]" in system
    assert "buscar_en_expediente" in system


def test_agent_and_chat_share_one_contract():
    """Same clauses, one module. If these ever diverge again, the default
    screen is answering under different rules than the chat."""
    from adelia.services.answer_contract import (
        agent_system_prompt,
        answer_contract,
        chat_system_prompt,
    )

    for locale in ("es", "en", "fr"):
        clauses = answer_contract(locale)
        assert clauses in chat_system_prompt(locale)
        assert clauses in agent_system_prompt(locale)
