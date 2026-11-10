"""The conversation state of a turn (agent/conversation.py), without a model.

Santiago tried the /dashboard agent in production on 2026-11-09 and wrote
"no está bien coordinado, es tonto; cuando sigues la conversación no sigue
bien; si tiene dudas no hace preguntas". His two real conversations are the
fixtures below, cut as he sent them. What failed, and what is pinned here:

  1. the router saw one message at a time, so a follow-up ("Pero todos los
     días está así"), a correction ("No es enfermo") and a new topic all
     looked alike;
  2. a follow-up was searched with AdelIA's own last answer glued in front,
     so the "niño enfermo" frame of the first answer came back every turn;
  3. a fever noted 15 minutes earlier rode into an unrelated question;
  4. with essentials missing it never asked;
  5. without evidence it said the same sentence every turn.

Everything here is rules: the same inputs give the same turn on every run,
and none of it needs a key.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from adelia.agent import conversation as conv
from adelia.enrichment.profile_service import ProfileFacts
from adelia.services.answer_contract import CLARIFY_QUESTIONS, no_evidence_reply

AGE_14 = ProfileFacts(None, "Leo", None, "M", 14)
NO_AGE = ProfileFacts(None, None, None, None, None)

# --- the two real conversations of 2026-11-09 ----------------------------------

GUARDERIA = (
    "Mi bebé en la guardería es el único que en tiempo libre se queda sentado en una "
    "esquina sin moverse. Todos los otros juegan pero él no se mueve. Pero en casa no "
    "es así, en casa juega"
)
SICK_FRAME = (
    "No puedo explicarte con mis fuentes por qué se queda quieto en la guardería y en "
    "casa sí juega.\n\n## Vigila\n- Falta de juego + mala noche + rechazo de la comida = "
    "no está bien, que se quede en casa [ev_1].\n\n## Cuándo ir al médico\n- Si tiene "
    "fiebre o le cuesta respirar [ev_2]."
)
CONV1 = [
    {"role": "user", "content": GUARDERIA},
    {"role": "assistant", "content": SICK_FRAME},
    {"role": "user", "content": "Pero todos los días está así"},
    {"role": "assistant", "content": SICK_FRAME},
]

FEVER_NOTE = "Tiene 38.7. Seguimos su temp"
NOTED = "Anotado: 38,7 °C, hoy a las 10:57."
FEVER_MIXED = (
    "Hoy has anotado 38,7 °C, y eso sí tiene una pauta clara: ofrécele líquidos y vigila "
    "cómo está [ev_1].\n\n## Cuándo ir al médico\n- Si la fiebre dura más de 3 días [ev_1]."
)
CONV2 = [
    {"role": "user", "content": FEVER_NOTE},
    {"role": "assistant", "content": NOTED},
    {"role": "user", "content": GUARDERIA},
    {"role": "assistant", "content": FEVER_MIXED},
]

ASKED = (
    CLARIFY_QUESTIONS["nursery_time"]["es"]["question"] + "\n"
    + CLARIFY_QUESTIONS["social_signals"]["es"]["question"]
)


def _u(text: str) -> dict:
    return {"role": "user", "content": text}


def _a(text: str) -> dict:
    return {"role": "assistant", "content": text}


# --- A. the kind of turn ------------------------------------------------------------


def test_a_first_message_is_a_new_topic_searched_as_she_wrote_it():
    c = conv.read(GUARDERIA, [])
    assert c.kind == "new" and c.via == "first"
    assert c.search_query == GUARDERIA
    assert c.model_history == [] and c.topic == ()


def test_pero_todos_los_dias_esta_asi_follows_the_topic():
    c = conv.read("Pero todos los días está así", CONV1[:2])
    assert c.kind == "follow_up" and c.via == "rule"
    assert c.topic == (GUARDERIA,)


def test_no_es_enfermo_is_a_correction_that_retracts_the_sick_frame():
    c = conv.read("No es enfermo", CONV1)
    assert c.kind == "correction" and c.via == "rule"
    assert c.retracted == ("enfermo",)
    assert c.topic == (GUARDERIA, "Pero todos los días está así")


def test_a_correction_drops_every_answer_built_on_the_wrong_frame():
    c = conv.read("No es enfermo", CONV1)
    assert c.model_history == []
    assert "enfermo" not in c.search_query.lower()
    assert "quede en casa" not in c.search_query


def test_the_guarderia_question_after_noting_a_fever_is_a_new_topic():
    c = conv.read(GUARDERIA, CONV2[:2])
    assert c.kind == "new" and c.via == "rule"
    assert c.model_history == []
    assert c.search_query == GUARDERIA


def test_es_tema_nuevo_no_tiene_fiebre_corrects_the_mixed_answer():
    """"Es tema nuevo" here says the LAST question was a new topic: nothing of
    her own follows it, so it corrects, and the fever is what it takes back."""
    c = conv.read("Es tema nuevo. No tiene fiebre ninads", CONV2)
    assert c.kind == "correction"
    assert "fiebre" in c.retracted
    assert c.topic == (GUARDERIA,)
    assert c.model_history == []
    for leaked in ("38", "fiebre", "temp", "Anotado"):
        assert leaked not in c.search_query, leaked


def test_a_new_topic_marker_with_a_question_of_its_own_opens_a_new_topic():
    c = conv.read("Otra cosa: ¿cuándo puede empezar a comer fresas?", CONV2)
    assert c.kind == "new"
    assert c.model_history == []
    assert c.search_query == "Otra cosa: ¿cuándo puede empezar a comer fresas?"


def test_y_por_la_noche_after_a_sleep_question_is_a_follow_up_searched_with_it():
    sleep = "¿Cuántas siestas tiene que hacer un bebé de 8 meses?"
    history = [_u(sleep), _a("A los 8 meses suelen hacer 2 siestas [ev_1].")]
    c = conv.read("¿y por la noche?", history)
    assert c.kind == "follow_up"
    assert c.search_query == f"{sleep}\n¿y por la noche?"
    assert c.model_history == history


def test_an_age_correction_retracts_the_answer_given_for_the_wrong_age():
    milk = "¿Cuánta leche tiene que tomar al día?"
    history = [_u(milk), _a("A los 6 meses, unos 500 a 600 ml al día [ev_1].")]
    c = conv.read("Perdona, tiene 9 meses, no 6", history)
    assert c.kind == "correction"
    assert c.model_history == []
    assert milk in c.search_query and "9 meses" in c.search_query


def test_a_long_self_contained_question_with_nothing_in_common_is_a_new_topic():
    history = [_u("¿Cuántas siestas hace un bebé de 8 meses?"), _a("Dos [ev_1].")]
    c = conv.read("Le han salido unas manchas rojas en el cuello después del baño", history)
    assert c.kind == "new"


def test_what_the_rules_cannot_place_stays_a_follow_up_and_the_model_may_say_otherwise():
    history = [_u("¿Cuánta leche tiene que tomar al día?"), _a("Unos 500 ml [ev_1].")]
    c = conv.read("Se despierta mucho", history)
    assert c.kind == "follow_up" and c.via == "default" and not c.decided
    assert c.route_history  # the routing model gets the thread to decide on
    new = conv.with_kind(c, "new")
    assert new.kind == "new" and new.via == "model"
    assert new.model_history == [] and new.search_query == "Se despierta mucho"
    same = conv.with_kind(c, "follow_up", search_query="¿Es normal que se despierte mucho?")
    assert same.search_query == "¿Es normal que se despierte mucho?\nSe despierta mucho"


def test_the_model_cannot_overrule_what_the_rules_decided():
    c = conv.read("No es enfermo", CONV1)
    assert conv.with_kind(c, "new") == c


def test_a_search_query_from_the_model_is_bounded():
    history = [_u("¿Cuánta leche tiene que tomar al día?"), _a("Unos 500 ml [ev_1].")]
    c = conv.read("Se despierta mucho", history)
    assert conv.with_kind(c, "follow_up", search_query="   ").search_query == c.search_query
    long = conv.with_kind(c, "follow_up", search_query="x" * 5000)
    assert len(long.search_query) <= conv.MAX_QUERY_CHARS


# --- B. what the search and the model see -----------------------------------------


def test_a_follow_up_is_searched_with_her_words_never_with_the_answer():
    c = conv.read("Pero todos los días está así", CONV1[:2])
    assert GUARDERIA in c.search_query
    assert "Pero todos los días está así" in c.search_query
    for word in ("enfermo", "Vigila", "quede en casa", "fiebre", "[ev_"):
        assert word not in c.search_query, word


def test_a_behaviour_topic_is_searched_with_the_corpus_words_for_it():
    """Searched as she wrote it, the guardería question found "niño enfermo
    en la guardería" cards. The corpus has adaptation, separation anxiety and
    social development (evidence_guarderia_adaptacion, evidence_desarrollo):
    a reformulated turn adds their words."""
    c = conv.read("Pero todos los días está así", CONV1[:2])
    assert c.behaviour
    assert "adaptación" in c.search_query and "desarrollo social" in c.search_query


def test_a_first_turn_is_searched_untouched_even_on_a_behaviour_topic():
    """The golden gate's questions are first turns: their search text must not move."""
    assert conv.read(GUARDERIA, []).search_query == GUARDERIA


def test_the_routing_model_gets_a_short_tail_of_the_thread_and_nothing_on_a_first_turn():
    assert conv.read(GUARDERIA, []).route_history == []
    long = [_u("a" * 5000), _a("b" * 5000)] * 4
    c = conv.read("Pero todos los días está así", long)
    assert len(c.route_history) == conv.ROUTE_HISTORY_MESSAGES
    assert all(len(m["content"]) <= conv.ROUTE_HISTORY_CHARS for m in c.route_history)


def test_the_route_text_carries_the_topic_for_a_follow_up_and_only_the_message_otherwise():
    sleep = "¿Cuántas siestas tiene que hacer un bebé de 8 meses?"
    follow = conv.read("¿y por la noche?", [_u(sleep), _a("Dos [ev_1].")])
    assert follow.route_text == f"{sleep}\n¿y por la noche?"
    assert conv.read(GUARDERIA, CONV2[:2]).route_text == GUARDERIA


def test_a_correction_tells_the_model_what_she_took_back_and_what_she_asked():
    c = conv.read("No es enfermo", CONV1)
    assert GUARDERIA in c.prompt_question
    note = conv.correction_note(c)
    assert "«No es enfermo»" in note


def test_only_a_correction_carries_a_note():
    assert conv.correction_note(conv.read("Pero todos los días está así", CONV1[:2])) == ""


# --- C. ask before answering, one round per topic ---------------------------------


def test_her_words_after_a_clarify_question_answer_it_and_carry_her_question():
    history = [_u(GUARDERIA), _a(ASKED)]
    c = conv.read("Dos semanas, y en casa sí, me mira y se ríe", history)
    assert c.kind == "follow_up" and c.via == "clarify" and c.answering
    assert c.asked
    assert c.message == f"{GUARDERIA}\nDos semanas, y en casa sí, me mira y se ríe"
    assert c.model_history == []


def test_a_button_answer_spends_the_round_too():
    history = [_u(GUARDERIA), _a(ASKED)]
    c = conv.read(f"{GUARDERIA}\nLleva en la guardería: menos de un mes", history,
                  clarified=True)
    assert c.asked and c.via == "clarify"


@pytest.mark.parametrize("text", [
    GUARDERIA,
    "No juega con los otros niños del parque, se queda solo en un rincón",
    "No responde a su nombre y casi no me mira",
    "My baby sits alone in a corner at nursery and doesn't play",
    "À la crèche il reste assis dans un coin et ne joue pas",
])
def test_a_behaviour_or_development_worry_is_a_behaviour_topic(text):
    assert conv.read(text, []).behaviour


@pytest.mark.parametrize("text", [
    "Tiene fiebre y no juega, está muy decaído",
    "¿Cuántas siestas tiene que hacer un bebé de 8 meses?",
    "Tiene mocos y tose por la noche",
])
def test_an_illness_or_a_plain_question_is_not_a_behaviour_topic(text):
    assert not conv.read(text, []).behaviour


def test_behaviour_at_the_nursery_asks_how_long_and_the_signals_at_home():
    assert conv.ask_first(conv.read(GUARDERIA, []), AGE_14) == ["nursery_time", "social_signals"]


def test_behaviour_without_a_nursery_asks_since_when():
    c = conv.read("No juega con los otros niños del parque, se queda solo en un rincón", [])
    assert conv.ask_first(c, AGE_14) == ["since_when", "social_signals"]


def test_behaviour_without_an_age_asks_the_age_first():
    assert conv.ask_first(conv.read(GUARDERIA, []), NO_AGE) == ["age", "social_signals"]


def test_never_a_second_round_in_the_same_topic():
    history = [_u(GUARDERIA), _a(ASKED)]
    assert conv.ask_first(conv.read("Dos semanas", history), AGE_14) == []
    later = history + [_u("Dos semanas"), _a("Es la adaptación [ev_1]."),
                       _u("Pero todos los días está así")]
    c = conv.read("¿Y si sigue igual en un mes?", later)
    assert c.asked and conv.ask_first(c, AGE_14) == []


def test_the_replayed_conversation_asks_on_the_second_turn_because_it_never_asked():
    """His transcript never had a question in it, so the round is still there."""
    assert conv.ask_first(conv.read("Pero todos los días está así", CONV1[:2]), AGE_14) == [
        "nursery_time", "social_signals",
    ]


def test_a_non_behaviour_topic_asks_nothing_before_answering():
    c = conv.read("¿Cuántas siestas tiene que hacer un bebé de 8 meses?", [])
    assert conv.ask_first(c, AGE_14) == []


def test_without_evidence_a_concern_asks_since_when_and_how_she_is():
    c = conv.read("Le han salido unas manchas en la espalda, ¿qué hago?", [])
    assert conv.ask_when_nothing_found(c, AGE_14, intent="plan") == [
        "since_when", "general_state",
    ]


def test_without_evidence_a_fact_question_or_a_drug_is_never_asked_about():
    c = conv.read("¿Le puedo dar melatonina para dormir?", [])
    assert conv.ask_when_nothing_found(c, AGE_14, intent="plan") == []
    c = conv.read("¿Qué es la costra láctea?", [])
    assert conv.ask_when_nothing_found(c, AGE_14, intent="question") == []


# The signals the social_signals question names, each tied to the corpus
# passage that makes it a reason to consult (the question must not invent one).
_DATA = Path(__file__).resolve().parents[1] / "adelia" / "enrichment" / "data"


def _corpus_text(title: str) -> str:
    for path in sorted(_DATA.glob("evidence_*.json")):
        for source in json.loads(path.read_text())["sources"]:
            if source.get("title") == title:
                chunks = source["chunks"]
                return " ".join(c["content"] if isinstance(c, dict) else c for c in chunks)
    raise AssertionError(f"no corpus source titled {title!r}")


@pytest.mark.parametrize("signal", sorted(conv.SIGNAL_SOURCES))
def test_every_signal_the_question_names_is_a_consult_sign_in_the_corpus(signal):
    title, passage = conv.SIGNAL_SOURCES[signal]
    assert passage in _corpus_text(title)
    asked = CLARIFY_QUESTIONS["social_signals"]["es"]
    words = asked["question"] + " " + " ".join(o["label"] for o in asked["options"])
    assert signal in words


# --- D. no evidence: once, then something useful ----------------------------------


def test_the_refusal_already_given_in_this_topic_is_remembered():
    history = [_u("¿Qué le pasa si tiene la lengua blanca?"), _a(no_evidence_reply("es"))]
    c = conv.read("Pero no se le quita con nada", history)
    assert c.refused
    assert not conv.read("¿Cuándo le toca la vacuna?", history).refused


def test_the_note_for_the_pediatrician_is_only_her_own_words():
    history = [_u(GUARDERIA), _a(ASKED)]
    c = conv.read("Dos semanas, y en casa sí, me mira y se ríe", history)
    note = conv.consult_note(c, "es")
    assert GUARDERIA in note and "Dos semanas, y en casa sí, me mira y se ríe" in note
    assert "[ev_" not in note and "enfermo" not in note


def test_the_text_she_can_save_for_the_visit_fits_an_observation():
    c = conv.read("x " * 600, [])
    assert 0 < len(conv.visit_note(c)) <= 500


def test_an_answer_in_words_to_a_question_asked_on_a_follow_up_carries_the_whole_topic():
    asked = CLARIFY_QUESTIONS["since_when"]["es"]["question"]
    history = [_u("Le han salido unas manchas en la espalda"), _a(no_evidence_reply("es")),
               _u("Pero no se le quitan"), _a(asked)]
    c = conv.read("Hace una semana", history)
    assert c.answering
    assert c.message == (
        "Le han salido unas manchas en la espalda\nPero no se le quitan\nHace una semana"
    )


def test_a_long_thread_loses_its_middle_never_the_first_question():
    first = "¿Por qué mi bebé no quiere comer verdura? " + "a" * 250
    history = []
    for i in range(5):
        history += [_u(first if i == 0 else f"y además le pasa {i} " + "b" * 280),
                    _a("Respuesta [ev_1].")]
    c = conv.read("¿y si lo mezclo con fruta?", history)
    assert len(c.search_query) <= conv.MAX_QUERY_CHARS
    assert c.search_query.startswith("¿Por qué mi bebé no quiere comer verdura?")
    assert c.search_query.endswith("¿y si lo mezclo con fruta?")


# --- the golden gate does not move -----------------------------------------------


def test_every_golden_question_is_a_first_turn_searched_exactly_as_written():
    """The gate asks each question with no history: its search text, its
    route text and its prompt are the question itself, as before."""
    from adelia.clinical.golden import CANDIDATES, GOLDEN_SET

    for q in (*GOLDEN_SET, *CANDIDATES):
        c = conv.read(q.question, [])
        assert c.kind == "new" and c.via == "first", q.id
        assert c.search_query == c.route_text == c.prompt_question == q.question, q.id
        assert c.model_history == [] and c.route_history == [], q.id


# --- a "no" that adds a fact is not a correction ------------------------------------

_SLEEP_THREAD = [_u("¿Cuántas siestas tiene que hacer un bebé de 8 meses?"),
                 _a("A los 8 meses suelen hacer 2 siestas [ev_1].")]


@pytest.mark.parametrize("text", [
    "No tiene hambre",
    "No está durmiendo bien",
    "Pero no tiene ganas de jugar y llora",
])
def test_a_no_that_tells_something_new_is_kept_in_the_search(text):
    c = conv.read(text, _SLEEP_THREAD)
    assert c.kind != "correction"
    assert c.retracted == ()
    assert text in c.search_query


@pytest.mark.parametrize("text", ["No está enfermo", "No es enfermo", "He's not sick",
                                  "Il n'est pas malade"])
def test_saying_the_baby_is_not_ill_is_a_correction_even_if_the_answer_never_said_ill(text):
    c = conv.read(text, CONV1[:2])
    assert c.kind == "correction" and c.retracted


def test_no_tiene_fiebre_corrects_only_an_answer_that_talked_about_fever():
    assert conv.read("No tiene fiebre", CONV2).kind == "correction"
    c = conv.read("No tiene fiebre", _SLEEP_THREAD)
    assert c.kind != "correction" and "No tiene fiebre" in c.search_query


def test_an_earlier_no_that_added_a_fact_stays_in_a_later_search():
    history = [*_SLEEP_THREAD, _u("No tiene hambre"), _a("Puede ser normal [ev_1].")]
    c = conv.read("¿y qué hago?", history)
    assert "No tiene hambre" in c.search_query


# --- review of 2026-11-09 (second pass) -------------------------------------------

_COLD = [_u("Tiene 38,5 de fiebre y mocos desde ayer"), _a("Ofrécele líquidos [ev_1].")]


def test_a_sick_baby_who_stops_playing_is_not_asked_the_development_questions():
    c = conv.read("Hoy no juega nada, se queda quieto en el sofá", _COLD)
    assert c.kind == "follow_up"
    assert not c.behaviour and conv.ask_first(c, AGE_14) == []
    assert "fiebre" in c.search_query


def test_asi_points_back_at_the_topic():
    c = conv.read("¿Puedo llevarlo a la guardería así mañana?", _COLD)
    assert c.kind == "follow_up" and "fiebre" in c.search_query


@pytest.mark.parametrize("text", ["No es la primera vez", "No es la única vez que pasa"])
def test_no_es_la_primera_vez_is_a_fact_not_a_correction(text):
    history = [_u("Le salieron ronchas al comer huevo"), _a("Puede ser una alergia [ev_1].")]
    c = conv.read(text, history)
    assert c.kind != "correction" and c.retracted == ()
    assert text in c.search_query


def test_a_long_follow_up_is_searched_whole():
    tail = " y además esta tarde le he visto unas manchitas que no se van al apretar"
    message = "Pero " + "sigue con mocos y tose mucho por la noche, " * 7 + tail
    c = conv.read(message, _COLD)
    assert c.search_query.endswith(tail.strip())
    assert c.search_query.startswith("Tiene 38,5 de fiebre")


def test_a_model_search_query_never_loses_her_message():
    history = [_u("¿Cuánta leche tiene que tomar al día?"), _a("Unos 500 ml [ev_1].")]
    c = conv.read("Se despierta mucho", history)
    c = conv.with_kind(c, "follow_up", search_query="despertares nocturnos del lactante")
    assert c.search_query == "despertares nocturnos del lactante\nSe despierta mucho"


def test_her_button_presses_are_read_as_her_sentences_in_later_turns():
    history = [_u(GUARDERIA), _a(ASKED), _u("Menos de un mes · Sí, todo eso"),
               _a("Es la adaptación [ev_1].")]
    c = conv.read("¿Y si sigue igual en un mes?", history)
    assert "Lleva menos de un mes en la guardería." in c.search_query
    assert "Menos de un mes · Sí, todo eso" not in c.search_query


# --- the battery's gaps (2026-11-11): a referral, a redirect, her shorthand ---------

from adelia.services.answer_contract import out_of_scope_reply, red_flag_reply  # noqa: E402

FEVER_2M = "tiene 38,2 y no para de llorar"
REFERRAL = red_flag_reply("fever_under_3_months", "es")


@pytest.mark.parametrize("text", [
    "le doy apiretal mientras", "y si le baja?", "puedo esperar a mañana?",
    "lo baño con agua fria?", "se ha dormido ahora, la despierto para ir",
])
def test_after_a_referral_her_next_message_stays_in_the_flagged_topic(text):
    """The battery: «le doy apiretal mientras» after a fever at 2 months got no
    referral. The guard reads the topic only if the thread keeps her there."""
    c = conv.read(text, [_u(FEVER_2M), _a(REFERRAL)])
    assert c.kind == "follow_up"
    assert c.referral == "fever_under_3_months"
    assert c.topic == (FEVER_2M,)


def test_a_referral_is_recognised_in_any_language():
    fr = red_flag_reply("fever_under_3_months", "fr")
    c = conv.read("il dort beaucoup aussi", [_u("mon bébé a 38,3"), _a(fr)])
    assert c.referral == "fever_under_3_months"


def test_a_topic_she_marks_as_new_after_a_referral_carries_no_referral():
    c = conv.read("otra cosa, cuantas siestas tiene que hacer a los 2 meses?",
                  [_u(FEVER_2M), _a(REFERRAL)])
    assert c.kind == "new" and c.referral is None


def test_a_topic_without_a_referral_has_none():
    c = conv.read("y por la noche", [_u("cuantas siestas"), _a("Dos o tres [ev_1].")])
    assert c.referral is None


@pytest.mark.parametrize("text", ["vale y la niña duerme bien boca arriba",
                                  "y mi bebé de 4 meses puede tomar fruta?"])
def test_after_the_out_of_scope_redirect_a_message_about_the_baby_is_a_new_topic(text):
    history = [_u("yo tengo dolor de espalda desde el parto"), _a(out_of_scope_reply("es"))]
    c = conv.read(text, history)
    assert c.kind == "new" and "espalda" not in c.search_query


def test_after_the_redirect_more_about_herself_stays_in_that_topic():
    history = [_u("yo tengo dolor de espalda desde el parto"), _a(out_of_scope_reply("es"))]
    c = conv.read("y si estoy dando el pecho", history)
    assert c.kind == "follow_up"


@pytest.mark.parametrize("text", ["lo baño con agua fria?", "¿la abrigo mucho o poco?",
                                  "le quito la ropa para dormir?"])
def test_a_short_question_about_him_with_no_subject_of_its_own_goes_on_with_the_topic(text):
    """«lo baño con agua fria?» after a fever was a new topic and lost the fever:
    a question that opens on «lo/la/le» points back at the baby being talked about."""
    history = [_u("tiene 38,5 y esta muy llorona"), _a("Ofrécele líquidos [ev_1].")]
    c = conv.read(text, history)
    assert c.kind == "follow_up"
    assert "38,5" in c.search_query


def test_a_long_self_contained_question_opening_on_le_is_still_a_new_topic():
    history = [_u("cuantas siestas a los 8 meses"), _a("Dos [ev_1].")]
    c = conv.read("le han salido unas manchas rojas en la barriga y en la espalda que no se "
                  "van al apretar, ¿qué es?", history)
    assert c.kind == "new"


@pytest.mark.parametrize("text", ["en la guarde no juega con nadie siempre solo",
                                  "desde q va a la guarde no juega con nadie"])
def test_guarde_is_the_nursery(text):
    c = conv.read(text, [])
    assert c.behaviour and c.nursery
    assert conv.ask_first(c, AGE_14) == ["nursery_time", "social_signals"]


@pytest.mark.parametrize("text", ["he doesnt say any words yet", "she doesn't say a word",
                                  "il ne dit aucun mot", "elle ne dit pas encore de mots"])
def test_no_words_yet_is_a_development_worry_in_english_and_french(text):
    c = conv.read(text, [])
    assert c.behaviour
    assert conv.ask_first(c, AGE_14) == ["since_when", "social_signals"]


@pytest.mark.parametrize("text", ["tb tiene mocos", "tmb se despierta"])
def test_tb_is_tambien_and_goes_on_with_the_topic(text):
    history = [_u("tiene 38,5 y esta muy llorona"), _a("Ofrécele líquidos [ev_1].")]
    c = conv.read(text, history)
    assert c.kind == "follow_up" and c.via == "rule"


def test_saying_he_has_no_fever_keeps_a_behaviour_topic_a_behaviour_topic():
    """«Es tema nuevo. No tiene fiebre ninads» under the nursery question: the
    fever she denies is not an illness that turns the topic into a sick baby."""
    c = conv.read("Es tema nuevo. No tiene fiebre ninads", [_u(GUARDERIA), _a(ASKED)])
    assert c.behaviour and c.nursery


def test_a_fever_she_reports_still_makes_it_a_sick_baby():
    c = conv.read("no juega con nadie y tiene fiebre", [])
    assert not c.behaviour


def test_drops_are_a_medicine_and_are_not_asked_about_when_nothing_is_found():
    c = conv.read("le puedo dar gotas para los gases", [_u("llora y encoge las piernas"),
                                                        _a("Puede ser cólico [ev_1].")])
    assert conv.ask_when_nothing_found(c, AGE_14, intent="plan") == []


@pytest.mark.parametrize("text", ["la caca es verde, es normal?", "la fiebre sube por la noche?"])
def test_la_as_an_article_opens_its_own_short_question(text):
    c = conv.read(text, [_u("cuantas siestas a los 8 meses"), _a("Dos [ev_1].")])
    assert c.kind == "new"


@pytest.mark.parametrize("text", ["puedo darle algo para el dolor",
                                  "can i give her something for the pain",
                                  "je peux lui donner quelque chose contre la douleur"])
def test_something_for_the_pain_is_a_medicine_and_is_not_asked_about(text):
    c = conv.read(text, [_u("le estan saliendo los dientes y babea"), _a("Es normal [ev_1].")])
    assert conv.ask_when_nothing_found(c, AGE_14, intent="plan") == []
