"""scripts/probe_warning_signs.py: the prod measurement the two settings wait for.

The supervisor runs it once inside the production API container, by hand. These
tests pin, without a key or a database, that it asks what it says (the four
prod answers word for word and eight topics with clear warning signs, none
stopped by the guard), that it reads what it says (the doctor bullets, where
the refusal sits), that it is cheap (one call at a time, a pause between them,
12 questions x 2 modes at most) and that it cannot write.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from adelia.clinical import red_flags
from adelia.clinical.age_scope import child_outside_scope
from adelia.config import settings
from adelia.demo.fixture import AGE_MONTHS
from adelia.services.answer_contract import no_evidence_reply

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "probe_warning_signs.py"
_spec = importlib.util.spec_from_file_location("probe_warning_signs", _PATH)
pw = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = pw
_spec.loader.exec_module(pw)


def test_the_four_prod_answers_come_first_word_for_word():
    assert [q for _, _, q in pw.QUESTIONS[:4]] == [
        "Tiene tos de perro por la noche, ¿qué puedo hacer en casa?",
        "Tiene el culito muy rojo del pañal",
        "¿A qué edad suelen empezar a gatear?",
        "Tiene la cabeza un poco plana por detrás",
    ]


def test_twelve_questions_at_most_and_the_eight_topics_with_warning_signs():
    assert len(pw.QUESTIONS) == 12
    ids = [i for i, _, _ in pw.QUESTIONS]
    assert len(set(ids)) == 12
    topics = {i for i, _, _ in pw.QUESTIONS[4:]}
    assert topics == {"fiebre", "bronquiolitis", "otitis", "vomitos", "diarrea",
                      "golpe_cabeza", "exantema", "estrenimiento"}


@pytest.mark.parametrize("qid, locale, question", pw.QUESTIONS)
def test_no_question_stops_at_the_guard_for_the_demo_baby(qid, locale, question):
    """A referral would measure nothing: no retrieval, no model."""
    assert red_flags.detect(question, locale=locale, age_months=AGE_MONTHS) is None
    assert not child_outside_scope(question)


PLAN = """Para la laringitis, mantén la calma y ofrécele líquidos [ev_1].

## Hoy
- Respira aire fresco con él junto a una ventana [ev_2].

## Cuándo ir al médico
- **Urgencias** si respira con ruido en reposo [ev_5].
* Hoy, si tiene fiebre alta [ev_1].

## No olvides
- Anota cuándo empezó [ev_1].

**Cremas o pomadas para el pañal:** {refusal}
"""


def test_the_doctor_bullets_are_the_lines_of_that_section_only():
    answer = PLAN.format(refusal=no_evidence_reply("es"))
    assert pw.doctor_bullets(answer, "es") == [
        "**Urgencias** si respira con ruido en reposo [ev_5].",
        "Hoy, si tiene fiebre alta [ev_1].",
    ]
    assert pw.doctor_bullets("Sin apartados [ev_1].", "es") == []


def test_the_refusal_is_located_by_its_bold_label_or_its_section():
    answer = PLAN.format(refusal=no_evidence_reply("es"))
    assert pw.refusal_places(answer) == ["Cremas o pomadas para el pañal"]
    under_heading = f"Respuesta [ev_1].\n\n## Cuándo ir al médico\n{no_evidence_reply('es')}"
    assert pw.refusal_places(under_heading) == ["## Cuándo ir al médico"]
    assert pw.refusal_places(no_evidence_reply("en")) == ["(whole answer)"]
    assert pw.refusal_places(PLAN.format(refusal="")) == []


def test_a_mode_sets_both_settings_in_memory_and_puts_them_back(monkeypatch):
    monkeypatch.setattr(settings, "warning_signs_retrieval", False)
    monkeypatch.setattr(settings, "no_unasked_refusals", False)
    with pw.mode(True):
        assert settings.warning_signs_retrieval is True
        assert settings.no_unasked_refusals is True
    assert settings.warning_signs_retrieval is False and settings.no_unasked_refusals is False
    with pytest.raises(RuntimeError):
        with pw.mode(True):
            raise RuntimeError("a failed call")
    assert settings.warning_signs_retrieval is False


async def test_every_session_is_read_only_before_its_first_query():
    seen: list[str] = []

    class _Session:
        async def execute(self, statement, *args, **kwargs):
            seen.append(str(statement))

    async def _search(session, **kwargs):
        await session.execute("SELECT 1")
        return []

    await pw.read_only(_search)(_Session(), query_embedding=[0.0])
    assert seen == ["SET TRANSACTION READ ONLY", "SELECT 1"]


async def test_one_call_at_a_time_with_a_pause_and_two_modes(monkeypatch):
    running, peak, calls, pauses = 0, 0, [], []

    async def _answer(qid, locale, question):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        calls.append((qid, settings.warning_signs_retrieval))
        running -= 1
        return pw.Row(kind="answer", intent="plan", answer="Respuesta [ev_1].", sources=[])

    async def _pause(seconds):
        pauses.append(seconds)

    monkeypatch.setattr(pw, "answer_once", _answer)
    monkeypatch.setattr(pw, "_pause", _pause)
    rows = await pw.run_all(pw.QUESTIONS)
    assert peak == 1
    assert len(calls) == 24 and len(rows) == 12
    assert [on for _, on in calls] == [False, True] * 12
    assert len(pauses) == 23 and set(pauses) == {pw.PAUSE_SECONDS} and pw.PAUSE_SECONDS == 2.0
