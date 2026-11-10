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


# --- her shorthand, a vague worry, the fallback (battery, 2026-11-11) ---------------
#
# The conversation battery found the rules did not read how a mother in a hurry
# writes: «q hago» was not «qué hago», so «ha vomitado 3 veces esta mañana q hago»
# became a diary line to note. Common Spanish chat shorthand is read as the word.

from adelia.agent.route import fallback_intent  # noqa: E402


@pytest.mark.parametrize("message", [
    "ha vomitado 3 veces esta mañana q hago",
    "y q hago si sube mas",
    "ke hago le ha subido a 38,6",
])
def test_q_hago_is_que_hago(message):
    d = route_by_rules(message, has_account=True, facts=KNOWN_AGE)
    assert d is not None and d.intent == "plan"


@pytest.mark.parametrize("message", [
    "es normal q tenga fiebre despues de la vacuna",
    "xq se despierta tanto por la noche",
    "pq no quiere el biberon",
    "cuanto tiene que dormir de dia a esta edad",
    "cuanto deberia comer a esta edad",
    "se despierta 4 veces es normal",
    "is that normal",
])
def test_a_fact_or_a_why_in_her_shorthand_is_a_question(message):
    d = route_by_rules(message, has_account=True, facts=KNOWN_AGE)
    assert d is not None and d.intent == "question"


def test_porque_inside_a_statement_is_not_a_why_question():
    d = route_by_rules("no come xq le duelen los dientes", has_account=True, facts=KNOWN_AGE)
    assert d is None or d.intent != "question"


def test_shorthand_is_read_only_as_a_whole_word():
    d = route_by_rules("ha tomado 120 ml de leche de vaca", has_account=True, facts=KNOWN_AGE)
    assert d is not None and d.intent == "record"


@pytest.mark.parametrize("message", [
    "le pasa algo raro",
    "no sé qué le pasa",
    "no se q le pasa a mi bebe",
    "something is wrong with her",
    "je ne sais pas ce qu'il a",
])
def test_something_is_wrong_with_no_symptom_asks_how_he_is(message):
    """AGENT_GRAPH.md, `clarify`: «le pasa algo» sin síntoma. The battery's «le pasa
    algo raro» was searched, found nothing and refused."""
    d = route_by_rules(message, has_account=True, facts=KNOWN_AGE)
    assert d is not None and d.intent == "clarify"
    assert d.missing == ["symptom"]


def test_something_is_wrong_with_a_symptom_is_not_the_vague_question():
    d = route_by_rules("no se que le pasa, tiene mocos y tose mucho desde hace 3 dias",
                       has_account=True, facts=KNOWN_AGE)
    assert d is not None and d.intent == "plan"


@pytest.mark.parametrize("message", [
    "is it ok to give him water", "can she sleep on her tummy",
    "se puede dar agua a un bebe", "cuantas cucharadas de cereales",
    "est-ce qu'il peut manger du fromage",
])
def test_with_the_classifier_down_a_plain_question_takes_the_short_answer(message):
    assert fallback_intent(message) == "question"


@pytest.mark.parametrize("message", [
    "tiene mocos desde ayer", "hola, una cosa", "le puedo dar paracetamol?",
    "is it ok that he cries so much", "llora mucho y no se que hacer",
])
def test_with_the_classifier_down_anything_else_takes_the_plan(message):
    """Decision 1 of AGENT_GRAPH.md: what nobody could place gets the path with
    the most safeguards. Only a plain question with no symptom, worry or drug is
    a short answer."""
    assert fallback_intent(message) == "plan"


def test_night_wakings_depend_on_the_age_so_without_it_she_is_asked():
    """tests/data/routing_es.json: «se despierta mucho por la noche es normal» with
    no age is `clarify`. Reading «es normal» at the end must not answer it blind."""
    d = route_by_rules("se despierta mucho por la noche es normal", facts=NO_AGE)
    assert d is not None and d.intent == "clarify" and d.missing == ["age"]
    d = route_by_rules("se despierta mucho por la noche es normal", facts=KNOWN_AGE)
    assert d is not None and d.intent == "question"


@pytest.mark.parametrize("message", ["no tiene fiebre", "sin fiebre pero vomita",
                                     "she doesn't have a fever", "il n'a pas de fièvre"])
def test_saying_there_is_no_fever_is_not_asked_for_the_thermometer(message):
    """«no tiene fiebre» after vomiting (the battery) was asked «¿Cuánto ha marcado el
    termómetro?»: the fever-report rule read the fever and not the «no»."""
    d = route_by_rules(message, has_account=True, facts=KNOWN_AGE)
    assert d is None or d.missing != ["temperature"]


@pytest.mark.parametrize("message", ["hoy pesa 8,4 kg", "ya mide 72 cm", "pesa 9 kilos",
                                     "she weighs 7.2 kg", "il pèse 8 kg"])
def test_a_weight_or_a_length_in_the_present_is_a_diary_line(message):
    d = route_by_rules(message, has_account=True, facts=KNOWN_AGE)
    assert d is not None and d.intent == "record"


@pytest.mark.parametrize("message", ["cuanto pesa un bebe de 9 meses",
                                     "pesa 8,4 kg es normal?"])
def test_a_question_about_weight_is_not_a_diary_line(message):
    d = route_by_rules(message, has_account=True, facts=KNOWN_AGE)
    assert d is None or d.intent != "record"


def test_drops_are_a_medicine_for_the_fallback():
    assert fallback_intent("le puedo dar gotas para los gases") == "plan"


@pytest.mark.parametrize("message", ["cuanto apiretal le doy pesa 9 kilos",
                                     "how much tylenol can i give she weighs 7 kg"])
def test_a_dose_question_with_the_weight_in_it_is_never_a_diary_line(message):
    d = route_by_rules(message, has_account=True, facts=KNOWN_AGE)
    assert d is None or d.intent != "record"


def test_vitamin_k_is_not_shorthand():
    from adelia.agent.route import read_shorthand

    assert read_shorthand("le pusieron la vitamina k al nacer") == (
        "le pusieron la vitamina k al nacer")
