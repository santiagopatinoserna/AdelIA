"""The chat runs the agent graph (AGENT_GRAPH step 5).

Same guard, same route, same contracts as the demo and the agent. The chat
page shows text and source cards and nothing else, so its graph has no
buttons and no writes: a fact question streams the short answer, a fever
without a reading is answered with what there is, a diary line is answered
rather than recorded. Everything the chat promised before is pinned in
tests/test_chat_orchestrator.py and must not move.
"""
from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

from adelia.services.answer_contract import chat_system_prompt
from adelia.services.chat_orchestrator import answer_question_streaming

from tests.test_chat_orchestrator import _evidence_match


async def _ask(question: str, *, age_months: int | None = 6):
    seen: dict = {}

    async def fake_stream(system_prompt, user_message, history=None, **kwargs):
        seen["system"], seen["user"] = system_prompt, user_message
        yield "Respuesta [ev_1]."

    with patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None), \
         patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[]), \
         patch("adelia.services.chat_orchestrator.embed_texts", return_value=[[0.1] * 1024]), \
         patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query",
               return_value=[_evidence_match()]), \
         patch("adelia.services.chat_orchestrator._stream_llm_tokens", fake_stream):
        events = [e async for e in answer_question_streaming(
            user_id=uuid4(), question=question, locale="es", age_months=age_months)]
    return events, seen


async def test_a_fact_question_streams_the_short_answer():
    events, seen = await _ask("¿A qué edad empiezan a gatear?")
    assert seen["system"] == chat_system_prompt("es", shape="question")
    assert [e.type for e in events] == ["token", "final"]


async def test_a_worry_still_gets_the_plan():
    _, seen = await _ask("Le cuesta dormirse, ¿cómo le ayudo?")
    assert seen["system"] == chat_system_prompt("es")


async def test_a_fever_without_a_reading_is_answered_not_asked():
    """The agent would ask for the reading with buttons; the chat page has
    none, so it answers with what there is (principle 2)."""
    events, seen = await _ask("Tiene fiebre, ¿qué hago?")
    assert seen["system"] == chat_system_prompt("es")
    assert [e.type for e in events] == ["token", "final"]


async def test_a_diary_line_is_answered_not_recorded():
    events, seen = await _ask("hoy ha tenido 37,8 a las 5 de la tarde")
    assert "system" in seen, "the chat answers; only the agent shows a card"
    assert [e.type for e in events] == ["token", "final"]
