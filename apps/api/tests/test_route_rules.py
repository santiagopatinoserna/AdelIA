"""The deterministic layer of the `route` node (docs/specs/AGENT_GRAPH.md).

Rules are free, instant and testable one by one. They decide only when the
message is unambiguous and return None otherwise, so the model is consulted
for the hard cases and never for the easy ones. The one promise that matters
most: a rule may send a message to the model, but it may never send a mother
who is reporting a symptom or asking for help to `other`.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from adelia.agent.route import RouteDecision, route_by_rules
from adelia.enrichment.profile_service import ProfileFacts

KNOWN_AGE = ProfileFacts(None, "Lucía", None, "F", 6)
NO_AGE = ProfileFacts(None, None, None, None, None)


def test_a_decision_rejects_an_unknown_intent():
    with pytest.raises(ValidationError):
        RouteDecision(intent="chitchat", confidence=0.9, missing=[], via="rule")


def test_a_decision_defaults_to_nothing_missing():
    d = RouteDecision(intent="plan", confidence=1.0, via="rule")
    assert d.missing == []


# --- record: number + unit + past tense, only with an account ----------------


@pytest.mark.parametrize("message", [
    "hoy ha tenido 37,8",
    "ha dormido 3 h seguidas esta noche",
    "se ha tomado 120 ml a las 4",
    "a dormi 3 h cette nuit",
    "had 2 bottles of 150 ml today",
])
def test_a_reported_measurement_with_an_account_is_a_record(message):
    d = route_by_rules(message, locale="es", has_account=True, facts=KNOWN_AGE)
    assert d is not None
    assert d.intent == "record" and d.via == "rule"


def test_the_same_report_without_an_account_is_a_plan():
    """The demo cannot write anything, so there is nothing to record."""
    d = route_by_rules("hoy ha tenido 37,8", locale="es", has_account=False, facts=None)
    assert d is not None and d.intent == "plan"


def test_a_report_that_asks_a_question_is_not_a_record():
    """"ha tenido 37,8, ¿qué hago?" is a worry, not a diary line."""
    d = route_by_rules("ha tenido 37,8 y esta muy llorona que hago", locale="es",
                       has_account=True, facts=KNOWN_AGE)
    assert d is not None and d.intent == "plan"


# --- track: the child's own data, only with an account ----------------------


@pytest.mark.parametrize("message", [
    "en que percentil esta de peso",
    "que vacunas le tocan ahora",
    "que ponia en el ultimo informe del pediatra",
    "como salio la analitica de hierro",
    "what vaccines are due for her",
    "quels vaccins lui restent a faire",
])
def test_a_question_about_her_own_child_data_is_track(message):
    d = route_by_rules(message, locale="es", has_account=True, facts=KNOWN_AGE)
    assert d is not None and d.intent == "track" and d.via == "rule"


def test_without_an_account_there_is_no_record_to_track_so_it_is_a_question():
    d = route_by_rules("que vacunas le tocan ahora", locale="es", has_account=False, facts=None)
    assert d is not None and d.intent == "question"


# --- plan: she wants to know what to do --------------------------------------


@pytest.mark.parametrize("message", [
    "tiene mocos y tose por la noche que hago",
    "lleva tres dias sin hacer caca y me preocupa",
    "no para de llorar por las tardes y no se que hacer",
    "elle a le nez bouche, que faire",
    "she keeps spitting up after every feed, what should I do",
])
def test_a_worry_with_a_request_for_action_is_a_plan(message):
    d = route_by_rules(message, locale="es", has_account=True, facts=KNOWN_AGE)
    assert d is not None and d.intent == "plan" and d.via == "rule"


# --- question: a fact or a short explanation, no symptom to act on -----------


@pytest.mark.parametrize("message", [
    "es normal que regurgite despues de cada toma",
    "a que edad empiezan a gatear",
    "cuando se le puede dar agua",
    "que es la dermatitis del panal",
    "is it normal that she sneezes a lot",
    "a quel age commencent ils a marcher",
])
def test_a_request_for_a_fact_is_a_question(message):
    d = route_by_rules(message, locale="es", has_account=True, facts=KNOWN_AGE)
    assert d is not None and d.intent == "question" and d.via == "rule"


def test_es_normal_que_with_a_worry_is_not_a_bare_question():
    """The rules must not decide; worry plus fact-shape goes to the model."""
    d = route_by_rules("es normal que lleve 3 dias con fiebre? estoy muy preocupada",
                       locale="es", has_account=True, facts=KNOWN_AGE)
    assert d is None or d.intent != "question"


# --- other: out of scope ------------------------------------------------------


@pytest.mark.parametrize("message", [
    "me duele la cabeza desde ayer que me tomo",
    "mi marido tiene fiebre y tos",
    "mi perro vomita desde ayer",
    "que tiempo va a hacer manana en madrid",
    "cuentame un chiste",
])
def test_an_adult_a_pet_the_weather_or_a_joke_is_other(message):
    d = route_by_rules(message, locale="es", has_account=True, facts=KNOWN_AGE)
    assert d is not None and d.intent == "other"


def test_the_mother_mentioning_herself_while_asking_about_the_baby_is_not_other():
    d = route_by_rules("estoy agotada, el bebe no duerme mas de 2 horas seguidas que hago",
                       locale="es", has_account=True, facts=KNOWN_AGE)
    assert d is None or d.intent != "other"


# --- clarify: the age changes the answer and nobody knows it ----------------


@pytest.mark.parametrize("message", [
    "tiene fiebre que hago",
    "cuantos ml tiene que tomar en cada biberon",
    "cuantas horas deberia dormir",
])
def test_age_dependent_questions_without_an_age_ask_for_it(message):
    d = route_by_rules(message, locale="es", has_account=False, facts=None)
    assert d is not None and d.intent == "clarify" and d.missing == ["age"]


# The messages below carry a thermometer reading since build step 3: a fever
# reported WITHOUT one now asks for the reading (tests/test_agent_clarify.py),
# which is a different question from the age these two tests are about.


def test_an_age_in_the_message_is_enough():
    d = route_by_rules("mi bebe de 4 meses tiene 38,5 de fiebre que hago", locale="es",
                       has_account=False, facts=None)
    assert d is not None and d.intent == "plan"


def test_an_age_in_the_profile_is_enough():
    d = route_by_rules("tiene 38,5 de fiebre que hago", locale="es", has_account=True,
                       facts=KNOWN_AGE)
    assert d is not None and d.intent == "plan"


def test_a_record_does_not_need_the_age():
    d = route_by_rules("hoy ha tenido 37,8", locale="es", has_account=True, facts=NO_AGE)
    assert d is not None and d.intent == "record"


def test_the_rules_abstain_when_nothing_matches():
    assert route_by_rules("hola", locale="es", has_account=True, facts=KNOWN_AGE) is None
    assert route_by_rules("   ", locale="es", has_account=True, facts=KNOWN_AGE) is None
