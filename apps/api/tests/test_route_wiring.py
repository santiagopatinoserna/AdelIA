"""Where the route node is wired, surface by surface.

Build step 1 measured `route` on both surfaces: one log line after the
red-flag check, the response untouched. Build step 2 (agent/graph.py) makes
the demo OBEY it: the same call, awaited as the graph's route node, picks
the answer contract. The chat still only measures until build step 5. These
tests pin that the call happens with the right context, that a red flag
never reaches it, and that a dead classifier changes nothing the mother sees
(the fallback is the plan, which is what both surfaces answered before).
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from adelia.agent import route as r
from adelia.config import settings
from adelia.enrichment.evidence_retrieval import EvidenceMatch
from adelia.services.chat_orchestrator import answer_question_streaming

from tests.pg_gate import PG_AVAILABLE

pg_only = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")


def _match() -> EvidenceMatch:
    return EvidenceMatch(
        chunk_id=uuid.uuid4(), source_id=uuid.uuid4(), source_title="A real guideline",
        organization="Org", publication_year=2024, url="https://example.org/e",
        content="fragment", chunk_index=0, distance=0.07, tier="evidence",
    )


class _Spy:
    """Stands in for `spawn_route_log`: records the call, logs nothing, schedules nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, surface, message, **kwargs):
        self.calls.append((surface, message, kwargs))
        return MagicMock()


class _AsyncSpy:
    """Stands in for `log_route` on the demo, where the graph awaits it: records
    the call and returns the plan, the decision a dead classifier would give."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def __call__(self, surface, message, **kwargs):
        self.calls.append((surface, message, kwargs))
        return r.RouteDecision(intent="plan", confidence=0.9, via="rule")


# --- demo ----------------------------------------------------------------------


async def _ask_demo(client, question: str):
    async def _retrieve(session, **kwargs):
        return [_match()]

    async def _no_experience(session, **kwargs):
        return []

    async def _generate(system_prompt, user_message, **kwargs):
        return "Plan de prueba [ev_1]."

    with patch("adelia.routers.demo.embed_texts", return_value=[[0.0] * 1024]), patch(
        "adelia.routers.demo.retrieve_evidence", _retrieve
    ), patch("adelia.routers.demo.retrieve_experience", _no_experience), patch(
        "adelia.routers.demo.generate_answer", _generate
    ):
        return await client.post("/demo/ask", json={"question": question, "locale": "es"})


@pg_only
async def test_the_demo_routes_after_the_red_flag_check_with_the_demo_babys_age(
    client, monkeypatch
):
    spy = _AsyncSpy()
    monkeypatch.setattr("adelia.routers.demo.log_route", spy)
    monkeypatch.setattr(settings, "demo_llm_provider", "openai")
    resp = await _ask_demo(client, "¿Cómo le ayudo a dormir mejor?")
    assert resp.status_code == 200
    assert resp.json()["kind"] == "answer" and resp.json()["answer"] == "Plan de prueba [ev_1]."
    assert len(spy.calls) == 1
    surface, message, kwargs = spy.calls[0]
    assert surface == "demo" and message == "¿Cómo le ayudo a dormir mejor?"
    assert kwargs["has_account"] is False
    assert kwargs["facts"].age_months == 5, "the demo baby's age is on the page; no clarify"
    assert kwargs["provider"] == "openai", "the demo's own provider, as generate_answer"


@pg_only
async def test_the_demo_never_routes_a_red_flag(client, monkeypatch):
    spy = _AsyncSpy()
    monkeypatch.setattr("adelia.routers.demo.log_route", spy)
    resp = await client.post(
        "/demo/ask", json={"question": "Tiene 2 meses y 38,5 de fiebre, ¿qué hago?", "locale": "es"}
    )
    assert resp.json()["kind"] == "red_flag"
    assert spy.calls == []


@pg_only
async def test_a_dead_classifier_changes_nothing_in_the_demo_answer(client, caplog):
    caplog.set_level("INFO", logger="adelia.agent.route")

    async def _boom(system, user, *, provider=None):
        raise RuntimeError("down")

    with patch.object(r, "_complete_json", _boom):
        resp = await _ask_demo(client, "hola, una cosa")
        for task in list(r._ROUTE_LOGS):
            await task
    assert resp.status_code == 200
    assert resp.json()["kind"] == "answer" and resp.json()["answer"] == "Plan de prueba [ev_1]."
    assert any("intent=plan via=fallback" in m for m in caplog.messages)


# --- chat ----------------------------------------------------------------------


@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query")
@patch("adelia.services.chat_orchestrator.embed_texts", return_value=[[0.1] * 1024])
@patch("adelia.services.chat_orchestrator._stream_llm_tokens")
async def test_the_chat_routes_with_the_profile_age_and_an_account(
    mock_stream, mock_embed, mock_evidence, mock_retrieve, mock_temporal, monkeypatch
):
    async def fake_stream(*args, **kwargs):
        yield "Respuesta."
    mock_stream.side_effect = fake_stream
    mock_evidence.return_value = [_match()]
    spy = _Spy()
    monkeypatch.setattr("adelia.services.chat_orchestrator.spawn_route_log", spy)
    profile_id = uuid4()

    events = [
        e async for e in answer_question_streaming(
            user_id=uuid4(), question="que vacunas le tocan", locale="es",
            age_months=7, profile_id=profile_id,
        )
    ]
    assert [e.type for e in events] == ["token", "final"]
    assert events[0].content == "Respuesta."
    assert len(spy.calls) == 1
    surface, message, kwargs = spy.calls[0]
    assert surface == "chat" and message == "que vacunas le tocan"
    assert kwargs["has_account"] is True and kwargs["locale"] == "es"
    assert kwargs["facts"].age_months == 7 and kwargs["facts"].profile_id == profile_id
    assert kwargs.get("provider") is None, "real accounts follow llm_provider, as the chat"


async def test_the_chat_never_routes_a_red_flag(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr("adelia.services.chat_orchestrator.spawn_route_log", spy)
    events = [
        e async for e in answer_question_streaming(
            user_id=uuid4(), question="Tiene 2 meses y 38,5 de fiebre", locale="es",
            age_months=2,
        )
    ]
    assert [e.type for e in events] == ["token", "final"]
    assert spy.calls == []
