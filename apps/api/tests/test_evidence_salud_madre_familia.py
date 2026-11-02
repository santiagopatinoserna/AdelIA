"""Maternal and family health corpus (0-24 months).

The corpus answered the baby's body and not the parents': a mother asking about the baby blues,
about being exhausted, about a baby who will not stop crying, about going back to work while
breastfeeding or about a jealous older sibling got no evidence or a colic fragment. This file
covers postnatal depression, parental exhaustion, inconsolable crying from the parent's side,
shaken baby prevention, returning to work and siblings, from AEP, AEPap, AAP, NHS, NICE, WHO
and the French bodies. The rules every domain file shares (size, shape, no dose, no named
medicine, nothing another file already holds) live in tests/evidence_corpus_checks.py; this
file pins the domain's own sub-topics.
"""
from __future__ import annotations

import pytest

from tests import evidence_corpus_checks as checks

PATH = checks.DATA_DIR / "evidence_salud_madre_familia.json"
SUBTOPICS = (
    "depresion_posparto",
    "cansancio_extremo",
    "llanto_inconsolable",
    "bebe_sacudido",
    "vuelta_trabajo",
    "hermanos",
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
