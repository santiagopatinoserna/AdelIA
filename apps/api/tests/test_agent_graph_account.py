"""The graph on the account surfaces: the chat and the agent (AGENT_GRAPH steps 4-5).

Same graph as the demo, different capabilities lent through GraphDeps:

  chat   streams; her record + evidence; no buttons, no cards, no writes
  agent  streams; buttons, cards, writes, and the tool loop (`track`)

What is pinned here: tokens stream as they come and the final frame carries
both citation namespaces; a surface never gets an intent it cannot show
(no buttons in the chat, no record without a card); the agent's tool loop
takes what the router cannot place; a diary line becomes a card and nothing
is written until she confirms it; a confirmed card is validated again.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from adelia.agent import record as rec
from adelia.agent.graph import GraphDeps, Retrieved, WriteOutcome, stream_graph
from adelia.agent.route import RouteDecision
from adelia.enrichment.profile_service import ProfileFacts
from adelia.services.answer_contract import chat_system_prompt, no_evidence_reply

from tests.test_agent_graph import EVIDENCE

MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 10, 23, 18, 0, tzinfo=MADRID)
AGE_6 = ProfileFacts(None, "Lucía", None, "F", 6)


class Store:
    def __init__(self, previous=None):
        self.saved: list[rec.RecordDraft] = []
        self._previous = previous

    async def save(self, draft):
        self.saved.append(draft)

    async def previous(self, kind, before):
        return self._previous


class Account:
    """Fakes for an account surface; `calls` records what reached what."""

    def __init__(self, *, intent="plan", via="rule", missing=(), evidence=(EVIDENCE,),
                 patient=None, tokens=("Res", "puesta [ev_1]."), store=None):
        self.decision = RouteDecision(intent=intent, confidence=0.9, via=via,
                                      missing=list(missing))
        self.evidence, self.patient, self.tokens = list(evidence), patient, list(tokens)
        self.store = store
        self.calls: list[tuple] = []

    async def route(self, message, **kwargs):
        self.calls.append(("route", message))
        return self.decision

    async def retrieve(self, state):
        self.calls.append(("retrieve", state["message"]))
        cites = [{"chunk_id": "c1"}] if self.patient else []
        return Retrieved(evidence=self.evidence, patient_context=self.patient, citations=cites)

    async def stream(self, system, user):
        self.calls.append(("stream", system, user))
        for t in self.tokens:
            yield t

    async def track(self, state):
        self.calls.append(("track", state["message"]))
        yield {"type": "tool_call", "tool_name": "proximas_vacunas"}
        yield {"type": "token", "content": "Le toca la del rotavirus [ev_1]."}
        yield {"type": "result", "answer": "Le toca la del rotavirus [ev_1].",
               "citations": [], "evidence_citations": [{"tag": "ev_1", "title": "Calendario"}]}

    async def write_tool(self, name, args):
        self.calls.append(("write_tool", name, args))
        return WriteOutcome(text="Briefing generado.", card={"type": "briefing", "id": "b1",
                                                             "payload": {}, "actions": []})

    def names(self):
        return [c[0] for c in self.calls]

    def chat(self) -> GraphDeps:
        return GraphDeps(route=self.route, retrieve=self.retrieve, stream=self.stream,
                         can_ask=False, now=lambda: NOW)

    def agent(self) -> GraphDeps:
        return GraphDeps(route=self.route, retrieve=self.retrieve, stream=self.stream,
                         can_ask=True, can_write=True, record_store=self.store,
                         write_tool=self.write_tool, track=self.track, now=lambda: NOW)


async def _run(deps, message, **state):
    events = [e async for e in stream_graph(
        {"surface": "agent", "locale": "es", "message": message, "account": True,
         "facts": AGE_6, **state}, deps)]
    final = events[-1]
    assert final["type"] == "final"
    return events[:-1], final["state"]


def _tokens(events):
    return "".join(e["content"] for e in events if e["type"] == "token")


# --- streaming and the two citation namespaces ------------------------------------


async def test_tokens_stream_as_they_come_and_the_final_carries_both_namespaces():
    fakes = Account(patient="[1] Revisión de los 4 meses")
    events, final = await _run(fakes.chat(), "¿Cómo le ayudo a dormir mejor?")
    assert [e["content"] for e in events if e["type"] == "token"] == ["Res", "puesta [ev_1]."]
    assert final["kind"] == "answer" and final["answer"] == "Respuesta [ev_1]."
    assert final["citations"] == [{"chunk_id": "c1"}]
    assert final["evidence_citations"][0]["tag"] == "ev_1"
    (_, system, user), = [c for c in fakes.calls if c[0] == "stream"]
    assert system == chat_system_prompt("es")
    assert "## Patient data" in user and "Revisión de los 4 meses" in user


async def test_a_question_streams_the_short_answer_on_an_account_too():
    fakes = Account(intent="question")
    await _run(fakes.chat(), "¿A qué edad gatean?")
    (_, system, _), = [c for c in fakes.calls if c[0] == "stream"]
    assert system == chat_system_prompt("es", shape="question")


async def test_her_record_alone_is_enough_to_answer():
    fakes = Account(evidence=[], patient="[1] Hb 11,2 g/dL")
    _, final = await _run(fakes.chat(), "¿Qué dio la analítica?")
    assert final["kind"] == "answer"


async def test_no_evidence_and_no_record_is_the_refusal_streamed_as_one_token():
    fakes = Account(evidence=[], patient=None)
    events, final = await _run(fakes.chat(), "¿Qué opinas de la fibrilación auricular?")
    assert final["kind"] == "no_evidence"
    assert _tokens(events) == no_evidence_reply("es")
    assert "stream" not in fakes.names()
    assert final["citations"] == [] and final["evidence_citations"] == []


async def test_a_red_flag_streams_the_referral_with_the_country_number():
    fakes = Account()
    events, final = await _run(fakes.chat(), "Tiene 2 meses y 38,5 de fiebre", country="FR")
    assert final["kind"] == "red_flag" and "112" in _tokens(events)
    assert fakes.calls == []


# --- what each surface can show -------------------------------------------------


async def test_the_chat_never_asks_with_buttons_it_answers():
    fakes = Account(intent="clarify", missing=["temperature"])
    events, final = await _run(fakes.chat(), "Tiene fiebre, ¿qué hago?")
    assert final["kind"] == "answer" and final["intent"] == "plan"
    assert not [e for e in events if e["type"] == "card"]


async def test_the_chat_never_records_it_answers():
    fakes = Account(intent="record")
    _, final = await _run(fakes.chat(), "hoy ha tenido 37,8")
    assert final["intent"] == "plan" and final["kind"] == "answer"


async def test_the_chat_reads_her_own_data_as_a_question_over_her_record():
    fakes = Account(intent="track", patient="[1] Vacunas: hexavalente 2 m")
    _, final = await _run(fakes.chat(), "¿Qué vacunas le tocan?")
    assert final["intent"] == "question" and "track" not in fakes.names()


async def test_the_agent_asks_with_a_clarify_card_that_carries_her_message():
    fakes = Account(intent="clarify", missing=["temperature"])
    events, final = await _run(fakes.agent(), "Tiene fiebre, ¿qué hago?")
    (card,) = [e["card"] for e in events if e["type"] == "card"]
    assert card["type"] == "clarify" and card["payload"]["field"] == "temperature"
    assert card["payload"]["message"] == "Tiene fiebre, ¿qué hago?"
    assert len(card["payload"]["options"]) == 3
    assert _tokens(events) == "", "the card is the question; no duplicate text"
    assert final["kind"] == "clarify"


@pytest.mark.parametrize("intent, via", [("other", "rule"), ("plan", "fallback")])
async def test_what_the_router_cannot_place_goes_to_the_agents_tool_loop(intent, via):
    fakes = Account(intent=intent, via=via)
    events, final = await _run(fakes.agent(), "hola")
    assert "track" in fakes.names() and "retrieve" not in fakes.names()
    assert {"type": "tool_call", "tool_name": "proximas_vacunas"} in events
    assert final["kind"] == "tracked"
    assert final["evidence_citations"] == [{"tag": "ev_1", "title": "Calendario"}]
    assert _tokens(events) == "Le toca la del rotavirus [ev_1].", "streamed once, not twice"


async def test_a_rule_question_on_the_agent_takes_the_contract_not_the_loop():
    fakes = Account(intent="question")
    await _run(fakes.agent(), "¿A qué edad gatean?")
    assert "track" not in fakes.names() and "stream" in fakes.names()


# --- record: a card, never a silent write ------------------------------------------


async def test_a_diary_line_becomes_a_card_and_nothing_is_written():
    store = Store()
    fakes = Account(intent="record", store=store)
    events, final = await _run(fakes.agent(), "hoy ha tenido 37,8 a las 5 de la tarde")
    (card,) = [e["card"] for e in events if e["type"] == "card"]
    assert card["type"] == "confirm" and card["payload"]["tool_name"] == rec.RECORD_TOOL
    assert card["payload"]["body"] == "Temperatura: 37,8 °C, hoy a las 17:00"
    assert final["kind"] == "confirm" and store.saved == []
    assert "retrieve" not in fakes.names() and "stream" not in fakes.names()


async def test_without_a_store_a_diary_line_is_answered_not_recorded():
    fakes = Account(intent="record", store=None)
    _, final = await _run(fakes.agent(), "hoy ha tenido 37,8")
    assert final["intent"] == "plan"


async def test_a_recorded_value_of_alarm_is_the_referral_not_a_card():
    """The rules of the guard read the MESSAGE; a value the model read from
    words reaches the value guard instead."""
    import json

    async def _model(system, user, *, provider=None):
        return json.dumps({"kind": "temperature", "value": 38.4, "unit": "°C"})

    store = Store()
    fakes = Account(intent="record", store=store)
    deps = GraphDeps(**{**fakes.agent().__dict__, "complete_json": _model})
    events, final = await _run(deps, "ha tenido treinta y ocho y pico",
                               facts=ProfileFacts(None, None, None, None, 2))
    assert final["kind"] == "red_flag" and "112" in _tokens(events)
    assert not [e for e in events if e["type"] == "card"] and store.saved == []


# --- write: only what she confirmed, validated again --------------------------------


def _confirm(draft):
    return {"intent": "confirm", "tool_name": rec.RECORD_TOOL, "tool_args": rec.draft_args(draft)}


async def test_a_confirmed_card_is_written_and_answered_in_one_line_with_the_comparison():
    yesterday = rec.RecordDraft("temperature", 37.2, "°C", NOW - timedelta(hours=22), "x")
    store = Store(previous=yesterday)
    fakes = Account(store=store)
    draft = rec.RecordDraft("temperature", 37.8, "°C", NOW.replace(hour=17), "hoy ha tenido 37,8")
    events, final = await _run(fakes.agent(), "", card_action=_confirm(draft))
    assert store.saved == [draft]
    assert _tokens(events) == "Anotado: 37,8 °C, hoy a las 17:00. La anterior: ayer, 37,2 °C."
    assert final["kind"] == "recorded"
    assert fakes.calls == [], "no guard on an empty message, no route, no model"


async def test_a_tampered_card_is_refused_and_nothing_is_written():
    store = Store()
    fakes = Account(store=store)
    action = {"intent": "confirm", "tool_name": rec.RECORD_TOOL,
              "tool_args": {"kind": "temperature", "value": 378, "unit": "°C",
                            "observed_at": NOW.isoformat(), "text": "x"}}
    events, _ = await _run(fakes.agent(), "", card_action=action)
    assert store.saved == [] and _tokens(events).startswith("No he podido anotarlo")


async def test_a_confirmed_value_of_alarm_is_not_written_silently():
    store = Store()
    fakes = Account(store=store)
    draft = rec.RecordDraft("temperature", 38.3, "°C", NOW, "38,3")
    events, final = await _run(fakes.agent(), "", card_action=_confirm(draft),
                               facts=ProfileFacts(None, None, None, None, 1))
    assert final["kind"] == "red_flag" and store.saved == []


async def test_another_confirmed_write_goes_to_the_surfaces_write_tool():
    fakes = Account()
    action = {"intent": "confirm", "tool_name": "generar_briefing",
              "tool_args": {"specialty": "pediatrics"}}
    events, _ = await _run(fakes.agent(), "", card_action=action)
    assert ("write_tool", "generar_briefing", {"specialty": "pediatrics"}) in fakes.calls
    assert [e["card"]["type"] for e in events if e["type"] == "card"] == ["briefing"]
    assert _tokens(events) == "Briefing generado."


async def test_the_chat_cannot_write_a_record_even_if_a_card_arrives():
    store = Store()
    fakes = Account(store=store)
    draft = rec.RecordDraft("temperature", 37.8, "°C", NOW, "x")
    await _run(fakes.chat(), "", card_action=_confirm(draft))
    assert store.saved == []


async def test_a_surface_that_cannot_show_a_card_never_records_even_with_a_store():
    store = Store()
    fakes = Account(intent="record", store=store)
    deps = GraphDeps(route=fakes.route, retrieve=fakes.retrieve, stream=fakes.stream,
                     can_write=False, record_store=store, now=lambda: NOW)
    events, final = await _run(deps, "hoy ha tenido 37,8")
    assert final["intent"] == "plan"
    assert not [e for e in events if e["type"] == "card"] and store.saved == []
