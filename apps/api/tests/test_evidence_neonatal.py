"""Neonatal corpus (0-24 months).

The first weeks at home bring the questions parents ask most and the corpus
answered least: two jaundice pages and nothing on the cord stump, the heel prick,
the hearing screen, the weight a newborn loses or the colour of meconium. This
file covers those seven sub-topics from AEP, AEPap, SEUP, Ministerio de Sanidad,
NHS, HealthyChildren and French family pages, and every jaundice chunk names the
age it holds for, so a question about an older baby does not borrow it. The rules
every domain file shares (size, shape, no dose, no named medicine, nothing another
file already holds) live in tests/evidence_corpus_checks.py; this file pins the
domain's own sub-topics.
"""
from __future__ import annotations

import re

import pytest

from tests import evidence_corpus_checks as checks

PATH = checks.DATA_DIR / "evidence_neonatal.json"
SUBTOPICS = (
    "primeras_semanas",
    "cordon_umbilical",
    "ictericia_neonatal",
    "prueba_talon",
    "cribado_auditivo",
    "perdida_peso_inicial",
    "deposiciones_recien_nacido",
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


def test_every_jaundice_chunk_says_the_age_it_holds_for():
    """Golden B8 asks about a yellow 4-month-old in the words of these chunks.
    A jaundice chunk without its age band reads as if it held for any baby, so
    each one names the hours, days or weeks of life it is about, in its own text
    and not only in the page title it opens with."""
    age = re.compile(
        r"\d+\s*(?:horas|días|semanas|meses)|recién nacido|primer[ao]s? (?:día|semana)", re.I
    )
    for source, i, chunk in checks.chunks(_data()):
        body = chunk.split("Tema:", 1)[-1]
        if "ictericia_neonatal" in source["topics"] and re.search(r"ictericia", body, re.I):
            assert age.search(body), f"{source['title'][:50]} #{i} gives no age"


def test_the_loader_reads_it(monkeypatch):
    checks.check_the_loader_reads_it(PATH, monkeypatch)
