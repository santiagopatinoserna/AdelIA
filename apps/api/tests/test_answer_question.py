"""A question gets an answer, not a plan (AGENT_GRAPH, build step 2).

"¿Es normal que regurgite?" or "¿a qué edad gatean?" asks for a fact. Until
the graph, every question got the four-section action plan, which buries a
one-line answer under "Hoy / Vigila / Cuándo ir al médico / No olvides".
The `question` variant of the contract asks for one sentence that answers
and at most three cited bullets, with no plan headings. What it may not cut
is safety: a warning sign the sources tie to the question still has to be
said, with the urgency the source gives it. That is the lesson of the
night/brevity branch, which shortened answers by 45 % and lost an alarm
sign in 1 of 9 questions.
"""
import pytest

from adelia.services.answer_contract import (
    CONTRACTS,
    PLAN_HEADINGS,
    answer_contract,
    chat_system_prompt,
)

LOCALES = ["es", "en", "fr"]


@pytest.mark.parametrize("locale", LOCALES)
def test_the_plan_prompt_is_unchanged_by_the_question_variant(locale):
    """Default shape is the plan, and it is the very text it was before."""
    assert chat_system_prompt(locale) == chat_system_prompt(locale, shape="plan")
    assert CONTRACTS[locale].language_rule in answer_contract(locale)


@pytest.mark.parametrize("locale", LOCALES)
def test_the_question_prompt_asks_for_no_plan_section(locale):
    prompt = chat_system_prompt(locale, shape="question")
    for heading in PLAN_HEADINGS[locale].values():
        # Named only to forbid them, never as an instruction to write one.
        assert f"\"## {heading}\" (" not in prompt
    assert CONTRACTS[locale].language_rule not in prompt


@pytest.mark.parametrize("locale, required", [
    ("es", ("una frase", "hasta 3 viñetas", "cada una con su cita", "ningún encabezado")),
    ("en", ("one sentence", "up to 3 bullets", "each with its citation", "no headings")),
    ("fr", ("une phrase", "jusqu’à 3 puces", "chacune avec sa citation", "aucun titre")),
])
def test_the_question_prompt_asks_for_one_sentence_and_three_cited_bullets(locale, required):
    prompt = chat_system_prompt(locale, shape="question").lower()
    for clause in required:
        assert clause in prompt, clause


@pytest.mark.parametrize("locale, required", [
    ("es", ("señal de alarma", "urgencia que indica la fuente", "nunca se recorta")),
    ("en", ("warning sign", "urgency the source states", "never cut")),
    ("fr", ("signe d’alerte", "urgence indiquée par la source", "jamais sacrifiée")),
])
def test_brevity_never_drops_a_warning_sign(locale, required):
    prompt = chat_system_prompt(locale, shape="question").lower()
    for clause in required:
        assert clause in prompt, clause


@pytest.mark.parametrize("locale", LOCALES)
def test_the_question_prompt_keeps_the_shared_clinical_clauses(locale):
    """Citation obligation, the exact refusal, no invented data: same as the plan."""
    prompt = chat_system_prompt(locale, shape="question")
    assert "[ev_1]" in prompt
    assert CONTRACTS[locale].refusal in prompt
    assert "NUNCA inventes datos médicos" in prompt
    assert "Clinical evidence" in prompt


@pytest.mark.parametrize("locale", LOCALES)
def test_the_question_rule_follows_the_house_typography(locale):
    prompt = chat_system_prompt(locale, shape="question")
    assert "—" not in prompt


def test_an_unknown_shape_is_an_error_not_a_silent_plan():
    with pytest.raises(ValueError):
        chat_system_prompt("es", shape="poem")
