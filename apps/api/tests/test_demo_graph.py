"""The public demo runs the agent graph (AGENT_GRAPH, build step 2).

Visible change: a question that asks for a fact gets a short answer, not the
four-section plan, and the response says which (`intent`) so the page can
title it "Tu respuesta" instead of "Tu plan". Everything else the demo
promised is pinned elsewhere and must not move: red flags first, the budget
after them, real corpus citations, refusals in code (tests/test_demo.py,
test_demo_experience.py, test_experience_only.py).
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from adelia.agent.route import RouteDecision
from adelia.config import settings
from adelia.enrichment.evidence_retrieval import EvidenceMatch
from adelia.services.answer_contract import chat_system_prompt

from tests.pg_gate import PG_AVAILABLE

pg_only = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")


def _match() -> EvidenceMatch:
    return EvidenceMatch(
        chunk_id=uuid.uuid4(), source_id=uuid.uuid4(), source_title="A real guideline",
        organization="Org", publication_year=2024, url="https://example.org/e",
        content="fragment", chunk_index=0, distance=0.07, tier="evidence",
    )


async def _ask(client, question: str, *, locale: str = "es"):
    seen: dict = {}

    async def _retrieve(session, **kwargs):
        return [_match()]

    async def _no_experience(session, **kwargs):
        return []

    async def _generate(system_prompt, user_message, **kwargs):
        seen["system"], seen["user"], seen["kwargs"] = system_prompt, user_message, kwargs
        return "Respuesta [ev_1]."

    with patch("adelia.routers.demo.embed_texts", return_value=[[0.0] * 1024]), patch(
        "adelia.routers.demo.retrieve_evidence", _retrieve
    ), patch("adelia.routers.demo.retrieve_experience", _no_experience), patch(
        "adelia.routers.demo.generate_answer", _generate
    ):
        resp = await client.post("/demo/ask", json={"question": question, "locale": locale})
    assert resp.status_code == 200, resp.text
    return resp.json(), seen


@pg_only
async def test_a_fact_question_gets_the_short_answer_contract(client):
    body, seen = await _ask(client, "¿Es normal que regurgite tras cada toma?")
    assert body["kind"] == "answer"
    assert body["intent"] == "question"
    assert seen["system"] == chat_system_prompt("es", shape="question")
    assert "Lucía" in seen["user"], "the demo baby's record is still citable"


@pg_only
async def test_a_worry_still_gets_the_plan(client):
    body, seen = await _ask(client, "¿Cómo le ayudo a dormir mejor?")
    assert body["kind"] == "answer"
    assert body["intent"] == "plan"
    assert seen["system"] == chat_system_prompt("es")


@pg_only
async def test_the_demo_generates_with_its_own_provider(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_llm_provider", "openai")
    _, seen = await _ask(client, "¿A qué edad empiezan a gatear?")
    assert seen["kwargs"].get("provider") == "openai"


@pg_only
async def test_the_demo_routes_with_its_provider_the_babys_age_and_no_account(
    client, monkeypatch
):
    calls: list[tuple] = []

    async def _route(surface, message, **kwargs):
        calls.append((surface, message, kwargs))
        return RouteDecision(intent="question", confidence=0.9, via="rule")

    monkeypatch.setattr("adelia.routers.demo.log_route", _route)
    monkeypatch.setattr(settings, "demo_llm_provider", "openai")
    body, _ = await _ask(client, "¿Cómo le ayudo a dormir mejor?")
    assert body["intent"] == "question", "the route decision is obeyed, not just logged"
    (surface, message, kwargs), = calls
    assert surface == "demo" and message == "¿Cómo le ayudo a dormir mejor?"
    assert kwargs["has_account"] is False
    assert kwargs["facts"].age_months == 5
    assert kwargs["provider"] == "openai"


@pg_only
async def test_a_red_flag_carries_no_intent_and_is_never_routed(client, monkeypatch):
    calls: list = []

    async def _route(surface, message, **kwargs):
        calls.append(message)
        return RouteDecision(intent="question", confidence=0.9, via="rule")

    monkeypatch.setattr("adelia.routers.demo.log_route", _route)
    resp = await client.post(
        "/demo/ask", json={"question": "Tiene 2 meses y 38,5 de fiebre, ¿qué hago?", "locale": "es"}
    )
    assert resp.json()["kind"] == "red_flag"
    assert resp.json().get("intent") is None
    assert calls == []


@pg_only
async def test_an_embedding_failure_is_still_a_503(client):
    with patch("adelia.routers.demo.embed_texts", side_effect=RuntimeError("no key")):
        resp = await client.post("/demo/ask", json={"question": "¿A qué edad gatean?"})
    assert resp.status_code == 503
