from adelia.agent.cards import card_confirm, card_lab
from adelia.agent.events import AgentEvent

def test_confirm_card_shape():
    c = card_confirm("c1", "¿Genero el briefing?", "generar_briefing", {"specialty": "peds"})
    assert c["type"] == "confirm"
    assert c["id"] == "c1"
    assert c["payload"]["tool_name"] == "generar_briefing"
    assert c["payload"]["tool_args"] == {"specialty": "peds"}
    assert any(a["intent"] == "confirm" for a in c["actions"])
    assert any(a["intent"] == "cancel" for a in c["actions"])

def test_lab_card_flag():
    c = card_lab("l1", "Hemoglobina", 9.0, "g/dL", "low", "12-16", "Bajo")
    assert c["type"] == "lab"
    assert c["payload"]["flag"] == "low"

def test_agent_event_defaults():
    e = AgentEvent(type="token", content="hi")
    assert e.card is None and e.tool_name == ""
