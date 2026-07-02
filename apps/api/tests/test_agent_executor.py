from unittest.mock import patch, MagicMock
from uuid import uuid4
from adelia.agent.executor import execute_tool, ToolOutcome

async def test_evaluar_labs_returns_card():
    fake = MagicMock(canonical_name="Hemoglobina", value=9.0, unit="g/dL",
                     flag="low", range="12-16", interpretation="Bajo")
    with patch("adelia.agent.executor.lab_evaluate", return_value=fake):
        out = await execute_tool("evaluar_labs", {"name": "Hb", "value": 9.0},
                                 user_id=uuid4(), profile_id=None)
    assert isinstance(out, ToolOutcome)
    assert out.card and out.card["type"] == "lab"
    assert out.card["payload"]["flag"] == "low"

async def test_percentil_tool():
    with patch("adelia.agent.executor.growth_percentile", return_value=50):
        out = await execute_tool("percentil_crecimiento",
                                 {"metric": "weight", "value": 5.6, "age_months": 2, "sex": "M"},
                                 user_id=uuid4(), profile_id=None)
    assert "50" in out.text
    assert out.card and out.card["type"] == "insight"

async def test_unknown_tool():
    out = await execute_tool("nope", {}, user_id=uuid4(), profile_id=None)
    assert "desconocida" in out.text.lower()
