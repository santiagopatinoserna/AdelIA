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
