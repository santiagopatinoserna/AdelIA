"""The /dashboard agent runs the agent graph (AGENT_GRAPH steps 4-5).

`run_turn` replaces the old model-and-tools loop (`run_agent_turn`, retired).
The loop survives as the graph's `track` node, bounded to 3 steps, for her
own data and for whatever the router cannot place. A plan or a fact question
takes the same contract path as the chat; a diary line becomes a card and is
written only when she confirms it; a fever without a reading gets the
question with buttons.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa

from adelia.agent import record as rec
from adelia.agent.orchestrator import MAX_STEPS, run_turn
from adelia.db import AsyncSessionLocal
from adelia.enrichment.profile_service import ProfileFacts
from adelia.models import Observation, Profile
from adelia.services.answer_contract import chat_system_prompt

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE
from tests.test_chat_orchestrator import _evidence_match

pg_only = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")
MADRID = ZoneInfo("Europe/Madrid")


def _exploding_provider():
    class P:
        async def stream_step(self, *, system, messages, tools):
            raise AssertionError("this path must not reach the tool loop")
            yield  # pragma: no cover
    return P()


async def _collect(gen):
    return [e async for e in gen]


def test_the_tool_loop_is_bounded_to_three_steps():
    assert MAX_STEPS == 3


async def test_a_fact_question_takes_the_contract_path_not_the_tool_loop():
    seen: dict = {}

    async def fake_stream(system_prompt, user_message, history=None, **kwargs):
        seen["system"] = system_prompt
        yield "Hacia los 8 meses [ev_1]."

    facts = ProfileFacts(None, "Lucía", None, "F", 6)
    with patch("adelia.agent.orchestrator.get_provider", _exploding_provider), \
         patch("adelia.agent.orchestrator.load_profile_facts", return_value=facts), \
         patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None), \
         patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[]), \
         patch("adelia.services.chat_orchestrator.embed_texts", return_value=[[0.1] * 1024]), \
         patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query",
               return_value=[_evidence_match()]), \
         patch("adelia.services.chat_orchestrator._stream_llm_tokens", fake_stream):
        events = await _collect(run_turn(user_id=uuid4(), profile_id=None,
                                         message="¿A qué edad empiezan a gatear?"))
    assert seen["system"] == chat_system_prompt("es", shape="question")
    assert [e.type for e in events] == ["token", "final"]
    assert events[-1].evidence_citations[0]["tag"] == "ev_1"


async def test_a_fever_without_a_reading_gets_the_clarify_card():
    facts = ProfileFacts(None, "Lucía", None, "F", 6)
    with patch("adelia.agent.orchestrator.get_provider", _exploding_provider), \
         patch("adelia.agent.orchestrator.load_profile_facts", return_value=facts):
        events = await _collect(run_turn(user_id=uuid4(), profile_id=None,
                                         message="Tiene fiebre, ¿qué hago?"))
    cards = [e.card for e in events if e.type == "card"]
    assert [c["type"] for c in cards] == ["clarify"]
    assert cards[0]["payload"]["message"] == "Tiene fiebre, ¿qué hago?"
    assert events[-1].type == "final"


@pg_only
async def test_a_diary_line_becomes_a_card_and_writes_nothing():
    user_id = await make_user()
    facts = ProfileFacts(None, "Lucía", None, "F", 6)
    with patch("adelia.agent.orchestrator.get_provider", _exploding_provider), \
         patch("adelia.agent.orchestrator.load_profile_facts", return_value=facts):
        events = await _collect(run_turn(user_id=user_id, profile_id=None,
                                         message="hoy ha tenido 37,8 a las 5 de la tarde"))
    (card,) = [e.card for e in events if e.type == "card"]
    assert card["type"] == "confirm" and card["payload"]["tool_name"] == rec.RECORD_TOOL
    async with AsyncSessionLocal() as session:
        n = await session.scalar(sa.select(sa.func.count()).select_from(Observation)
                                 .where(Observation.user_id == user_id))
    assert n == 0


@pg_only
async def test_confirming_the_card_writes_one_row_for_that_child_and_compares():
    user_id = await make_user()
    async with AsyncSessionLocal() as session:
        child = Profile(user_id=user_id, display_name="Lucía", relationship="child",
                        is_default=True)
        session.add(child)
        await session.commit()
        await session.refresh(child)
    facts = ProfileFacts(child.id, "Lucía", None, "F", 6)
    now = datetime.now(MADRID)
    yesterday = rec.RecordDraft("temperature", 37.2, "°C", now - timedelta(days=1), "37,2")
    today = rec.RecordDraft("temperature", 37.8, "°C", now - timedelta(minutes=5), "37,8")

    async def _confirm(draft):
        action = {"intent": "confirm", "tool_name": rec.RECORD_TOOL,
                  "tool_args": rec.draft_args(draft)}
        with patch("adelia.agent.orchestrator.get_provider", _exploding_provider), \
             patch("adelia.agent.orchestrator.load_profile_facts", return_value=facts):
            return await _collect(run_turn(user_id=user_id, profile_id=child.id, message="",
                                           card_action=action))

    await _confirm(yesterday)
    events = await _confirm(today)
    text = "".join(e.content for e in events if e.type == "token")
    assert text.startswith("Anotado: 37,8 °C, hoy a las")
    assert text.endswith("La anterior: ayer, 37,2 °C.")
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            sa.select(Observation).where(Observation.user_id == user_id)
            .order_by(Observation.observed_at)
        )).scalars().all()
    assert [(r.value, r.profile_id, r.source) for r in rows] == [
        (37.2, child.id, "agent"), (37.8, child.id, "agent"),
    ]
