"""Injury prevention corpus (0-24 months).

Parents ask about accidents before they happen (silla del coche, piscina, pilas de botón,
pantallas) and right after a minor one (se ha caído del cambiador, ha tocado la plancha), and
the corpus had nothing on either: the urgent-care file covers resuscitation, not the fall or
scald a mother handles at home. This file closes that gap from parent pages of the AEP, AEPap,
SEUP, Ministerio de Sanidad, WHO, AAP and NHS, each chunk keeping its own source's warning
signs and urgency. The rules every domain file shares (size, shape, no dose, no named
medicine, nothing another file already holds) live in tests/evidence_corpus_checks.py; this
file pins the domain's own sub-topics.
"""
from __future__ import annotations

import pytest

from tests import evidence_corpus_checks as checks

PATH = checks.DATA_DIR / "evidence_seguridad.json"
SUBTOPICS = (
    "caidas",
    "quemaduras",
    "intoxicaciones",
    "ahogamiento",
    "atragantamiento_objetos",
    "silla_coche",
    "juguetes",
    "sol_calor",
    "pantallas",
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
    checks.check_no_medicine(_data())


def test_ages_stay_inside_the_first_years():
    checks.check_ages_stay_in_the_first_years(_data())


def test_the_loader_reads_it(monkeypatch):
    checks.check_the_loader_reads_it(PATH, monkeypatch)
