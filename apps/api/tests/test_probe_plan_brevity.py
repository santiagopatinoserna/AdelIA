"""scripts/probe_plan_brevity.py: the prod measurement settings.plan_brevity waits for.

The supervisor runs it inside the production API container, by hand, twice. These
tests pin, without a key or a database, that it asks the warning-sign questions
plus one in French (none stopped by the guard), that it flips plan_brevity and
nothing else, that it reads what it says (words per section, loose paragraphs,
the doctor section whole) and that it reuses the read-only call of
probe_warning_signs, one call at a time with a pause between them.
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

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_spec = importlib.util.spec_from_file_location("probe_plan_brevity",
                                               _SCRIPTS / "probe_plan_brevity.py")
pb = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = pb
_spec.loader.exec_module(pb)
pw = pb.pw


def test_it_asks_the_warning_sign_questions_and_one_in_french():
    assert pb.QUESTIONS[:-1] == pw.ALL_QUESTIONS
    qid, locale, question = pb.QUESTIONS[-1]
    assert (qid, locale) == ("diarrhee_fr", "fr")
    assert question == "Elle a la diarrhée depuis hier, que faire ?"
    assert len({i for i, _, _ in pb.QUESTIONS}) == len(pb.QUESTIONS) == 14


@pytest.mark.parametrize("qid, locale, question", pb.QUESTIONS)
def test_no_question_stops_at_the_guard_for_the_demo_baby(qid, locale, question):
    assert red_flags.detect(question, locale=locale, age_months=AGE_MONTHS) is None
    assert not child_outside_scope(question)


def test_it_reuses_the_read_only_answer_of_the_warning_signs_probe():
    assert pb.answer_once is pw.answer_once


def test_the_mode_flips_plan_brevity_only_and_puts_it_back(monkeypatch):
    monkeypatch.setattr(settings, "plan_brevity", False)
    monkeypatch.setattr(settings, "no_unasked_refusals", True)
    monkeypatch.setattr(settings, "warning_signs_retrieval", True)
    with pb.brevity(True):
        assert settings.plan_brevity is True
        assert settings.no_unasked_refusals is True
        assert settings.warning_signs_retrieval is True
    assert settings.plan_brevity is False
    with pytest.raises(RuntimeError):
        with pb.brevity(True):
            raise RuntimeError("a failed call")
    assert settings.plan_brevity is False


PLAN = """Es una laringitis y se cuida en casa [ev_1]. Suele durar tres días [ev_2].

## Hoy
- Ofrécele líquidos [ev_1].
- Cálmala en brazos [ev_1]. La calma le ayuda a respirar [ev_1].

**Evita** los jarabes para la tos [ev_3].

## Vigila
- Cómo respira [ev_2].

## Cuándo ir al médico
**Ve a urgencias** si [ev_5]:
- Hace ruido al coger aire en reposo.
- Tiene los labios azulados.

## No olvides
- Anota cuándo empezó [ev_1].

**Dosis de paracetamol:** {refusal}
"""


def _plan():
    return PLAN.format(refusal=no_evidence_reply("es"))


def test_words_and_bullets_are_counted_per_section():
    words = pb.section_words(_plan())
    assert set(words) == set(pb.SECTIONS)
    assert words["opening"] == 14
    assert words["today"] == 3 + 11 + 7
    assert words["watch"] == 3
    assert words["doctor"] == 5 + 7 + 4
    assert words["mothers"] == 0
    bullets = pb.section_bullets(_plan())
    assert (bullets["today"], bullets["watch"], bullets["doctor"], bullets["remember"]) == (
        2, 1, 2, 1)


def test_a_loose_paragraph_is_one_outside_the_doctor_section_and_the_opening():
    """The doctor section's "Ve a urgencias si:" line groups its signs by urgency,
    which the rule asks for; a loose "Evita" paragraph under Hoy is what it cuts.
    The coded refusal paragraph is reported apart, not as a loose one."""
    assert pb.loose_paragraphs(_plan()) == [("today", "**Evita** los jarabes para la tos [ev_3].")]


def test_the_opening_sentence_and_bullet_sentences_are_measured():
    assert pb.first_sentence_words(_plan()) == 8, "citation markers are not words"
    assert pb.multi_sentence_bullets(_plan()) == 1
    assert pb.first_sentence_words("") == 0


def test_the_doctor_section_is_read_whole_lead_in_included():
    assert pb.doctor_text(_plan(), "es").splitlines() == [
        "**Ve a urgencias** si [ev_5]:",
        "- Hace ruido al coger aire en reposo.",
        "- Tiene los labios azulados.",
    ]
    assert pb.doctor_text("Sin apartados [ev_1].", "es") == ""


def test_the_doctor_sections_print_side_by_side(capsys):
    off = pw.Row(kind="answer", intent="plan", answer=_plan())
    on = pw.Row(kind="answer", intent="plan",
                answer=_plan().replace("- Tiene los labios azulados.\n", ""))
    pb.print_row(("crup", "es", "Tiene tos de perro"), off, on)
    out = capsys.readouterr().out
    side = [line for line in out.splitlines() if "Hace ruido al coger aire" in line]
    assert len(side) == 1 and side[0].count("Hace ruido al coger aire") == 2
    assert "doctor bullets 2 -> 1" in out


def test_the_summary_names_every_answer_whose_doctor_section_shrank():
    full = pw.Row(kind="answer", intent="plan", answer=_plan())
    short = pw.Row(kind="answer", intent="plan",
                   answer=_plan().replace("- Tiene los labios azulados.\n", ""))
    rows = [(("crup", "es", "q"), full, short), (("tos", "es", "q"), full, full)]
    summary = pb.summarize(rows)
    assert summary["fewer_doctor_bullets"] == ["crup"]
    assert summary["off"]["doctor_bullets"] == 4 and summary["on"]["doctor_bullets"] == 3
    assert summary["off"]["refusals_inside"] == 2
    assert summary["off"]["loose_paragraphs"] == 2
    assert summary["off"]["median_words"] == len(_plan().split())
    assert summary["off"]["median_section_words"]["today"] == 21


async def test_one_call_at_a_time_off_then_on_with_a_pause(monkeypatch):
    running, peak, calls, pauses = 0, 0, [], []

    async def _answer(qid, locale, question):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        calls.append((qid, settings.plan_brevity))
        running -= 1
        return pw.Row(kind="answer", intent="plan", answer="Respuesta [ev_1].")

    async def _pause(seconds):
        pauses.append(seconds)

    monkeypatch.setattr(settings, "plan_brevity", False)
    monkeypatch.setattr(pb, "answer_once", _answer)
    monkeypatch.setattr(pb, "_pause", _pause)
    rows = await pb.run_all(pb.QUESTIONS)
    n = len(pb.QUESTIONS)
    assert peak == 1 and len(rows) == n and len(calls) == 2 * n
    assert [on for _, on in calls] == [False, True] * n
    assert len(pauses) == 2 * n - 1 and set(pauses) == {pw.PAUSE_SECONDS}
    assert settings.plan_brevity is False
