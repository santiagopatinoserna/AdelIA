"""Infections and fever corpus (0-24 months).

Fever is the commonest reason a parent opens the chat, and before this file the corpus held it
only as clinical guidelines written for professionals (NICE NG143, CG84 and the AEP febrile
seizure protocol, in the urgent-care file). This one adds the parent-facing pages of the AEP,
AEPap, SEUP, NHS, HealthyChildren and the French bodies on fever, gastroenteritis, chickenpox,
roseola, hand, foot and mouth disease, conjunctivitis, urinary infection and febrile seizure,
with each warning sign at the urgency its own source gives. The rules every domain file shares
(size, shape, no dose, no named medicine, nothing another file already holds) live in
tests/evidence_corpus_checks.py; this file pins the domain's own sub-topics.
"""
from __future__ import annotations

import pytest

from tests import evidence_corpus_checks as checks

PATH = checks.DATA_DIR / "evidence_infecciones_fiebre.json"
SUBTOPICS = (
    "fiebre",
    "gastroenteritis",
    "varicela",
    "roseola",
    "mano_pie_boca",
    "conjuntivitis",
    "infeccion_orina",
    "convulsion_febril",
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
