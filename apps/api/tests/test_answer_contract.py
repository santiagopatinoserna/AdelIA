"""The contract itself: what every answering surface promises a parent."""
from __future__ import annotations

import pytest

from adelia.services.answer_contract import (
    CONTRACTS,
    DEFAULT_LOCALE,
    RED_FLAG_REASONS,
    agent_system_prompt,
    answer_contract,
    chat_system_prompt,
    contract_for,
    emergency_number,
    interface_disclaimer,
    no_evidence_reply,
    red_flag_reply,
)
from adelia.clinical.red_flags import PRIORITY


LOCALES = ("es", "en", "fr")


def test_every_supported_locale_is_complete():
    assert set(CONTRACTS) == set(LOCALES)
    for locale in LOCALES:
        c = CONTRACTS[locale]
        assert c.language_rule and c.no_info_phrase
        assert c.disclaimer and c.refusal


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
    assert CONTRACTS[locale].language_rule in clauses


@pytest.mark.parametrize("locale", LOCALES)
def test_both_surfaces_embed_the_same_clauses(locale):
    clauses = answer_contract(locale)
    assert clauses in chat_system_prompt(locale)
    assert clauses in agent_system_prompt(locale)


# ---------------------------------------------------------------------------
# The disclaimer moved from the prompt to the interface (audit 3.8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_prompt_no_longer_asks_the_model_for_a_disclaimer(locale):
    """It appeared only when the model chose to obey, never on a refusal and
    never on the agent canvas. The interface paints it now, always."""
    clauses = answer_contract(locale)
    assert "Termina con" not in clauses
    assert "End with" not in clauses
    assert "Termine par" not in clauses
    assert interface_disclaimer(locale) not in clauses


@pytest.mark.parametrize("locale", LOCALES)
def test_the_interface_disclaimer_names_the_doctor_and_carries_no_em_dash(locale):
    text = interface_disclaimer(locale)
    assert any(w in text.lower() for w in ("pediatra", "pediatrician", "pédiatre"))
    assert "—" not in text


# ---------------------------------------------------------------------------
# Red-flag wording (audit 3.3)
# ---------------------------------------------------------------------------


def test_every_red_flag_code_has_wording_in_every_language():
    assert set(RED_FLAG_REASONS) == set(PRIORITY)
    for code, per_locale in RED_FLAG_REASONS.items():
        assert set(per_locale) == set(LOCALES), code


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("code", PRIORITY)
def test_red_flag_reply_dials_the_emergency_number_and_names_no_drug(code, locale):
    reply = red_flag_reply(code, locale)
    assert "112" in reply
    # The question that makes the detector necessary is "do I give her
    # paracetamol?". The answer must not contain a dose, in any shape.
    lowered = reply.lower()
    for forbidden in ("mg/kg", "mg /kg", " ml/kg", "paracetamol", "ibuprofeno", "ibuprofen"):
        assert forbidden not in lowered, f"{code}/{locale} names a drug or a dose"
    assert "—" not in reply


@pytest.mark.parametrize("code", PRIORITY)
def test_red_flag_french_keeps_its_non_breaking_spaces(code):
    """French of France: U+00A0 before : ; ? !"""
    import re

    reply = red_flag_reply(code, "fr")
    for match in re.finditer(r"(.)([:;?!])", reply):
        before = match.group(1)
        assert before == "\u00a0", f"{code}: missing non-breaking space before {match.group(2)!r}"


def test_emergency_number_is_112_in_both_countries_and_falls_back():
    assert emergency_number("ES") == "112"
    assert emergency_number("FR") == "112"
    assert emergency_number(None, "es") == "112"
    assert emergency_number("XX", "de") == "112"


def test_unknown_red_flag_code_raises_instead_of_answering_generically():
    with pytest.raises(KeyError):
        red_flag_reply("not_a_flag", "es")
