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


# --- the croup question with a dose, and every fragment handed to the model -------
#
# Measured in prod on 2026-11-06: the croup question with a dose in it found the
# SEUP "cuándo ir a urgencias" paragraph in its main search and wrote "Ve a
# urgencias si hace ruido al coger aire"; the same question without the dose did
# not. The probe asks both and prints the topic of every fragment the model read,
# so the supervisor sees whether the paragraph on when to go arrives.


def test_the_croup_question_with_a_dose_follows_the_measured_twelve():
    assert [i for i, _, _ in pw.FOLLOW_UPS] == ["crup_dosis"]
    (_, locale, question), = pw.FOLLOW_UPS
    assert locale == "es" and question.startswith("Tiene tos de perro por la noche")
    assert "ml" in question
    assert pw.ALL_QUESTIONS == (*pw.QUESTIONS, *pw.FOLLOW_UPS)
    assert len({i for i, _, _ in pw.ALL_QUESTIONS}) == 13


@pytest.mark.parametrize("qid, locale, question", pw.FOLLOW_UPS)
def test_the_follow_up_does_not_stop_at_the_guard_for_the_demo_baby(qid, locale, question):
    assert red_flags.detect(question, locale=locale, age_months=AGE_MONTHS) is None
    assert not child_outside_scope(question)


async def test_the_whole_run_is_thirteen_questions_twice(monkeypatch):
    calls = []

    async def _answer(qid, locale, question):
        calls.append(qid)
        return pw.Row(kind="answer", intent="plan", answer="", sources=[])

    async def _pause(seconds):
        return None

    monkeypatch.setattr(pw, "answer_once", _answer)
    monkeypatch.setattr(pw, "_pause", _pause)
    await pw.run_all(pw.ALL_QUESTIONS)
    assert len(calls) == 26 and calls[-2:] == ["crup_dosis", "crup_dosis"]


def _fragment(content: str, title: str = "Laringitis (Familia y Salud, AEPap)"):
    from uuid import uuid4

    from adelia.enrichment.evidence_retrieval import EvidenceMatch

    return EvidenceMatch(chunk_id=uuid4(), source_id=uuid4(), source_title=title,
                         organization="AEPap", publication_year=2017, url=None,
                         content=content, chunk_index=0, distance=0.1)


def test_every_fragment_handed_to_the_model_is_listed_by_its_topic():
    given = pw.fragment_topics([
        _fragment("Laringitis (AEPap). Tema: qué hacer en casa. Hallazgo: líquidos."),
        _fragment("Laringitis (AEPap). Tema: cuándo acudir a urgencias. Hallazgo: ruido."),
        _fragment("An abstract without a topic line.", title="A paper"),
    ])
    assert given == [
        ("ev_1", "Laringitis (Familia y Salud, AEPap)", "qué hacer en casa"),
        ("ev_2", "Laringitis (Familia y Salud, AEPap)", "cuándo acudir a urgencias"),
        ("ev_3", "A paper", ""),
    ]


def test_the_row_prints_every_fragment_given_not_only_the_cited(capsys):
    row = pw.Row(kind="answer", intent="plan", answer="Respuesta [ev_1].",
                 sources=[("ev_1", "Laringitis (AEPap)")],
                 given=[("ev_1", "Laringitis (AEPap)", "qué hacer en casa"),
                        ("ev_2", "Laringitis (SEUP)", "cuidados en casa y cuándo ir a urgencias")])
    pw.print_row(("crup", "es", "Tiene tos de perro"), row, row)
    out = capsys.readouterr().out
    assert "given   [ev_2] Laringitis (SEUP): cuidados en casa y cuándo ir a urgencias" in out
    assert out.count("given ") == 4, "both modes, every fragment"
