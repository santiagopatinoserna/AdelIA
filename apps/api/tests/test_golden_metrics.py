"""The golden set's own instruments: dosage, matching, the report contract.

`tests/test_rag_golden.py` runs the set. This file tests the pieces the set is
measured with, none of which needs a key, a corpus or a database, so a bug in
a metric is found by a test that always runs rather than by a gate that skips.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from adelia.clinical.golden import (
    GOLDEN_SET,
    RED_FLAG_DOSAGE_MAX,
    GoldenReport,
    contains_dosage,
    corpus_blind_spots,
    is_refusal,
    questions,
    run_red_flag_group,
    source_matches,
)
from adelia.clinical.red_flags import PRIORITY
from adelia.services.answer_contract import (
    interface_disclaimer,
    no_evidence_reply,
    red_flag_reply,
)

API_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# contains_dosage (audit 3.3: "la respuesta no contiene mg/kg")
# ---------------------------------------------------------------------------

DOSES = [
    # the audit's own example, and the metric units
    "10 mg/kg cada 6 horas",
    "la dosis es de 15 mg/kg",
    "250 mg",
    "125 mg/5 ml",
    "200 mcg",
    "50 ml/kg de suero oral",
    "mg/kg",
    # volumes, drops, spoons, tablets, in the three languages
    "Dale 5 ml de paracetamol",
    "Dale 2,5 ml",
    "Puedes darle 3 gotas",
    "dale una cucharadita de jarabe",
    "Administra el jarabe dos veces al día",
    "2 comprimidos",
    "Give 2.5 ml every 4 to 6 hours",
    "give her half a teaspoon",
    "take 1/2 teaspoon",
    "a few drops of it",
    "Donnez 5 ml toutes les 6 heures",
    "donnez-lui deux gouttes",
    "une demi-cuillère à café",
    # a medicine's frequency after a dosing verb, with no unit at all
    "dale paracetamol cada 6 horas",
    "Give her Calpol every 4 hours",
    "Give him paracetamol three times a day",
    "Donnez du Doliprane toutes les 6 heures",
]

CLINICAL_NUMBERS = [
    # the two the task names, in each language's way of writing them
    "Tiene 38,2 °C y pesa 6,4 kg",
    "Temperature 38.2 °C and weight 6.4 kg",
    "Température 38,2 °C, poids 6,4 kg",
    "38,2 °C y 6,4 kg",
    # lab values, whose units contain mg, g, ml or l
    "Hb 11 g/dL, ferritina 12 ng/mL, glucosa 90 mg/dL",
    "colesterol 180 mg/dl",
    "bilirrubina 2 mg/dL",
    "ferritina 12 µg/L",
    "TFG 90 ml/min",
    # ages, durations, counts, the emergency number, a score
    "tiene 2 meses y 3 semanas",
    "12 horas sin pañal mojado; llama al 112",
    "Elle a 38,2 et elle a 2 mois",
    "call 112 now",
    "5 sobre 10",
    "The vaccine schedule has 3 doses",
    "He weighs 6400 g and is 62 cm",
    "ha ganado 200 g",
    # frequencies that are not dosing
    "Revisa la temperatura cada 4 horas",
    "Take his temperature every 4 hours",
    "The nurse will check him every 2 hours",
    # feeding
    "toma 120 ml de leche cada 3 horas",
    "Dale el pecho cada 3 horas",
    # the refusal wording, which must not trip the thing that guards it
    "No le des ningún medicamento por tu cuenta",
    "Do not give any medicine on your own in the meantime",
    "Ne donnez aucun médicament de votre propre initiative",
    "if the temperature drops",
    "",
]


@pytest.mark.parametrize("text", DOSES)
def test_a_dose_is_a_dose(text):
    assert contains_dosage(text, "es"), text


@pytest.mark.parametrize("text", CLINICAL_NUMBERS)
def test_a_plain_clinical_number_is_not_a_dose(text):
    assert not contains_dosage(text, "es"), text


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_the_locale_never_narrows_the_match(locale):
    """A Spanish-locale answer that says "give 5 ml" still gave a dose."""
    assert contains_dosage("Give 5 ml", locale)
    assert contains_dosage("Dale 5 ml", locale)
    assert contains_dosage("Donnez 5 ml", locale)


def test_no_red_flag_reply_nor_the_fixed_texts_carry_a_dose():
    """All eleven flags in all three languages, plus the refusal and the disclaimer.

    This is the audit's acceptance criterion for 3.3 asserted on the wording
    itself, not only on the five group C questions that happen to be asked.
    """
    for code in PRIORITY:
        for locale in ("es", "en", "fr"):
            reply = red_flag_reply(code, locale)
            assert not contains_dosage(reply, locale), f"{code}/{locale}: {reply[:80]!r}"
    for locale in ("es", "en", "fr"):
        assert not contains_dosage(no_evidence_reply(locale), locale)
        assert not contains_dosage(interface_disclaimer(locale), locale)


def test_a_red_flag_answer_with_a_dose_would_fail_the_gate(monkeypatch):
    """Wiring: the report counts it and `failures()` names it."""
    from adelia.clinical import golden

    monkeypatch.setattr(
        "adelia.services.answer_contract.red_flag_reply",
        lambda code, locale, **kw: "Llama al 112. Dale 10 mg/kg cada 6 horas.",
    )
    report = golden.run_red_flag_group()
    assert report.red_flag_dosage == len(questions("C"))
    assert report.red_flag_rate == 1.0  # the detector still fired; the ANSWER is what failed
    assert any("dosis" in f for f in report.failures()), report.failures()
    assert not any(r["passed"] for r in report.results.values())
    assert report.as_dict()["red_flag_dosage"] == len(questions("C"))


def test_the_dosage_threshold_is_zero():
    assert RED_FLAG_DOSAGE_MAX == 0


# ---------------------------------------------------------------------------
# source_matches and is_refusal
# ---------------------------------------------------------------------------


def test_a_single_substring_behaves_as_it_always_did():
    assert source_matches("reflujo", "reflujo (ger) vs enfermedad por reflujo | otra")
    assert not source_matches("reflujo", "bronquiolitis en niños")
    assert source_matches("Alimentación Complementaria", "recomendaciones ... alimentación complementaria")


def test_any_alternative_is_enough():
    titles = "fer et nutrition | something else"
    assert source_matches("iron requirements|ferropenia|fer et nutrition", titles)
    assert not source_matches("iron requirements|ferropenia", titles)


def test_an_empty_alternative_never_matches_everything():
    """A trailing "|" must not turn the expectation into "anything"."""
    assert not source_matches("iron requirements|", "bronquiolitis")
    assert not source_matches("", "bronquiolitis")


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_the_refusal_and_the_referral_count_as_refusals(locale):
    assert is_refusal(no_evidence_reply(locale), locale)
    assert is_refusal(red_flag_reply("fever_under_3_months", locale), locale)
    assert not is_refusal("Según la guía [ev_1], son 10 mg/kg.", locale)


def test_a_refusal_in_the_wrong_language_is_not_a_refusal():
    """An English refusal does not satisfy a French question."""
    assert not is_refusal(no_evidence_reply("en"), "fr")


# ---------------------------------------------------------------------------
# The report is a contract with deploy-prod.sh and compare_golden.py
# ---------------------------------------------------------------------------

#: Every field the report had before the 2026-10-14 widening, with its type.
LEGACY_FIELDS = {
    "recall_at_4": (float, type(None)),
    "refusal_rate": (float, type(None)),
    "red_flag_rate": (float, type(None)),
    "orphan_citations": (int,),
    "questions_run": (dict,),
    "misses": (list,),
    "skipped_reason": (str, type(None)),
}


def test_every_legacy_report_field_survives_with_its_type():
    data = run_red_flag_group().as_dict()
    for name, types in LEGACY_FIELDS.items():
        assert name in data, f"{name} was removed: scripts/deploy-prod.sh would break"
        assert isinstance(data[name], types), (name, type(data[name]))
    assert set(data["questions_run"]) == {"A", "B", "C"}
    assert all(isinstance(v, int) for v in data["questions_run"].values())


def test_the_new_report_fields_are_present_and_serialisable():
    data = run_red_flag_group().as_dict()
    for name in ("red_flag_dosage", "questions_run_by_locale", "rates_by_locale", "results", "blind_spots"):
        assert name in data, name
    round_tripped = json.loads(json.dumps(data, ensure_ascii=False))
    assert round_tripped["red_flag_dosage"] == 0
    assert set(round_tripped["results"]) == {q.id for q in questions("C")}


def test_the_report_with_nothing_run_is_still_valid():
    data = GoldenReport().as_dict()
    assert data["recall_at_4"] is None and data["refusal_rate"] is None
    assert data["results"] == {} and data["rates_by_locale"] == {}
    assert GoldenReport().failures() == []


def test_a_question_that_did_not_run_is_absent_not_failed():
    report = run_red_flag_group()
    assert not any(qid.startswith(("A", "B")) for qid in report.results)
    assert report.questions_run_by_locale() == {
        "es": {"C": 5}, "en": {"C": 5}, "fr": {"C": 5},
    }


def test_rates_by_locale_shows_a_regression_the_aggregate_hides():
    report = GoldenReport()
    a = {q.id: q for q in questions("A")}
    for qid in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"):
        report.mark(a[qid], True)
    for qid in ("A10", "A11", "A12"):
        report.mark(a[qid], False)
    rates = report.rates_by_locale()["A"]
    assert rates == {"en": 1.0, "es": 1.0, "fr": 0.0}
    assert sum(1 for r in report.results.values() if r["passed"]) / 12 == 0.75


def test_the_render_names_the_dosage_line_and_the_per_locale_rates():
    text = run_red_flag_group().render()
    assert "banderas rojas con dosis:  0" in text
    assert "grupo C por idioma" in text and "en 1.00" in text and "fr 1.00" in text


# ---------------------------------------------------------------------------
# Group C keeps its one property: no key, no corpus, no network
# ---------------------------------------------------------------------------


def test_group_c_runs_without_importing_a_database_a_client_or_a_key():
    """The most important property of the file, checked in a clean process.

    The child imports the golden module and runs group C, then reports which
    heavy modules ended up loaded. If someone makes group C depend on the
    database, an HTTP client or a model SDK, the gate silently stops being
    runnable in CI with no secrets, and this fails first.
    """
    program = (
        "import json, sys\n"
        "from adelia.clinical.golden import run_red_flag_group\n"
        "r = run_red_flag_group()\n"
        "heavy = [m for m in ('sqlalchemy', 'asyncpg', 'httpx', 'mistralai', 'anthropic', "
        "'adelia.db', 'adelia.config', 'adelia.workers.embed') if m in sys.modules]\n"
        "print(json.dumps({'rate': r.red_flag_rate, 'dosage': r.red_flag_dosage, 'heavy': heavy}))\n"
    )
    env = {
        k: v for k, v in os.environ.items()
        if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD", "DATABASE", "POSTGRES"))
    }
    env["PYTHONPATH"] = str(API_ROOT)
    out = subprocess.run(
        [sys.executable, "-c", program], cwd=API_ROOT, env=env,
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result == {"rate": 1.0, "dosage": 0, "heavy": []}, result


# ---------------------------------------------------------------------------
# Blind spots
# ---------------------------------------------------------------------------


def test_blind_spots_list_the_corpus_themes_no_a_question_touches():
    spots = corpus_blind_spots()
    assert spots, "the corpus files are in the repo; this must not be None"
    themes = {s["theme"] for s in spots}
    assert {"alimentacion_bebes", "guarderia_adaptacion", "pediatric_reflux", "urgencias_lactante"} <= themes
    for s in spots:
        assert 0 <= s["untouched"] <= s["sources"]
        assert len(s["examples"]) <= 3
    # The most-ignored theme comes first, so the next question to add is obvious.
    ratios = [s["untouched"] / s["sources"] for s in spots]
    assert ratios == sorted(ratios, reverse=True)


def test_a_source_a_question_names_is_not_a_blind_spot():
    spots = {s["theme"]: s for s in corpus_blind_spots()}
    reflux = spots["pediatric_reflux"]
    # A4 expects "reflujo", which matches every title of that file.
    assert reflux["untouched"] == 0 and reflux["sources"] == 7


def test_the_adult_sources_that_ride_along_are_not_counted():
    """Only `pediatrics`-tagged sources are searched, so only they can be blind."""
    spots = {s["theme"]: s for s in corpus_blind_spots()}
    assert spots["seed"]["sources"] == 2  # GINA asthma and the CDC schedule


def test_blind_spots_degrade_to_a_note_when_the_corpus_is_missing(tmp_path):
    assert corpus_blind_spots(tmp_path) is None
    report = GoldenReport()
    report.blind_spots = corpus_blind_spots(tmp_path)
    text = report.render()
    assert "puntos ciegos del corpus: no disponible" in text
    assert report.as_dict()["blind_spots"] is None


def test_blind_spots_degrade_when_a_corpus_file_is_malformed(tmp_path):
    (tmp_path / "evidence_broken.json").write_text("{not json", encoding="utf-8")
    assert corpus_blind_spots(tmp_path) is None
    (tmp_path / "evidence_broken.json").write_text('{"sources": [{"nope": 1}]}', encoding="utf-8")
    assert corpus_blind_spots(tmp_path) is None


def test_blind_spots_render_one_line_per_theme_with_examples():
    report = run_red_flag_group()
    report.blind_spots = corpus_blind_spots()
    text = report.render()
    assert "puntos ciegos del corpus:" in text
    assert "urgencias_lactante:" in text and "p. ej." in text


def test_every_question_belongs_to_a_known_locale_and_group():
    assert {q.group for q in GOLDEN_SET} == {"A", "B", "C"}
    assert {q.locale for q in GOLDEN_SET} == {"es", "en", "fr"}
