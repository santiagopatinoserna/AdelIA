"""The warning-signs query (agent/warning_signs.py, settings.warning_signs_retrieval).

Measured in prod on 2026-11-06 (demo, Claude, 30 real questions): the croup plan
cited AEP, AEPap and SEUP and then wrote "Señales de alarma y cuándo acudir a
urgencias: No tengo evidencia...". The library's croup guides say when to go;
that paragraph was not among the four fragments retrieved. The second search is
the same topic followed by the warning-sign words in the question's language.
"""
from __future__ import annotations

import pytest

from adelia.agent.warning_signs import WARNING_TERMS, warning_query


@pytest.mark.parametrize("locale, terms", [
    ("es", "signos de alarma, cuándo consultar, urgencias"),
    ("en", "warning signs, when to see a doctor, emergency"),
    ("fr", "signes d’alerte, quand consulter, urgences"),
])
def test_the_warning_terms_are_the_agreed_words_in_each_language(locale, terms):
    assert WARNING_TERMS[locale] == terms


def test_the_query_is_the_topic_then_the_warning_terms_on_a_second_line():
    text = "Tiene tos de perro por la noche, ¿qué puedo hacer en casa?"
    assert warning_query(f"  {text}\n", "es") == f"{text}\n{WARNING_TERMS['es']}"


def test_an_unknown_locale_gets_the_spanish_terms_of_the_corpus():
    assert warning_query("tos", "de").endswith(WARNING_TERMS["es"])
    assert warning_query("cough", "en-GB").endswith(WARNING_TERMS["en"])


def test_no_long_dashes_in_the_terms():
    assert all("—" not in t and "–" not in t for t in WARNING_TERMS.values())
