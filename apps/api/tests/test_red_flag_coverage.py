"""The coverage set: every way a mother tells a red flag fires, and the look-alikes do not.

The phrases live in tests/red_flag_phrasings.py (origins and rules there);
scripts/red_flag_coverage.py prints the same set as a table per flag, against
this tree or a git ref, which is how the before/after of the #retr4 sweep was
measured. Pure code: no model, no database, no key, so it runs whole in CI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from adelia.clinical.golden import contains_dosage
from adelia.clinical.red_flags import PRIORITY, RED_FLAG_SOURCES, citation_for, detect
from adelia.services.answer_contract import red_flag_reply
from tests.red_flag_phrasings import LOOKALIKES, POSITIVES

LOCALES = ("es", "en", "fr")
DATA = Path(__file__).resolve().parents[1] / "adelia" / "enrichment" / "data"


@pytest.mark.parametrize(
    "code,locale,sentence,age,origin",
    POSITIVES,
    ids=[f"{c}-{loc}-{i}" for i, (c, loc, _s, _a, _o) in enumerate(POSITIVES)],
)
def test_a_mother_telling_a_red_flag_gets_the_referral(code, locale, sentence, age, origin):
    flag = detect(sentence, locale=locale, age_months=age)
    got = flag.code if flag else None
    assert got == code, f"[{locale}] {sentence!r} ({origin}) -> {got}"


@pytest.mark.parametrize(
    "locale,sentence,age,why",
    LOOKALIKES,
    ids=[f"{loc}-{i}" for i, (loc, _s, _a, _w) in enumerate(LOOKALIKES)],
)
def test_a_look_alike_does_not_send_her_to_the_emergency_room(locale, sentence, age, why):
    flag = detect(sentence, locale=locale, age_months=age)
    assert flag is None, f"[{locale}] {sentence!r} ({why}) fired {flag}"


def test_every_flag_is_in_the_set_in_every_language():
    for code in PRIORITY:
        for locale in LOCALES:
            n = sum(1 for c, loc, *_ in POSITIVES if c == code and loc == locale)
            assert n >= 1, f"{code} has no {locale!r} phrase in the coverage set"


# --- the set written blind ---------------------------------------------------
#
# tests/fixtures/red_flag_heldout.json was written by an agent that had read
# neither the detector nor the set above (its "_about" keeps the numbers taken
# before its misses were fixed). It stays here so the next widening is held to
# phrasings nobody tuned it on.

_HELDOUT = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "red_flag_heldout.json").read_text("utf-8")
)

#: Two look-alikes the blind set found that fire through patterns older than
#: this sweep: acrocyanosis (cold purple feet, pink lips) through "pies ...
#: morados", and a cough that clears the water through "atragant". Narrowing
#: an existing flag is the context layer's decision, not a night's.
_HELDOUT_FIRING_BEFORE = {
    "Se le ponen los pies un poco morados cuando lleva rato sin calcetines, los labios los tiene "
    "rosas",
    "Se atraganta un poco con el agua del vaso pero tose y se le pasa",
}


@pytest.mark.parametrize("case", _HELDOUT["positives"], ids=lambda c: c["text"][:40])
def test_a_blind_phrasing_gets_the_referral(case):
    flag = detect(case["text"], locale=case["locale"], age_months=case["age_months"])
    assert (flag.code if flag else None) == case["code"], case["text"]


@pytest.mark.parametrize("case", _HELDOUT["lookalikes"], ids=lambda c: c["text"][:40])
def test_a_blind_look_alike_does_not_fire(case):
    flag = detect(case["text"], locale=case["locale"], age_months=case["age_months"])
    if case["text"] in _HELDOUT_FIRING_BEFORE:
        assert flag is not None, "fixed: drop it from _HELDOUT_FIRING_BEFORE"
    else:
        assert flag is None, (case["text"], case["why"], flag)


# --- the head injury and the green or bloody vomit -------------------------


@pytest.mark.parametrize("code", ["head_injury", "green_or_bloody_vomit"])
@pytest.mark.parametrize("locale", LOCALES)
def test_the_new_flags_answer_in_every_language_without_a_dose(code, locale):
    reply = red_flag_reply(code, locale)
    assert "112" in reply
    assert not contains_dosage(reply, locale)


def _titles(filename: str) -> set[str]:
    corpus = json.loads((DATA / filename).read_text(encoding="utf-8"))
    return {s["title"] for s in corpus["sources"]}


def test_a_head_injury_cites_the_seup_sheet_it_comes_from():
    """The SEUP sheet for parents sends repeated vomiting, blood or clear fluid
    from the nose or ears, hard-to-wake and any child under 3 months to the
    emergency department; it lives with the falls in evidence_seguridad.json."""
    flag = detect("se ha dado un golpe en la cabeza y ha vomitado varias veces", age_months=14)
    assert flag is not None and flag.code == "head_injury"
    citation = citation_for(flag)
    assert citation["title"] == "Traumatismo craneal, información para padres (SEUP)"
    assert citation["title"] in _titles("evidence_seguridad.json")


def test_a_green_or_bloody_vomit_cites_the_nhs_page_that_sends_it_to_999():
    flag = detect("ha vomitado algo verde", age_months=5)
    assert flag is not None and flag.code == "green_or_bloody_vomit"
    assert RED_FLAG_SOURCES["green_or_bloody_vomit"]["title"] in _titles(
        "evidence_digestivo_piel.json"
    )


def test_a_head_injury_outranks_the_seizure_it_caused():
    """The parent gets one answer; after a blow the head-injury reason and its
    SEUP source say more than the febrile-seizure protocol would."""
    flag = detect("se dio un golpe en la cabeza y ha convulsionado", age_months=15)
    assert flag is not None and flag.code == "head_injury"


def test_choking_still_comes_first():
    flag = detect("se cayó, se ha atragantado y ha vomitado dos veces", age_months=15)
    assert flag is not None and flag.code == "choking"


def test_any_fall_under_three_months_is_seen():
    """SEUP: go to the emergency department whenever the child is under 3 months."""
    assert detect("se ha caído del sofá", age_months=2) is not None
    assert detect("se ha caído del sofá", age_months=14) is None


def test_a_lump_counts_when_big_under_one_year_or_soft_at_any_age():
    """NHS: under 1 year a large lump, swelling or cut after a knock is 999 or
    A&E; Bambino Gesu: a soft swelling of the skull at any age. A plain
    chichon at 11 months is the battery's golpe-en-la-cabeza turn 2, which
    expects an answer from the sources, not a referral."""
    assert detect("se dio un golpe y le ha salido un chichón muy grande", age_months=8) is not None
    assert detect("se dio un golpe y le ha salido un chichón", age_months=11) is None
    assert detect("se dio un golpe y le ha salido un chichón muy grande", age_months=18) is None
    assert detect("se dio un golpe y le ha salido un bulto blando", age_months=18) is not None


# --- what does not change ---------------------------------------------------


#: A6 asks which signs of dehydration to watch for and has fired since before
#: this set existed (tests/test_golden_orphans.py documents it): the word is
#: the pattern. Narrowing it is the context layer's job, not this sweep's.
_GOLDEN_FIRING_BEFORE = {("A6", "dehydration")}


def test_no_other_golden_question_outside_group_c_fires():
    """Groups A and B are the questions the RAG must answer or refuse; a
    widened pattern that reaches one of them has turned a question into 112."""
    from adelia.clinical.golden import questions

    fired = set()
    for group in ("A", "B"):
        for q in questions(group):
            flag = detect(q.question, locale=q.locale, age_months=q.age_months)
            if flag is not None:
                fired.add((q.id, flag.code))
    assert fired == _GOLDEN_FIRING_BEFORE


def test_no_battery_turn_that_expects_an_answer_fires():
    """The conversation battery's own turns, up to the first referral of each
    scenario, are things mothers said that are not an emergency."""
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "red_flag_coverage.py"
    spec = importlib.util.spec_from_file_location("red_flag_coverage", path)
    coverage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(coverage)
    turns = coverage._battery_quiet_turns()
    assert turns
    fired = [(s, detect(s, locale=loc, age_months=a).code)
             for loc, s, a in turns if detect(s, locale=loc, age_months=a) is not None]
    assert fired == []
