"""The reflux questionnaire must be complete, deduplicated, cover the clinical
domains, and — critically — JUSTIFY every question (why + source). This is the
machine-checked guarantee of 'no question without a fundament'."""
import pytest

from adelia.clinical.questionnaire import (
    UnjustifiedQuestionError,
    load_reflux_questionnaire,
    question_count,
    section_ids,
)


def test_loads_and_every_question_is_justified():
    data = load_reflux_questionnaire()  # raises if any question lacks why/source
    for sec in data["sections"]:
        for q in sec["questions"]:
            assert q["why"].strip(), f"{q['id']} sin justificación"
            assert q["source"].strip(), f"{q['id']} sin fuente"


def test_covers_the_essential_clinical_domains():
    ids = set(section_ids())
    # The domains Santiago asked for + what the guidelines require.
    for required in {"perinatal", "feeding", "symptoms", "red_flags",
                     "medication", "growth", "family_genetics"}:
        assert required in ids, f"falta el dominio {required}"
    assert question_count() >= 25


def test_red_flags_section_is_present_and_flagged():
    data = load_reflux_questionnaire()
    red = next(s for s in data["sections"] if s["id"] == "red_flags")
    assert any(q.get("alarm") for q in red["questions"]), "ninguna pregunta marcada como alarma"
    # the bilious-vomit surgical-emergency question must exist
    assert any("bilios" in q["text"].lower() or "verde" in q["text"].lower()
               for q in red["questions"])


def test_medication_section_captures_drug_and_since_when():
    data = load_reflux_questionnaire()
    med = next(s for s in data["sections"] if s["id"] == "medication")
    for q in med["questions"]:
        if q.get("type") == "med_detail":
            assert "desde_cuando" in q.get("fields", []), f"{q['id']} no pregunta desde cuándo"


def test_validation_rejects_unjustified_question():
    from adelia.clinical import questionnaire as mod
    bad = {"sections": [{"id": "x", "questions": [{"id": "q1", "text": "?", "source": "X"}]}]}
    with pytest.raises(UnjustifiedQuestionError):
        mod._validate(bad)


async def test_endpoint_serves_questionnaire(client):
    resp = await client.get("/clinical/reflux-questionnaire")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sections"] and "_meta" in body
