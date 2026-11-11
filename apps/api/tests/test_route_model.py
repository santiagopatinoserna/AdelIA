"""The model layer of the `route` node and the `route` chain.

The model is consulted only when the rules abstain. Its output is strict
JSON validated with pydantic, and every way it can fail (bad JSON, unknown
intent, exception, slowness) lands on `plan`, the path with the most
safeguards, flagged `via="fallback"` so the logs show it happened.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adelia.agent import route as r
from adelia.config import settings
from adelia.enrichment.profile_service import ProfileFacts

#: These tests drive the model layer themselves (fake completions, fake
#: clients); conftest's guard against live classifier calls stays out.
pytestmark = pytest.mark.routing_model_layer

KNOWN_AGE = ProfileFacts(None, "Lucía", None, "F", 6)


def _completion(text: str):
    async def _fake(system, user, *, provider=None):
        return text
    return _fake


async def test_a_valid_json_answer_becomes_a_model_decision():
    with patch.object(r, "_complete_json", _completion(
        '{"intent": "question", "confidence": 0.91, "missing": []}'
    )):
        d = await r.route_by_model("hola", locale="es", has_account=True, facts=KNOWN_AGE)
    assert d.intent == "question" and d.via == "model" and d.confidence == 0.91


async def test_json_wrapped_in_a_code_fence_is_still_read():
    with patch.object(r, "_complete_json", _completion(
        '```json\n{"intent": "plan", "confidence": 0.8, "missing": []}\n```'
    )):
        d = await r.route_by_model("hola", locale="es", has_account=True, facts=KNOWN_AGE)
    assert d.intent == "plan" and d.via == "model"


@pytest.mark.parametrize("text", [
    "no se",
    '{"intent": "chitchat", "confidence": 0.9, "missing": []}',
    '{"confidence": 0.9}',
    '{"intent": "plan", "confidence": 7, "missing": []}',
])
async def test_anything_that_does_not_validate_falls_back_to_plan(text):
    with patch.object(r, "_complete_json", _completion(text)):
        d = await r.route_by_model("hola", locale="es", has_account=True, facts=KNOWN_AGE)
    assert d.intent == "plan" and d.via == "fallback"


async def test_low_confidence_becomes_clarify():
    with patch.object(r, "_complete_json", _completion(
        '{"intent": "plan", "confidence": 0.4, "missing": ["symptom"]}'
    )):
        d = await r.route_by_model("le pasa algo", locale="es", has_account=True, facts=KNOWN_AGE)
    assert d.intent == "clarify" and d.via == "model" and d.missing == ["symptom"]


async def test_without_an_account_the_model_cannot_record_or_track():
    with patch.object(r, "_complete_json", _completion(
        '{"intent": "record", "confidence": 0.9, "missing": []}'
    )):
        d = await r.route_by_model("x", locale="es", has_account=False, facts=None)
    assert d.intent == "plan"
    with patch.object(r, "_complete_json", _completion(
        '{"intent": "track", "confidence": 0.9, "missing": []}'
    )):
        d = await r.route_by_model("x", locale="es", has_account=False, facts=None)
    assert d.intent == "question"


async def test_the_prompt_is_json_only_and_names_the_message_and_the_account():
    seen = {}

    async def _fake(system, user, *, provider=None):
        seen["system"], seen["user"] = system, user
        return '{"intent": "plan", "confidence": 0.9, "missing": []}'

    with patch.object(r, "_complete_json", _fake):
        await r.route_by_model("tiene mocos", locale="fr", has_account=False, facts=None)
    assert "JSON" in seen["system"]
    for intent in r.INTENTS:
        assert f'"{intent}"' in seen["system"]
    assert "tiene mocos" in seen["user"]
    assert "compte" in seen["user"].lower() or "account" in seen["user"].lower()


# --- provider selection: the demo's override, else the global setting --------


async def test_an_explicit_provider_wins_over_the_global_setting(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mistral")
    openai = AsyncMock(return_value="{}")
    mistral = AsyncMock(return_value="{}")
    with patch.object(r, "_openai_json", openai), patch.object(r, "_mistral_json", mistral):
        await r._complete_json("s", "u", provider="openai")
    openai.assert_awaited_once()
    mistral.assert_not_awaited()


async def test_without_a_provider_the_global_setting_decides(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mistral")
    openai = AsyncMock(return_value="{}")
    mistral = AsyncMock(return_value="{}")
    with patch.object(r, "_openai_json", openai), patch.object(r, "_mistral_json", mistral):
        await r._complete_json("s", "u")
        monkeypatch.setattr(settings, "llm_provider", "openai")
        await r._complete_json("s", "u")
    assert mistral.await_count == 1 and openai.await_count == 1


async def test_the_mistral_call_uses_the_small_routing_model_and_json_mode(monkeypatch):
    monkeypatch.setattr(settings, "mistral_api_key", "k")
    client = MagicMock()
    client.chat.complete_async = AsyncMock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"a": 1}'))]
    ))
    with patch.object(r, "get_mistral_client", return_value=client):
        out = await r._mistral_json("sys", "usr")
    assert out == '{"a": 1}'
    kwargs = client.chat.complete_async.await_args.kwargs
    assert kwargs["model"] == settings.mistral_routing_model
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["temperature"] == 0
    assert kwargs["messages"][0] == {"role": "system", "content": "sys"}
    assert kwargs["messages"][1] == {"role": "user", "content": "usr"}


def test_the_routing_model_is_a_small_one_by_default():
    from adelia.config import Settings
    assert Settings.model_fields["mistral_routing_model"].default == "mistral-small-latest"


async def test_the_mistral_call_fails_loudly_without_a_key(monkeypatch):
    monkeypatch.setattr(settings, "mistral_api_key", "")
    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
        await r._mistral_json("s", "u")


# --- route: rules, else model, never blocking --------------------------------


async def test_route_uses_the_rules_without_consulting_the_model():
    model = AsyncMock()
    with patch.object(r, "_complete_json", model):
        d = await r.route("que vacunas le tocan", locale="es", has_account=True, facts=KNOWN_AGE)
    assert d.intent == "track" and d.via == "rule"
    model.assert_not_awaited()


async def test_route_consults_the_model_when_the_rules_abstain():
    with patch.object(r, "_complete_json", _completion(
        '{"intent": "question", "confidence": 0.9, "missing": []}'
    )):
        d = await r.route("hola", locale="es", has_account=True, facts=KNOWN_AGE)
    assert d.intent == "question" and d.via == "model"


async def test_a_model_failure_is_a_plan_fallback_not_an_exception():
    async def _boom(system, user, *, provider=None):
        raise RuntimeError("MISTRAL_API_KEY not set")

    with patch.object(r, "_complete_json", _boom):
        d = await r.route("hola", locale="es", has_account=True, facts=KNOWN_AGE)
    assert d.intent == "plan" and d.via == "fallback"


async def test_a_slow_model_is_cut_at_the_deadline_and_falls_back():
    async def _slow(system, user, *, provider=None):
        await asyncio.sleep(0.5)
        return '{"intent": "question", "confidence": 0.9, "missing": []}'

    with patch.object(r, "_complete_json", _slow):
        d = await r.route("hola", locale="es", has_account=True, facts=KNOWN_AGE,
                          timeout_s=0.05)
    assert d.intent == "plan" and d.via == "fallback"


def test_the_default_deadline_is_two_seconds():
    assert r.MODEL_TIMEOUT_S == 2.0


# --- the measure-only hook the surfaces call -----------------------------------


async def test_log_route_writes_one_line_with_intent_via_and_confidence(caplog):
    caplog.set_level("INFO", logger="adelia.agent.route")
    d = await r.log_route("demo", "que vacunas le tocan", locale="es", has_account=True,
                          facts=KNOWN_AGE)
    assert d.intent == "track"
    line = next(m for m in caplog.messages if m.startswith("route intent="))
    assert "intent=track" in line and "via=rule" in line and "conf=0.90" in line
    assert "surface=demo" in line
    assert "que vacunas" not in line, "the message itself is never logged"


async def test_log_route_never_raises(caplog):
    caplog.set_level("INFO", logger="adelia.agent.route")

    async def _boom(system, user, *, provider=None):
        raise RuntimeError("down")

    with patch.object(r, "_complete_json", _boom):
        d = await r.log_route("chat", "hola", locale="es", has_account=True, facts=KNOWN_AGE)
    assert d.via == "fallback"
    assert any("via=fallback" in m for m in caplog.messages)


async def test_spawn_route_log_runs_in_the_background_and_forgets_the_task(caplog):
    caplog.set_level("INFO", logger="adelia.agent.route")
    task = r.spawn_route_log("demo", "que vacunas le tocan", locale="es", has_account=True,
                             facts=KNOWN_AGE)
    assert task in r._ROUTE_LOGS, "a strong reference keeps the task alive until it is done"
    await task
    await asyncio.sleep(0)
    assert task not in r._ROUTE_LOGS
    assert any("intent=track" in m for m in caplog.messages)


# --- the thread, in the same call (2026-11-09) -----------------------------------
#
# The router used to read "Pero todos los días está así" and "No es enfermo"
# alone. When the rules abstain the one classifier call it already made now
# also reads a short tail of the conversation and says what kind of turn this
# is and what to search; no second call. A first turn's prompt does not move.

THREAD = [
    {"role": "user", "content": "Mi bebé se queda sentado en una esquina en la guardería"},
    {"role": "assistant", "content": "Que se quede en casa si no come ni duerme [ev_1]."},
]


def _seeing(seen: dict, reply: str = '{"intent": "plan", "confidence": 0.9, "missing": []}'):
    async def _fake(system, user, *, provider=None):
        seen["system"], seen["user"] = system, user
        return reply
    return _fake


async def test_without_a_thread_the_prompt_is_the_one_it_always_was():
    seen: dict = {}
    with patch.object(r, "_complete_json", _seeing(seen)):
        await r.route_by_model("tiene mocos", locale="es", has_account=True, facts=KNOWN_AGE)
    assert '"turn"' not in seen["system"] and "search_query" not in seen["system"]
    assert seen["user"] == r._USER_PROMPT["es"].format(message="tiene mocos", account="si",
                                                       age=6)


async def test_with_a_thread_the_same_call_reads_it_and_is_asked_for_turn_and_query():
    seen: dict = {}
    with patch.object(r, "_complete_json", _seeing(seen)):
        await r.route_by_model("Pero todos los días está así", locale="es", has_account=True,
                               facts=KNOWN_AGE, history=THREAD)
    assert '"turn"' in seen["system"] and '"search_query"' in seen["system"]
    assert "esquina en la guardería" in seen["user"]
    assert "Que se quede en casa" in seen["user"]
    assert seen["user"].rstrip().endswith("Edad conocida (meses): 6")


async def test_the_model_says_the_kind_of_turn_and_the_search_query():
    reply = ('{"intent": "plan", "confidence": 0.9, "missing": [], "turn": "follow_up", '
             '"search_query": "bebé que no juega en la guardería todos los días"}')
    with patch.object(r, "_complete_json", _completion(reply)):
        d = await r.route_by_model("Pero todos los días está así", locale="es",
                                   has_account=True, facts=KNOWN_AGE, history=THREAD)
    assert d.via == "model" and d.turn == "follow_up"
    assert d.search_query == "bebé que no juega en la guardería todos los días"


@pytest.mark.parametrize("extra", [
    '"turn": "sideways"', '"turn": 3', '"search_query": ["a"]', '"search_query": 7',
])
async def test_a_bad_turn_or_query_is_dropped_and_the_intent_survives(extra):
    reply = '{"intent": "question", "confidence": 0.9, "missing": [], ' + extra + "}"
    with patch.object(r, "_complete_json", _completion(reply)):
        d = await r.route_by_model("Pero todos los días está así", locale="es",
                                   has_account=True, facts=KNOWN_AGE, history=THREAD)
    assert d.intent == "question" and d.via == "model"
    assert d.turn is None and d.search_query is None


async def test_route_hands_the_thread_to_the_model_only_when_the_rules_abstain():
    seen: dict = {}
    with patch.object(r, "_complete_json", _seeing(seen)):
        d = await r.route("hola", locale="es", has_account=True, facts=KNOWN_AGE,
                          history=THREAD)
    assert d.via == "model" and "esquina" in seen["user"]
    model = AsyncMock()
    with patch.object(r, "_complete_json", model):
        d = await r.route("que vacunas le tocan", locale="es", has_account=True,
                          facts=KNOWN_AGE, history=THREAD)
    assert d.via == "rule"
    model.assert_not_awaited()


async def test_log_route_names_the_turn_and_never_the_thread(caplog):
    caplog.set_level("INFO", logger="adelia.agent.route")
    reply = '{"intent": "plan", "confidence": 0.9, "missing": [], "turn": "correction"}'
    with patch.object(r, "_complete_json", _completion(reply)):
        await r.log_route("agent", "No es enfermo", locale="es", has_account=True,
                          facts=KNOWN_AGE, history=THREAD)
    line = next(m for m in caplog.messages if m.startswith("route intent="))
    assert "turn=correction" in line
    assert "esquina" not in line and "enfermo" not in line


async def test_an_output_that_does_not_validate_is_logged_without_its_text(caplog):
    caplog.set_level("INFO", logger="adelia.agent.route")
    reply = '{"intent": "nonsense", "search_query": "mi bebé no juega en la guardería"}'
    with patch.object(r, "_complete_json", _completion(reply)):
        d = await r.route_by_model("x", locale="es", has_account=True, facts=KNOWN_AGE,
                                   history=THREAD)
    assert d.via == "fallback"
    assert not any("guardería" in m for m in caplog.messages)


# --- why it fell back, and a turn the rules already placed (2026-11-11, round 5) -----
#
# The battery with the real model (battery-resume-20261111-1704.json): 6 turns took
# the fallback, every one of them with the thread in the call. The report could only
# say so by inference (the model step began at 2.02 s and the classifier's tokens were
# never counted). A fallback now says why. And of the 42 classifier calls, the 16
# without a thread never missed the 2 s deadline while 7 of the 26 with one did; in
# 16 of those 26 the rules had already placed the turn, so the `turn` and
# `search_query` the model was asked for were thrown away (conversation.with_kind).


async def test_a_fallback_says_why():
    async def _slow(system, user, *, provider=None):
        await asyncio.sleep(0.5)
        return '{"intent": "question", "confidence": 0.9, "missing": []}'

    class _Busy(Exception):
        status_code = 429

    async def _busy(system, user, *, provider=None):
        raise _Busy("no capacity")

    with patch.object(r, "_complete_json", _slow):
        late = await r.route("hola", locale="es", has_account=True, facts=KNOWN_AGE,
                             timeout_s=0.05)
    with patch.object(r, "_complete_json", _busy):
        busy = await r.route("hola", locale="es", has_account=True, facts=KNOWN_AGE)
    with patch.object(r, "_complete_json", _completion("no se")):
        invalid = await r.route("hola", locale="es", has_account=True, facts=KNOWN_AGE)
    assert (late.via, late.reason) == ("fallback", "timeout")
    assert (busy.via, busy.reason) == ("fallback", "error:_Busy 429")
    assert (invalid.via, invalid.reason) == ("fallback", "invalid")
    ruled = await r.route("que vacunas le tocan", locale="es", has_account=True,
                          facts=KNOWN_AGE)
    assert ruled.reason is None


async def test_a_reason_the_model_writes_is_not_taken():
    reply = '{"intent": "question", "confidence": 0.9, "missing": [], "reason": "timeout"}'
    with patch.object(r, "_complete_json", _completion(reply)):
        d = await r.route_by_model("hola", locale="es", has_account=True, facts=KNOWN_AGE)
    assert d.via == "model" and d.reason is None


async def test_a_turn_already_placed_reads_the_thread_but_is_not_asked_its_kind():
    placed: dict = {}
    first: dict = {}
    with patch.object(r, "_complete_json", _seeing(placed)):
        await r.route_by_model("y de dalsy", locale="es", has_account=True, facts=KNOWN_AGE,
                               history=THREAD, ask_turn=False)
    with patch.object(r, "_complete_json", _seeing(first)):
        await r.route_by_model("y de dalsy", locale="es", has_account=True, facts=KNOWN_AGE)
    # The first turn's system prompt, byte for byte: no turn, no search_query to write.
    assert placed["system"] == first["system"]
    assert "esquina en la guardería" in placed["user"]
    assert placed["user"].rstrip().endswith("Edad conocida (meses): 6")


async def test_a_kind_or_query_it_was_not_asked_for_is_dropped():
    reply = ('{"intent": "question", "confidence": 0.9, "missing": [], "turn": "new", '
             '"search_query": "dalsy"}')
    with patch.object(r, "_complete_json", _completion(reply)):
        d = await r.route_by_model("y de dalsy", locale="es", has_account=True,
                                   facts=KNOWN_AGE, history=THREAD, ask_turn=False)
    assert d.intent == "question" and d.via == "model"
    assert d.turn is None and d.search_query is None


async def test_route_and_log_route_hand_ask_turn_down():
    for call in (r.route, lambda m, **kw: r.log_route("agent", m, **kw)):
        seen: dict = {}
        with patch.object(r, "_complete_json", _seeing(seen)):
            await call("hola", locale="es", has_account=True, facts=KNOWN_AGE,
                       history=THREAD, ask_turn=False)
        assert "esquina" in seen["user"] and '"search_query"' not in seen["system"]
