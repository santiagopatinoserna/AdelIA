"""The contract itself: what every answering surface promises a parent."""
from __future__ import annotations

import pytest

from adelia.services.answer_contract import (
    CONTRACTS,
    DEFAULT_LOCALE,
    agent_system_prompt,
    answer_contract,
    chat_system_prompt,
    contract_for,
    no_evidence_reply,
)


LOCALES = ("es", "en", "fr")


def test_every_supported_locale_is_complete():
    assert set(CONTRACTS) == set(LOCALES)
    for locale in LOCALES:
        c = CONTRACTS[locale]
        assert c.language_rule and c.no_info_phrase
        assert c.disclaimer_rule and c.refusal


def test_unknown_locale_falls_back_instead_of_raising():
    assert contract_for("pt") is CONTRACTS[DEFAULT_LOCALE]
    assert no_evidence_reply("pt") == no_evidence_reply(DEFAULT_LOCALE)


@pytest.mark.parametrize("locale", LOCALES)
def test_refusal_sends_the_parent_to_a_pediatrician(locale):
    """A refusal that just says "I don't know" leaves a worried parent with
    nowhere to go. Every language must name the doctor."""
    refusal = no_evidence_reply(locale)
    assert any(
        word in refusal.lower()
        for word in ("pediatra", "pediatrician", "pédiatre")
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_refusal_carries_no_em_dash(locale):
    assert "—" not in no_evidence_reply(locale)


@pytest.mark.parametrize("locale", LOCALES)
def test_contract_forbids_clinical_claims_without_a_citation(locale):
    clauses = answer_contract(locale)
    assert "[ev_1]" in clauses
    assert "NO interpretes ni aconsejes sin respaldo de investigación" in clauses
    assert CONTRACTS[locale].disclaimer_rule in clauses
    assert CONTRACTS[locale].language_rule in clauses


@pytest.mark.parametrize("locale", LOCALES)
def test_both_surfaces_embed_the_same_clauses(locale):
    clauses = answer_contract(locale)
    assert clauses in chat_system_prompt(locale)
    assert clauses in agent_system_prompt(locale)
