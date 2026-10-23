"""`clarify`: one question, two or three buttons, never twice (AGENT_GRAPH step 3).

Principle 2 of the graph: if an essential fact is missing the graph asks ONE
concrete thing, with the two or three most likely values as buttons, and the
next turn answers with whatever it has. Never two clarifications in a row:
the mother has no time.

Two facts are asked today, because each one changes the answer in the
sources: the age (fever under 3 months is an emergency, NICE NG143 1.2.12;
milk amounts and sleep depend on it) and the thermometer reading when she
says "fiebre" without a number (39 C or more at 3-6 months is an amber
sign in the same guideline).
"""
from __future__ import annotations

import pytest

from adelia.agent import route as r
from adelia.agent.graph import run_graph
from adelia.enrichment.profile_service import ProfileFacts
from adelia.services.answer_contract import CLARIFY_QUESTIONS, clarification_sentence

from tests.test_agent_graph import EVIDENCE, Fakes

AGE_5 = ProfileFacts(None, None, None, None, 5)
NO_AGE = ProfileFacts(None, None, None, None, None)


# --- the rules ----------------------------------------------------------------


def test_fever_without_a_number_asks_for_the_thermometer_reading():
    d = r.route_by_rules("Tiene fiebre, ¿qué hago?", facts=AGE_5)
    assert d is not None and d.intent == "clarify" and d.missing == ["temperature"]


@pytest.mark.parametrize("text", [
    "Tiene 38,4 de fiebre, ¿qué hago?",
    "Tiene fiebre de 39, ¿qué hago?",
    "She has a fever of 38.5, what should I do",
])
def test_fever_with_a_number_is_not_asked_again(text):
    d = r.route_by_rules(text, facts=AGE_5)
    assert d is not None and d.intent != "clarify"


def test_without_an_age_the_age_is_asked_first():
    """One question per turn, and the age comes first: it decides whether
    the same fever is an emergency."""
    d = r.route_by_rules("Tiene fiebre, ¿qué hago?", facts=NO_AGE)
    assert d is not None and d.intent == "clarify" and d.missing == ["age"]


@pytest.mark.parametrize("text", [
    "tiene décimas, le puedo dar algo",
    "está destemplado y no quiere comer",
    "le ha subido la fiebre esta tarde",
    "tiene fiebre desde hace 36 horas, qué hago",
    "she has a fever, what do I do",
    "il a de la fièvre, que faire",
])
def test_a_fever_report_without_a_number_asks_for_it(text):
    d = r.route_by_rules(text, facts=AGE_5)
    assert d is not None and d.intent == "clarify" and d.missing == ["temperature"], d


@pytest.mark.parametrize("text", [
    "¿A partir de cuántos grados se considera fiebre?",
    "¿Qué temperatura es normal en un bebé?",
    "what temperature counts as a fever in a baby",
])
def test_a_question_about_fever_itself_is_not_asked_for_a_reading(text):
    """Nobody's baby has a temperature in these: asking for the thermometer
    reading would be absurd."""
    d = r.route_by_rules(text, facts=AGE_5)
    assert d is None or d.missing != ["temperature"], d


# --- the contract: questions and buttons ----------------------------------------


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
@pytest.mark.parametrize("field", ["age", "temperature"])
def test_each_question_offers_two_or_three_values_and_a_way_out(locale, field):
    q = CLARIFY_QUESTIONS[field][locale]
    assert q["question"].strip() and "—" not in q["question"]
    assert 2 <= len(q["options"]) <= 3
    assert len({o["value"] for o in q["options"]}) == len(q["options"])
    assert q["skip"]["value"] == "unknown" and q["skip"]["label"].strip()
    for option in q["options"]:
        assert option["label"].strip() and "—" not in option["label"]


@pytest.mark.parametrize("value, expected", [
    ("37.5-37.9", 37.9), ("38-38.9", 38.9), ("39+", 39.0),
])
def test_a_temperature_answer_reads_as_a_temperature_to_the_guard(value, expected):
    from adelia.clinical.red_flags import temperature_in

    sentence = clarification_sentence("temperature", value, "es")
    assert temperature_in(sentence) == expected


def test_an_unknown_value_is_said_in_words_not_as_a_number():
    from adelia.clinical.red_flags import temperature_in

    sentence = clarification_sentence("temperature", "unknown", "es")
    assert sentence and temperature_in(sentence) is None


def test_an_invalid_value_is_refused():
    assert clarification_sentence("temperature", "45", "es") is None
    assert clarification_sentence("weight", "7", "es") is None


# --- the graph ------------------------------------------------------------------


def _real_route(fakes: Fakes):
    """The real `route` (rules; the model layer is off in tests), recorded."""
    async def _route(message, **kwargs):
        fakes.calls.append(("route", message, kwargs))
        return await r.route(message, **kwargs)
    return _route


async def _run(fakes, message, *, facts=AGE_5, clarification=None, account=False, **deps):
    state = {"surface": "demo", "locale": "es", "message": message, "account": account,
             "facts": facts}
    if clarification is not None:
        state["clarification"] = clarification
    return await run_graph(state, fakes.deps(**{"route": _real_route(fakes), **deps}))


async def test_turn_one_asks_one_question_with_buttons_and_spends_nothing_else():
    fakes = Fakes()
    out = await _run(fakes, "Tiene fiebre, ¿qué hago?")
    assert out["kind"] == "clarify" and out["intent"] == "clarify"
    clarify = out["clarify"]
    assert clarify["field"] == "temperature"
    assert clarify == {"field": "temperature", **CLARIFY_QUESTIONS["temperature"]["es"]}
    assert out["answer"] == clarify["question"]
    assert out["evidence_citations"] == []
    assert "embed" not in fakes.names() and "generate" not in fakes.names()


async def test_turn_two_answers_with_the_reading():
    fakes = Fakes()
    out = await _run(fakes, "Tiene fiebre, ¿qué hago?",
                     clarification={"field": "temperature", "value": "38-38.9"})
    assert out["kind"] == "answer" and out["intent"] == "plan"
    (_, message, _), = [c for c in fakes.calls if c[0] == "route"]
    assert "38 a 38,9" in message
    (_, _, user), = [c for c in fakes.calls if c[0] == "generate"]
    assert "Tiene fiebre, ¿qué hago?" in user and "38 a 38,9" in user


async def test_turn_two_answers_even_when_the_fact_is_still_missing():
    """The test the spec asks for: she did not measure, the rules would ask
    again, and the graph answers with what there is and says what would
    change the answer."""
    fakes = Fakes()
    out = await _run(fakes, "Tiene fiebre, ¿qué hago?",
                     clarification={"field": "temperature", "value": "unknown"})
    assert out["kind"] == "answer", "never two clarifications in a row"
    assert out["intent"] == "plan"
    assert out["missing"] == ["temperature"]
    (_, _, user), = [c for c in fakes.calls if c[0] == "generate"]
    assert "no la he medido" in user.lower()
    assert "qué cambiaría" in user


async def test_turn_two_answers_even_if_the_model_asks_to_clarify_again():
    fakes = Fakes(intent="clarify")
    fakes.decision = fakes.decision.model_copy(update={"missing": ["temperature"]})
    out = await _run(fakes, "Tiene fiebre, ¿qué hago?", route=fakes.route,
                     clarification={"field": "temperature", "value": "unknown"})
    assert out["kind"] == "answer" and out["intent"] == "plan"


async def test_a_clarify_with_nothing_we_can_ask_answers_instead():
    """The model may say "clarify" with a fact we have no buttons for, or
    with low confidence and nothing named: answer with the plan."""
    fakes = Fakes(intent="clarify")
    fakes.decision = fakes.decision.model_copy(update={"missing": ["symptom"]})
    out = await _run(fakes, "le pasa algo pero no sé qué es", route=fakes.route)
    assert out["kind"] == "answer" and out["intent"] == "plan"


async def test_an_age_band_reaches_the_guard_at_its_youngest():
    """"Menos de 3 meses" plus fever is the NG143 emergency: the band's lower
    bound is the age the guard sees, so the answer to the question can only
    make the guard stricter."""
    fakes = Fakes()
    out = await _run(fakes, "Tiene fiebre, ¿qué hago?", facts=NO_AGE,
                     clarification={"field": "age", "value": "0-2"})
    assert out["kind"] == "red_flag"
    assert fakes.calls == []


async def test_a_known_age_is_not_overwritten_by_an_age_answer():
    fakes = Fakes()
    out = await _run(fakes, "¿Cuántas tomas tiene que hacer al día?", facts=AGE_5,
                     clarification={"field": "age", "value": "0-2"})
    assert out["kind"] == "answer"
    (_, _, kwargs), = [c for c in fakes.calls if c[0] == "route"]
    assert kwargs["facts"].age_months == 5


async def test_an_invalid_answer_is_ignored_but_still_counts_as_the_one_question():
    fakes = Fakes()
    out = await _run(fakes, "Tiene fiebre, ¿qué hago?",
                     clarification={"field": "temperature", "value": "45"})
    assert out["kind"] == "answer"
    (_, message, _), = [c for c in fakes.calls if c[0] == "route"]
    assert message == "Tiene fiebre, ¿qué hago?"


async def test_clarify_keeps_the_evidence_fakes_untouched():
    """Sanity: a clarify run never retrieves, so the evidence default is not read."""
    fakes = Fakes(evidence=[EVIDENCE])
    await _run(fakes, "Tiene fiebre, ¿qué hago?")
    assert "evidence" not in fakes.names()
