import re
from unittest.mock import patch
from uuid import uuid4

import pytest

from adelia.agent.executor import execute_tool, ToolOutcome
from adelia.services.chat_orchestrator import ChatEvent


# --- evaluar_labs emits no card, because its ranges are adult ---------------
#
# lab_ranges v0.1 says so itself (enrichment/lab_ranges.py:5-7, "Adult
# ranges") and evaluate() takes no age, so on a baby the card was wrong in
# both directions: false alarm (140 bpm -> "tachycardia" against 60-100,
# normal in an infant; Hb 10,5 -> "low" against 12,0-17,5, normal at 6 months)
# and, worse, false reassurance (38,0 C -> "low_grade_fever", when under 3
# months that is a same-day assessment). The card is yielded straight to the
# screen without passing the model (agent/orchestrator.py), so no clause of
# answer_contract could correct it, and it carried neither [ev_N] nor a
# disclaimer. Age-banded ranges are audit item 3.5; until then, no card.


@pytest.mark.parametrize("name,value", [
    ("temperatura", 38.0),      # the under-3-months case, previously "febrícula"
    ("frecuencia cardiaca", 140.0),
    ("hemoglobina", 10.5),
])
async def test_evaluar_labs_no_emite_tarjeta_con_rangos_de_adulto(name, value):
    out = await execute_tool("evaluar_labs", {"name": name, "value": value},
                             user_id=uuid4(), profile_id=None)
    assert isinstance(out, ToolOutcome)
    assert out.card is None, "an adult reference range must not reach the screen"
    assert "adulto" in out.text
    assert "pediatra" in out.text


def test_the_tool_description_tells_the_model_not_to_use_it():
    from adelia.agent.tools import TOOLS

    labs = next(t for t in TOOLS if t["name"] == "evaluar_labs")
    assert "adulto" in labs["description"]


# --- buscar_en_expediente hands back sources, not orphan markers ------------
#
# answer_contract makes every clinical claim carry [ev_N] because the CHAT
# renders those as source cards. The agent canvas paints plain text and
# AgentEvent has no citations field, so the same markers land on /dashboard,
# the screen the parent actually opens, pointing at nothing. Propagating the
# citations properly is audit item 3.7 (week 3); until then the tool strips
# the markers and names the sources instead.


def _events(text: str, evidence: list[dict]):
    async def _gen(**kwargs):
        for tok in text.split(" "):
            yield ChatEvent(type="token", content=tok + " ")
        yield ChatEvent(type="final", evidence_citations=evidence)
    return _gen


async def test_buscar_en_expediente_leaves_no_orphan_markers():
    answer = "Regurgita tras cada toma [1]; segun la guia es habitual [ev_1] y mejora [ev_2]."
    with patch("adelia.agent.executor.answer_question_streaming",
               _events(answer, [{"organization": "NASPGHAN-ESPGHAN",
                                 "title": "Pediatric GER guideline", "year": 2018}])):
        out = await execute_tool("buscar_en_expediente", {"query": "reflujo"},
                                 user_id=uuid4(), profile_id=None)

    assert re.search(r"\[(?:ev_)?\d+\]", out.text) is None, out.text
    assert "NASPGHAN-ESPGHAN" in out.text
    assert "Fuentes citables" in out.text


async def test_buscar_en_expediente_without_evidence_names_nothing():
    with patch("adelia.agent.executor.answer_question_streaming",
               _events("No tengo evidencia sobre esto.", [])):
        out = await execute_tool("buscar_en_expediente", {"query": "fiebre"},
                                 user_id=uuid4(), profile_id=None)

    assert "Fuentes citables" not in out.text
    assert out.text == "No tengo evidencia sobre esto."


def test_the_agent_contract_forbids_the_markers_it_cannot_render():
    from adelia.services.answer_contract import agent_system_prompt

    for locale in ("es", "en", "fr"):
        prompt = agent_system_prompt(locale)
        assert "Fuentes citables" in prompt
        assert "Nunca dejes un [1] ni un [ev_1]" in prompt

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
