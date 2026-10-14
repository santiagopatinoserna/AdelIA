"""The lexical plan: when a retrieval call goes hybrid, and what it sends.

Pure, always runs. The properties that matter are the negative ones: the flag
being off, or anything unsupported, yields NO plan, because "no plan" is what
keeps retrieval on the exact path it had before hybrid existed. The SQL-level
version of the same claim is in tests/test_hybrid_retrieval.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from adelia.config import Settings, settings
from adelia.services.lexical import (
    MAX_QUERY_TERMS,
    TS_CONFIG_BY_LANGUAGE,
    or_tsquery_text,
    plan_lexical,
    supported_language,
)


def test_the_hybrid_flag_defaults_to_false():
    """Tonight's commit must not change production. The default flips only
    after the eval harness says the fused order is better."""
    assert Settings.model_fields["retrieval_hybrid_enabled"].default is False


@pytest.fixture
def hybrid_on(monkeypatch):
    monkeypatch.setattr(settings, "retrieval_hybrid_enabled", True)


@pytest.fixture
def hybrid_off(monkeypatch):
    monkeypatch.setattr(settings, "retrieval_hybrid_enabled", False)


def test_flag_off_means_no_plan_whatever_else_is_supplied(hybrid_off):
    assert plan_lexical("fiebre en el bebé", "es") is None


def test_flag_on_with_a_supported_question_makes_a_plan(hybrid_on):
    plan = plan_lexical("fiebre en el bebé", "es")
    assert plan is not None
    assert plan.language == "es"
    assert plan.ts_config == "spanish"
    assert "'fiebre'" in plan.tsquery


@pytest.mark.parametrize(
    ("locale", "language", "config"),
    [("es", "es", "spanish"), ("en", "en", "english"), ("fr", "fr", "french"),
     ("es-ES", "es", "spanish"), ("FR_ca", "fr", "french"), (" en ", "en", "english")],
)
def test_locales_map_to_their_own_configuration(hybrid_on, locale, language, config):
    plan = plan_lexical("fever", locale)
    assert plan is not None
    assert (plan.language, plan.ts_config) == (language, config)


@pytest.mark.parametrize("locale", [None, "", "pt", "de", "xx-YY"])
def test_an_unsupported_locale_means_no_plan_not_a_guess(hybrid_on, locale):
    assert plan_lexical("fever", locale) is None


@pytest.mark.parametrize("question", [None, "", "   ", "?!¿", "a b c"])
def test_a_question_with_no_usable_term_means_no_plan(hybrid_on, question):
    assert plan_lexical(question, "es") is None


def test_supported_language_is_closed_over_the_corpus_languages():
    assert set(TS_CONFIG_BY_LANGUAGE) == {"es", "en", "fr"}
    assert supported_language("ES") == "es"
    assert supported_language("it") is None


def test_the_migration_and_the_mapping_agree_on_configuration_names():
    """The generated columns hard-code these three names. A fourth language
    added to the mapping without a migration would parse queries under a
    configuration no row was indexed with."""
    # Read by path: `alembic.versions` would resolve to the installed alembic
    # package, not this repo's migrations directory.
    migration = (
        Path(__file__).resolve().parent.parent
        / "alembic" / "versions" / "0021_hybrid_retrieval_fts.py"
    )
    source = migration.read_text(encoding="utf-8")
    for config in TS_CONFIG_BY_LANGUAGE.values():
        assert f"'{config}'::regconfig" in source


def test_terms_are_or_ed_lowercased_and_deduplicated():
    assert or_tsquery_text("Fiebre fiebre BEBÉ") == "'fiebre' | 'bebé'"


def test_one_character_terms_are_dropped():
    assert or_tsquery_text("a 8 meses") == "'meses'"


def test_unicode_words_survive():
    assert or_tsquery_text("hémoglobine niño") == "'hémoglobine' | 'niño'"


def test_the_term_count_is_bounded():
    question = " ".join(f"term{i}" for i in range(MAX_QUERY_TERMS * 3))
    assert or_tsquery_text(question).count("|") == MAX_QUERY_TERMS - 1


@pytest.mark.parametrize(
    "hostile",
    ["x' | 'y", "a'); DROP TABLE chunks; --", "foo & !bar", "x\\y", "(a | b) <-> c", "a:*b"],
)
def test_no_term_can_carry_a_quote_a_backslash_or_a_tsquery_operator(hostile):
    """to_tsquery would read these as syntax. Every term is a bare run of word
    characters between single quotes, so none can."""
    text = or_tsquery_text(hostile)
    if text is None:
        return
    for term in text.split(" | "):
        assert term.startswith("'") and term.endswith("'")
        body = term[1:-1]
        assert body and all(ch.isalnum() or ch == "_" for ch in body), term
