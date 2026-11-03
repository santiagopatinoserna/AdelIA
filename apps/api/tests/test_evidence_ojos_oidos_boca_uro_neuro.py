"""Eyes, ears, mouth, genital and head-shape corpus (0-24 months).

The coverage audit found the questions parents bring to the first check-ups with
nothing to cite: a squint in the first months, a sticky eye from a blocked tear
duct, whether a baby hears well after the newborn screening, first brushing and
bottle caries, a tight foreskin, an undescended testicle, umbilical and inguinal
hernias, a flat head and a head that always turns to one side. The sources are
parent pages of AEP, AEPap, AAP, NHS, NICE, ameli.fr, mpedia.fr and HAS,
paraphrased in Spanish. The rules every domain file shares (size, shape, no dose,
no named medicine, nothing another file already holds) live in
tests/evidence_corpus_checks.py; this file pins the domain's own sub-topics.
"""
from __future__ import annotations

import pytest

from tests import evidence_corpus_checks as checks

PATH = checks.DATA_DIR / "evidence_ojos_oidos_boca_uro_neuro.json"
SUBTOPICS = (
    "estrabismo",
    "lagrimal_obstruido",
    "audicion",
    "caries_fluor",
    "fimosis",
    "testiculo_no_descendido",
    "hernias",
    "plagiocefalia",
    "torticolis",
)


def _data() -> dict:
    return checks.load(PATH)


def test_the_file_exists_and_has_meta():
    checks.check_meta(_data())


def test_between_30_and_40_sources():
    checks.check_size(_data())


def test_sources_have_the_shape_the_loader_and_cards_need():
    checks.check_source_shape(_data(), SUBTOPICS)


def test_no_title_or_url_is_already_in_another_file():
    checks.check_disjoint_from_other_files(PATH)


@pytest.mark.parametrize("topic", SUBTOPICS)
def test_every_subtopic_has_at_least_two_sources(topic):
    checks.check_subtopic(_data(), topic)


def test_chunks_are_sized_attributed_and_spanish():
    checks.check_chunks_are_sized_attributed_and_spanish(_data())


def test_no_chunk_carries_a_dose():
    checks.check_no_dose(_data())


def test_no_chunk_names_a_medicine_or_remedy_except_to_warn():
    # Fluoride toothpaste is this domain's subject (how much paste, which
    # concentration, from which tooth), so "flúor" is lifted here and only
    # here. The golden near miss B14 asks for a fluoride DOSE for an
    # 11-month-old; no chunk gives one (no mg, no supplement), so that half of
    # the question must still go unanswered, which the measurement checks.
    checks.check_no_medicine(_data(), allow_near_miss=frozenset({"flúor"}))


def test_ages_stay_inside_the_first_years():
    checks.check_ages_stay_in_the_first_years(_data())


def test_the_loader_reads_it(monkeypatch):
    checks.check_the_loader_reads_it(PATH, monkeypatch)
