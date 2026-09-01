import re
from unittest.mock import patch
from uuid import uuid4

import pytest

from adelia.agent.executor import execute_tool
from adelia.enrichment.profile_service import ProfileFacts, UNKNOWN_PROFILE
from adelia.services.chat_orchestrator import ChatEvent


def _child(age_months: int | None, sex: str | None = "F") -> ProfileFacts:
    return ProfileFacts(
        profile_id=uuid4(), display_name="Adel", date_of_birth=None,
        sex=sex, age_months=age_months,
    )


# --- evaluar_labs reads the age off the profile (audit 3.5) ----------------
#
# v0.1 compared every value against an adult range and took no age at all, so
# on a baby the card was wrong in both directions: false alarm (140 bpm ->
# "tachycardia" against 60-100, normal in an infant; Hb 10,5 -> "low" against
# 12,0-17,5, normal at 6 months) and, worse, false reassurance (38,0 C ->
# "low_grade fever", when under 3 months that is the NICE red column). Week 1
# disabled the tool outright; week 3 gives it bands, and one hard rule that
# no card can override.


async def test_38_degrees_at_2_months_is_a_referral_not_a_card():
    """The hard rule of item 3.5. The card is painted straight to the screen
    without passing the model, so a card here would be the app itself telling
    a parent that a NICE red flag is a data point."""
    out = await execute_tool("evaluar_labs", {"name": "temperatura", "value": 38.0},
                             user_id=uuid4(), profile_id=None, facts=_child(2))
    assert out.card is None
    assert "112" in out.text
    assert "urgencias" in out.text.lower()
    assert "mg/kg" not in out.text


@pytest.mark.parametrize("name,value,age,expected", [
    ("frecuencia cardiaca", 130.0, 6, "normal"),   # ERC 2021: 100-180 at that age
    ("hemoglobina", 11.0, 9, "normal"),            # WHO 2024 cutoff is 10.5
    ("leucocitos", 13.0, 2, "normal"),             # NICE NG143: 5 to 15
])
async def test_evaluar_labs_uses_the_band_for_the_age(name, value, age, expected):
    out = await execute_tool("evaluar_labs", {"name": name, "value": value},
                             user_id=uuid4(), profile_id=None, facts=_child(age))
    assert out.card is not None
    assert out.card["payload"]["flag"] == expected
    assert "Fuente:" in out.text


async def test_evaluar_labs_without_an_age_refuses_instead_of_guessing():
    out = await execute_tool("evaluar_labs", {"name": "hemoglobina", "value": 11.0},
                             user_id=uuid4(), profile_id=None, facts=UNKNOWN_PROFILE)
    assert out.card is None
    assert "edad" in out.text.lower()


async def test_evaluar_labs_without_a_pediatric_band_refuses():
    out = await execute_tool("evaluar_labs", {"name": "hba1c", "value": 6.0},
                             user_id=uuid4(), profile_id=None, facts=_child(9))
    assert out.card is None
    assert "pediatra" in out.text.lower()


def test_the_tool_description_tells_the_model_the_age_comes_from_the_profile():
    from adelia.agent.tools import TOOLS

    labs = next(t for t in TOOLS if t["name"] == "evaluar_labs")
    assert "EDAD" in labs["description"]
    assert "perfil" in labs["description"]


# --- buscar_en_expediente carries its citations out (audit 3.7) ------------
#
# Week 1 stripped the [ev_N] markers because AgentEvent had no citation field
# and the canvas painted plain text, so every marker on /dashboard pointed at
# nothing. The agent's SSE now carries both namespaces and the canvas renders
# the same evidence card as the chat, so the markers stay and travel with the
# sources they name.


def _events(text: str, evidence: list[dict], citations: list | None = None):
    async def _gen(**kwargs):
        for tok in text.split(" "):
            yield ChatEvent(type="token", content=tok + " ")
        yield ChatEvent(type="final", evidence_citations=evidence,
                        citations=citations or [])
    return _gen


async def test_buscar_en_expediente_keeps_markers_and_returns_the_citations():
    answer = "Regurgita tras cada toma; segun la guia es habitual [ev_1] y mejora [ev_2]."
    evidence = [
        {"tag": "ev_1", "organization": "NASPGHAN-ESPGHAN",
         "title": "Pediatric GER guideline", "year": 2018},
        {"tag": "ev_2", "organization": "AEP", "title": "Reflujo", "year": 2020},
    ]
    with patch("adelia.agent.executor.answer_question_streaming", _events(answer, evidence)):
        out = await execute_tool("buscar_en_expediente", {"query": "reflujo"},
                                 user_id=uuid4(), profile_id=None, facts=_child(6))

    assert re.findall(r"\[ev_\d+\]", out.text) == ["[ev_1]", "[ev_2]"]
    assert len(out.evidence_citations) == 2


async def test_buscar_en_expediente_without_evidence_returns_nothing_to_cite():
    with patch("adelia.agent.executor.answer_question_streaming",
               _events("No tengo evidencia sobre esto.", [])):
        out = await execute_tool("buscar_en_expediente", {"query": "fiebre"},
                                 user_id=uuid4(), profile_id=None, facts=UNKNOWN_PROFILE)

    assert out.evidence_citations == []
    assert out.text == "No tengo evidencia sobre esto."


async def test_buscar_en_expediente_passes_the_profile_age_down():
    """Without this the chat's red-flag rule cannot know the baby is 2 months
    old unless the parent happens to type it."""
    seen = {}

    def _capture(**kwargs):
        seen.update(kwargs)
        return _events("ok", [])(**kwargs)

    with patch("adelia.agent.executor.answer_question_streaming", _capture):
        await execute_tool("buscar_en_expediente", {"query": "fiebre"},
                           user_id=uuid4(), profile_id=None, facts=_child(2))
    assert seen["age_months"] == 2


def test_the_agent_contract_now_reuses_the_markers_it_can_render():
    from adelia.services.answer_contract import agent_system_prompt

    for locale in ("es", "en", "fr"):
        prompt = agent_system_prompt(locale)
        assert "Fuentes citables" not in prompt
        assert "Reutiliza los marcadores" in prompt


async def test_percentil_tool_takes_age_and_sex_from_the_profile():
    seen = {}

    def _capture(**kwargs):
        seen.update(kwargs)
        return 50

    with patch("adelia.agent.executor.growth_percentile", _capture):
        out = await execute_tool("percentil_crecimiento",
                                 {"metric": "weight", "value": 5.6, "age_months": 99, "sex": "M"},
                                 user_id=uuid4(), profile_id=None, facts=_child(2, "F"))
    # The profile wins over whatever the model typed.
    assert seen["age_months"] == 2 and seen["sex"] == "F"
    assert "50" in out.text
    assert out.card and out.card["type"] == "insight"


async def test_percentil_tool_without_a_profile_asks_for_the_data():
    out = await execute_tool("percentil_crecimiento",
                             {"metric": "weight", "value": 5.6},
                             user_id=uuid4(), profile_id=None, facts=UNKNOWN_PROFILE)
    assert out.card is None
    assert "fecha de nacimiento" in out.text


async def test_unknown_tool():
    out = await execute_tool("nope", {}, user_id=uuid4(), profile_id=None)
    assert "desconocida" in out.text.lower()
