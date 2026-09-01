"""The detector that has to fire before the model does (audit 3.3).

Risk 1 of the audit is "clinical harm to a baby from an answer that looks
sourced and is not". These tests pin the two halves of the guarantee: the
right questions fire, and the ordinary questions a parent asks all day do
not, because a detector that fires on everything gets ignored like the
vaccine card did.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from adelia.clinical.red_flags import (
    FEVER_AGE_LIMIT_MONTHS,
    FEVER_THRESHOLD_C,
    PRIORITY,
    RED_FLAG_SOURCES,
    age_months_in,
    citation_for,
    detect,
    temperature_in,
)


# --- the case the audit names ---------------------------------------------


def test_the_audit_case_fires_and_the_answer_carries_no_dose():
    """3.3's own acceptance criterion, verbatim."""
    from adelia.services.answer_contract import red_flag_reply

    flag = detect("Mi bebé de 2 meses tiene 38,2, ¿le doy paracetamol?")
    assert flag is not None and flag.code == "fever_under_3_months"
    reply = red_flag_reply(flag.code, "es")
    assert "mg/kg" not in reply and "paracetamol" not in reply.lower()
    assert "112" in reply


# --- fever, the one age-gated rule ----------------------------------------


@pytest.mark.parametrize("question,age,expected", [
    ("mi bebé tiene fiebre", 1, True),
    ("mi bebé tiene fiebre", 2, True),
    ("mi bebé tiene fiebre", 3, False),      # the boundary is exclusive
    ("mi bebé tiene fiebre", 10, False),
    ("mi bebé tiene 38,5", 1, True),
    ("mi bebé tiene 37,4", 1, False),        # a number below the threshold
    ("my 7 week old has a temperature of 38.5", None, True),
    ("Mon bébé de 6 semaines a 38,4 de fièvre", None, True),
    ("mi hija de 8 meses tiene 38,5 y está contenta", None, False),
])
def test_fever_under_three_months(question, age, expected):
    flag = detect(question, age_months=age)
    fired = flag is not None and flag.code == "fever_under_3_months"
    assert fired is expected, flag


def test_the_thresholds_are_the_nice_ones():
    assert FEVER_AGE_LIMIT_MONTHS == 3
    assert FEVER_THRESHOLD_C == 38.0


def test_the_smaller_of_profile_and_stated_age_wins():
    """A stale profile or a sibling's question must not disable the rule."""
    assert detect("mi bebé de 2 meses tiene fiebre", age_months=18) is not None
    assert detect("mi bebé de 18 meses tiene fiebre", age_months=2) is not None


# --- the ten pattern flags -------------------------------------------------


@pytest.mark.parametrize("question,code", [
    ("se atragantó con un trozo de manzana", "choking"),
    ("he choked on a grape, what do I do", "choking"),
    ("il a fait une fausse route avec un morceau de pomme", "choking"),
    ("se le hinchó la cara y la lengua después del huevo", "anaphylaxis"),
    ("swollen lips and trouble breathing after peanut", "anaphylaxis"),
    ("tiene los labios azules", "cyanosis"),
    ("his lips are blue", "cyanosis"),
    ("ses lèvres sont bleues", "cyanosis"),
    ("tuvo una convulsión anoche", "seizure"),
    ("she had a seizure this morning", "seizure"),
    ("respira con quejido y se le marcan las costillas", "respiratory_distress"),
    ("my baby is grunting and has chest indrawing", "respiratory_distress"),
    ("il a du mal à respirer et fait du tirage", "respiratory_distress"),
    ("le salieron manchas que no desaparecen al presionar", "non_blanching_rash"),
    ("a rash that doesn't fade when pressed", "non_blanching_rash"),
    ("des taches qui ne s'effacent pas", "non_blanching_rash"),
    ("tiene la fontanela abombada", "bulging_fontanelle"),
    ("his soft spot is bulging", "bulging_fontanelle"),
    ("no se despierta desde hace horas", "lethargy"),
    ("he won't wake up", "lethargy"),
    ("lleva 14 horas sin mojar el pañal", "no_wet_nappy_12h"),
    ("no wet nappy for 13 hours", "no_wet_nappy_12h"),
    ("llora sin lágrimas y tiene los ojos hundidos", "dehydration"),
])
def test_pattern_flags_fire(question, code):
    flag = detect(question)
    assert flag is not None, question
    assert flag.code == code, f"{question!r} fired {flag.code} instead of {code}"


def test_the_nappy_rule_needs_twelve_hours():
    """NICE NG9 1.6.1 says 12 hours. Three hours is a normal morning."""
    assert detect("no ha mojado el pañal en 3 horas") is None
    assert detect("no ha mojado el pañal en 14 horas") is not None


def test_priority_puts_the_minutes_before_the_hours():
    """Choking and anaphylaxis are minutes; a fever in a neonate is hours."""
    flag = detect("mi bebé de 2 meses tiene fiebre y se ha atragantado")
    assert flag is not None and flag.code == "choking"


# --- and the ordinary questions do not fire --------------------------------


@pytest.mark.parametrize("question,age", [
    ("¿cuándo empiezo con la alimentación complementaria?", 6),
    ("¿es normal que no gatee a los 9 meses?", 9),
    ("¿cuánto debería pesar un bebé de 6 meses?", 6),
    ("mide 38 cm de perímetro craneal, ¿es normal?", 2),
    ("¿cuánto tarda en adaptarse a la guardería?", 12),
    ("regurgita después de cada toma, ¿es normal?", 3),
    ("nació a las 38 semanas, ¿duerme demasiado?", 1),
    ("what vaccines are due at 12 months?", 12),
    ("combien de siestes à 8 mois ?", 8),
])
def test_everyday_questions_do_not_fire(question, age):
    assert detect(question, age_months=age) is None, question


def test_empty_and_whitespace_are_not_flags():
    assert detect("") is None
    assert detect("   ") is None


# --- helpers ---------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("tiene 38,2", 38.2),
    ("temperature of 38.5", 38.5),
    ("39 grados", 39.0),
    ("38 °C", 38.0),
    ("mi bebé de 40 días", None),      # an age, not a temperature
    ("nació a las 38 semanas", None),  # gestational age, not a temperature
    ("pesa 4 kg", None),
])
def test_temperature_is_only_read_where_it_cannot_be_something_else(text, expected):
    assert temperature_in(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("mi bebé de 2 meses", 2),
    ("6 semanas", 1),
    ("20 días", 0),
    ("recién nacido", 0),
    ("my 7 week old", 1),
    ("de 18 mois", 18),
    ("sin edad", None),
])
def test_age_is_read_from_the_question(text, expected):
    assert age_months_in(text) == expected


# --- the guideline behind each flag really exists ---------------------------


def test_every_flag_points_at_a_source_in_the_urgent_care_corpus():
    """A rename in the corpus must not leave a flag citing a source that is
    no longer loaded: the red-flag answer skips retrieval, so this mapping is
    the only thing standing between the parent and an unsourced claim."""
    corpus = json.loads(
        (Path(__file__).resolve().parents[1] / "adelia" / "enrichment" / "data"
         / "evidence_urgencias_lactante.json").read_text(encoding="utf-8")
    )
    titles = {s["title"] for s in corpus["sources"]}
    for code in PRIORITY:
        assert RED_FLAG_SOURCES[code]["title"] in titles, code


def test_citation_has_the_shape_the_evidence_card_renders():
    flag = detect("mi bebé de 2 meses tiene 38,2")
    citation = citation_for(flag)
    assert set(citation) >= {"tag", "source_id", "title", "organization", "year", "url"}
    assert citation["tag"] == "ev_1"
