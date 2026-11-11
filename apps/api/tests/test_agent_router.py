from adelia.routers.agent import _map_event
from adelia.agent.events import AgentEvent

def test_map_token():
    ev = _map_event(AgentEvent(type="token", content="hi"))
    assert ev["event"] == "token"
    assert '"hi"' in ev["data"]

def test_map_card():
    ev = _map_event(AgentEvent(type="card", card={"type": "lab", "id": "l1", "payload": {}, "actions": []}))
    assert ev["event"] == "card"
    assert '"lab"' in ev["data"]

def test_map_final():
    assert _map_event(AgentEvent(type="final"))["event"] == "final"


# --- a card with two questions (2026-11-09) ---------------------------------------

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from adelia.routers.agent import AgentTurnRequest  # noqa: E402
from tests.test_agent_history_guard import auth_headers  # noqa: E402,F401  (fixture)


def test_a_two_question_card_sends_both_answers():
    payload = AgentTurnRequest.model_validate({
        "message": "Mi bebé en la guardería se queda en una esquina",
        "clarifications": [{"field": "nursery_time", "value": "lt1m"},
                           {"field": "social_signals", "value": "all"}],
    })
    assert [c.field for c in payload.clarifications] == ["nursery_time", "social_signals"]


@pytest.mark.parametrize("answers", [
    [{"field": "weight", "value": "7"}],
    [{"field": "since_when", "value": "x" * 17}],
    [{"field": "since_when", "value": "days"}] * 3,
])
def test_an_answer_we_never_asked_for_is_refused(answers):
    with pytest.raises(ValidationError):
        AgentTurnRequest.model_validate({"message": "x", "clarifications": answers})


@pytest.mark.usefixtures("auth_headers")
async def test_both_answers_reach_the_graph(client):
    from unittest.mock import patch

    seen: dict = {}

    async def _fake_run_turn(**kwargs):
        seen.update(kwargs)
        yield AgentEvent(type="final", citations=[], evidence_citations=[])

    with patch("adelia.routers.agent.run_turn", _fake_run_turn):
        resp = await client.post("/agent/turn", headers={"Authorization": "Bearer dummy"}, json={
            "message": "q", "clarifications": [{"field": "since_when", "value": "days"},
                                               {"field": "general_state", "value": "no"}],
        })
    assert resp.status_code == 200, resp.text
    assert seen["clarifications"] == [{"field": "since_when", "value": "days"},
                                      {"field": "general_state", "value": "no"}]


def test_map_status():
    """What the panel shows while it waits (agent-canvas.tsx)."""
    import json as _json

    ev = _map_event(AgentEvent(type="status", content="writing", sources=3))
    assert ev["event"] == "status"
    assert _json.loads(ev["data"]) == {"stage": "writing", "sources": 3}
