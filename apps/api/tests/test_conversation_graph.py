"""Multi-turn regressions through the whole graph, without a model (2026-11-09).

Santiago's two production conversations of 2026-11-09 and the cases he asked
for next to them, each run through `stream_graph` with fakes for what costs
money (route, retrieval, generation). What each test reads back is what the
fakes received: the kind of turn, the search text, the prior turns the
answering model saw, the cards. The red flag, the coded refusal and the
clinical contract are the real ones.

  * a follow-up is searched with her words in the topic, never AdelIA's;
  * a correction drops the answers built on the frame she rejected;
  * a new topic carries nothing of the old one (the fever noted before);
  * a behaviour worry gets one round of questions before any answer, and
    never a second one in the same topic;
  * nothing found: one round of questions for a worry, then the refusal
    once, with her own words for the visit and a card to note them;
  * the red flag still comes first on the second turn.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from adelia.agent import record as rec
from adelia.agent.graph import (
    ACCOUNT_CLARIFY_FIELDS,
    GraphDeps,
    Retrieved,
    run_graph,
    stream_graph,
)
from adelia.agent.route import RouteDecision
from adelia.enrichment.profile_service import ProfileFacts
from adelia.services.answer_contract import CLARIFY_QUESTIONS, no_evidence_reply

from tests.test_agent_graph import EVIDENCE, Fakes
from tests.test_conversation import (
    ASKED,
    CONV1,
    CONV2,
    FEVER_NOTE,
    GUARDERIA,
    NOTED,
    SICK_FRAME,
)

MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 11, 9, 11, 12, tzinfo=MADRID)
AGE_14 = ProfileFacts(None, "Leo", None, "M", 14)

SLEEP = "¿Cuántas siestas tiene que hacer un bebé de 8 meses?"
SLEEP_ANSWER = "A los 8 meses suelen hacer 2 siestas [ev_1]."
MILK = "¿Cuánta leche tiene que tomar al día?"
MILK_ANSWER = "A los 6 meses, unos 500 a 600 ml al día [ev_1]."
SPOTS = "Le han salido unas manchas en la espalda, ¿qué hago?"
ASKED_WHEN_NOTHING = (
    CLARIFY_QUESTIONS["since_when"]["es"]["question"] + "\n"
    + CLARIFY_QUESTIONS["general_state"]["es"]["question"]
)


def _u(text):
    return {"role": "user", "content": text}


def _a(text):
    return {"role": "assistant", "content": text}


class Store:
    def __init__(self):
        self.saved = []

    async def save(self, draft):
        self.saved.append(draft)

    async def previous(self, kind, before):
        return None


class Surface:
    """An account surface whose fakes record what reached them."""

    def __init__(self, *, intent="plan", via="rule", evidence=(EVIDENCE,), turn=None,
                 search_query=None, missing=(), tokens=("Respuesta [ev_1].",)):
        self.decision = RouteDecision(intent=intent, confidence=0.9, via=via, turn=turn,
                                      search_query=search_query, missing=list(missing))
        self.evidence, self.tokens = list(evidence), list(tokens)
        self.store = Store()
        self.calls: list[tuple] = []

    async def route(self, message, **kwargs):
        self.calls.append(("route", message, kwargs))
        return self.decision

    async def retrieve(self, state):
        self.calls.append(("retrieve", state["search_query"], state["message"]))
        return Retrieved(evidence=self.evidence)

    async def stream(self, system, user, history=None):
        self.calls.append(("stream", system, user, history))
        for t in self.tokens:
            yield t

    async def track(self, state):
        self.calls.append(("track", state["message"]))
        yield {"type": "result", "answer": "", "citations": [], "evidence_citations": []}

    def names(self):
        return [c[0] for c in self.calls]

    def one(self, name):
        (call,) = [c for c in self.calls if c[0] == name]
        return call

    def agent(self) -> GraphDeps:
        return GraphDeps(route=self.route, retrieve=self.retrieve, stream=self.stream,
                         can_ask=True, can_write=True, record_store=self.store,
                         track=self.track, now=lambda: NOW,
                         clarify_fields=ACCOUNT_CLARIFY_FIELDS, clarify_round=2)

    def chat(self) -> GraphDeps:
        return GraphDeps(route=self.route, retrieve=self.retrieve, stream=self.stream,
                         can_ask=False, now=lambda: NOW)


async def _turn(deps, message, history, **state):
    events = [e async for e in stream_graph(
        {"surface": "agent", "locale": "es", "message": message, "account": True,
         "facts": AGE_14, "history": history, **state}, deps)]
    assert events[-1]["type"] == "final"
    return events[:-1], events[-1]["state"]


def _cards(events):
    return [e["card"] for e in events if e["type"] == "card"]


def _text(events):
    return "".join(e["content"] for e in events if e["type"] == "token")


# --- conversation 1: the nursery, his account ------------------------------------


async def test_c1_turn_one_asks_how_long_and_the_signals_at_home_before_answering():
    s = Surface()
    events, final = await _turn(s.agent(), GUARDERIA, [])
    (card,) = _cards(events)
    assert card["type"] == "clarify"
    assert [q["field"] for q in card["payload"]["questions"]] == [
        "nursery_time", "social_signals"]
    assert card["payload"]["message"] == GUARDERIA
    assert card["payload"]["free"]
    assert final["kind"] == "clarify"
    assert final["answer"] == ASKED
    # Asked before routing: the rules place nothing else, so the routing
    # model (up to 2 s) is not paid for a question we ask anyway.
    assert s.calls == []


async def test_c1_her_answer_in_words_is_read_under_her_question_and_searched_as_adaptation():
    s = Surface()
    answer = "Lleva dos semanas, y en casa sí, me mira y sonríe"
    events, final = await _turn(s.agent(), answer, [_u(GUARDERIA), _a(ASKED)])
    assert final["kind"] == "answer" and not _cards(events)
    _, query, message = s.one("retrieve")
    assert message == f"{GUARDERIA}\n{answer}"
    assert GUARDERIA in query and answer in query and "adaptación" in query
    _, _, user, history = s.one("stream")
    assert history == []
    assert answer in user and "enfermo" not in user


async def test_c1_buttons_answer_both_questions_in_one_turn():
    s = Surface()
    events, final = await _turn(
        s.agent(), GUARDERIA, [_u(GUARDERIA), _a(ASKED)],
        clarifications=[{"field": "nursery_time", "value": "lt1m"},
                        {"field": "social_signals", "value": "all"}],
    )
    assert final["kind"] == "answer" and not _cards(events)
    _, query, message = s.one("retrieve")
    assert "Lleva menos de un mes en la guardería." in message
    assert "responde a su nombre" in message
    assert "adaptación" in query


async def test_c1_replayed_pero_todos_los_dias_is_a_follow_up_that_now_asks_first():
    """His transcript never had a question in it: the round is still there."""
    s = Surface()
    events, final = await _turn(s.agent(), "Pero todos los días está así", CONV1[:2])
    (card,) = _cards(events)
    assert card["type"] == "clarify"
    assert card["payload"]["message"] == f"{GUARDERIA}\nPero todos los días está así"
    assert "enfermo" not in card["payload"]["message"]
    assert s.calls == []


async def test_c1_no_es_enfermo_after_the_round_drops_the_sick_answers():
    s = Surface()
    history = [_u(GUARDERIA), _a(ASKED), _u("Menos de un mes · Sí, todo eso"), _a(SICK_FRAME)]
    events, final = await _turn(s.agent(), "No es enfermo", history)
    assert final["kind"] == "answer" and not _cards(events)
    _, query, _ = s.one("retrieve")
    assert "enfermo" not in query.lower() and "quede en casa" not in query
    assert GUARDERIA in query
    _, _, user, model_history = s.one("stream")
    assert model_history == []
    assert "«No es enfermo»" in user and GUARDERIA in user
    assert "quede en casa" not in user


async def test_a_correction_the_router_cannot_place_takes_the_contract_path():
    """With the model down the fallback used to send it to the tool loop."""
    s = Surface(intent="plan", via="fallback")
    history = [_u(GUARDERIA), _a(ASKED), _u("Menos de un mes"), _a(SICK_FRAME)]
    _, final = await _turn(s.agent(), "No es enfermo", history)
    assert final["intent"] == "plan" and "track" not in s.names()


# --- conversation 2: the guest space, a fever noted, then the nursery ----------


async def test_c2_a_new_topic_after_noting_a_fever_never_sees_the_fever():
    s = Surface()
    question = "¿Cuándo puede empezar a comer huevo?"
    _, final = await _turn(s.agent(), question, [_u(FEVER_NOTE), _a(NOTED)])
    assert final["kind"] == "answer"
    _, query, _ = s.one("retrieve")
    assert query == question
    _, _, user, history = s.one("stream")
    assert history == []
    assert "38" not in user and "fiebre" not in user.lower()


async def test_c2_the_nursery_question_after_the_fever_asks_and_carries_no_fever():
    s = Surface()
    events, _ = await _turn(s.agent(), GUARDERIA, [_u(FEVER_NOTE), _a(NOTED)])
    (card,) = _cards(events)
    assert card["type"] == "clarify" and card["payload"]["message"] == GUARDERIA
    assert s.calls == []


async def test_c2_es_tema_nuevo_no_tiene_fiebre_takes_back_the_fever_and_keeps_the_nursery():
    s = Surface()
    events, _ = await _turn(s.agent(), "Es tema nuevo. No tiene fiebre ninads", CONV2)
    (card,) = _cards(events)
    assert card["type"] == "clarify"
    assert card["payload"]["message"] == GUARDERIA


# --- the other cases he asked for ----------------------------------------------


async def test_y_por_la_noche_after_a_sleep_question_is_searched_with_it():
    s = Surface(intent="question")
    _, final = await _turn(s.agent(), "¿y por la noche?", [_u(SLEEP), _a(SLEEP_ANSWER)])
    assert final["kind"] == "answer"
    _, query, _ = s.one("retrieve")
    assert query == f"{SLEEP}\n¿y por la noche?"
    _, _, _, history = s.one("stream")
    assert history == [_u(SLEEP), _a(SLEEP_ANSWER)]


async def test_an_age_correction_is_searched_with_the_question_and_the_new_age():
    s = Surface(intent="question")
    _, _ = await _turn(s.agent(), "Perdona, tiene 9 meses, no 6", [_u(MILK), _a(MILK_ANSWER)])
    _, query, _ = s.one("retrieve")
    assert MILK in query and "9 meses" in query
    _, _, user, history = s.one("stream")
    assert history == [] and MILK in user


async def test_a_red_flag_on_the_second_turn_still_comes_first():
    s = Surface()
    events, final = await _turn(s.agent(), "Se ha puesto morado y le cuesta respirar",
                                [_u(SLEEP), _a(SLEEP_ANSWER)])
    assert final["kind"] == "red_flag"
    assert s.calls == []
    assert not _cards(events)


async def test_a_red_flag_in_her_answer_to_a_clarify_question_fires():
    s = Surface()
    events, final = await _turn(s.agent(), "Ahora se ha puesto morado",
                                [_u(GUARDERIA), _a(ASKED)])
    assert final["kind"] == "red_flag" and s.calls == []


# --- one round per topic ----------------------------------------------------------


async def test_never_a_second_round_in_the_same_topic_even_if_the_router_asks():
    s = Surface(intent="clarify", missing=["temperature"])
    history = [_u(GUARDERIA), _a(ASKED), _u("Menos de un mes"), _a("Es la adaptación [ev_1].")]
    events, final = await _turn(s.agent(), "¿Y si sigue igual en un mes?", history)
    assert final["kind"] == "answer" and not _cards(events)


# --- D. nothing found ----------------------------------------------------------------


async def test_nothing_found_for_a_worry_asks_one_round_before_refusing():
    s = Surface(evidence=())
    events, final = await _turn(s.agent(), SPOTS, [])
    (card,) = _cards(events)
    assert [q["field"] for q in card["payload"]["questions"]] == ["since_when", "general_state"]
    assert final["kind"] == "clarify"
    assert "stream" not in s.names()


async def test_still_nothing_says_it_once_with_her_words_and_a_card_to_note_them():
    s = Surface(evidence=())
    events, final = await _turn(s.agent(), "Hace una semana y está bien",
                                [_u(SPOTS), _a(ASKED_WHEN_NOTHING)])
    assert final["kind"] == "no_evidence"
    text = _text(events)
    assert text.startswith(no_evidence_reply("es"))
    assert f"«{SPOTS}»" in text and "«Hace una semana y está bien»" in text
    (card,) = _cards(events)
    assert card["type"] == "confirm" and card["payload"]["tool_name"] == rec.RECORD_TOOL
    args = card["payload"]["tool_args"]
    assert args["kind"] == "note" and SPOTS in args["text"]
    assert card["payload"]["body"] == args["text"]
    assert rec.validate_args(args, now=NOW) is not None
    assert final["evidence_citations"] == []
    assert s.store.saved == [], "nothing is written before she confirms"


async def test_the_refusal_is_not_said_again_in_the_same_topic():
    s = Surface(evidence=())
    history = [_u(SPOTS), _a(ASKED_WHEN_NOTHING), _u("Hace una semana"),
               _a(no_evidence_reply("es") + "\n\nPara la consulta, esto es lo que me has contado:")]
    events, final = await _turn(s.agent(), "Pero no se le quitan con nada", history)
    assert final["kind"] == "no_evidence"
    text = _text(events)
    assert no_evidence_reply("es") not in text
    assert text.startswith("Sigo sin fuentes sobre esto.")
    assert "«Pero no se le quitan con nada»" in text


async def test_nothing_found_for_a_drug_question_refuses_without_asking():
    s = Surface(evidence=())
    events, final = await _turn(s.agent(), "¿Le puedo dar melatonina para dormir?", [])
    assert final["kind"] == "no_evidence"
    assert _text(events).startswith(no_evidence_reply("es"))
    assert all(c["type"] != "clarify" for c in _cards(events))


async def test_the_chat_says_the_refusal_without_cards_or_questions():
    s = Surface(evidence=())
    events, final = await _turn(s.chat(), SPOTS, [])
    assert final["kind"] == "no_evidence" and _cards(events) == []
    assert _text(events) == no_evidence_reply("es")


# --- what the routing model sees, and what it may decide --------------------------


async def test_a_follow_up_routes_with_the_topic_and_a_tail_of_the_thread():
    s = Surface(intent="question")
    await _turn(s.agent(), "¿y por la noche?", [_u(SLEEP), _a(SLEEP_ANSWER)])
    _, routed, kwargs = s.one("route")
    assert routed == f"{SLEEP}\n¿y por la noche?"
    assert kwargs["history"] == [_u(SLEEP), _a(SLEEP_ANSWER)]


async def test_a_behaviour_worry_the_rules_place_elsewhere_is_routed_not_asked():
    """"Que vacunas le tocan" is her own data whatever else she says: the rules
    send it to the tool loop and no round is asked."""
    s = Surface(intent="track")
    events, final = await _turn(
        s.agent(), "No juega con los otros niños, ¿qué vacunas le tocan?", [])
    assert final["intent"] == "track" and not _cards(events)


async def test_a_first_turn_routes_without_any_thread():
    s = Surface()
    await _turn(s.agent(), SLEEP, [])
    _, routed, kwargs = s.one("route")
    assert routed == SLEEP and "history" not in kwargs


async def test_the_model_may_say_new_topic_where_the_rules_could_not():
    s = Surface(via="model", turn="new")
    _, _ = await _turn(s.agent(), "Se despierta mucho", [_u(MILK), _a(MILK_ANSWER)])
    _, query, _ = s.one("retrieve")
    assert query == "Se despierta mucho"
    _, _, _, history = s.one("stream")
    assert history == []


async def test_the_model_search_query_is_used_where_the_rules_could_not_decide():
    s = Surface(via="model", turn="follow_up",
                search_query="¿Es normal que se despierte mucho por la noche?")
    _, _ = await _turn(s.agent(), "Se despierta mucho", [_u(MILK), _a(MILK_ANSWER)])
    _, query, _ = s.one("retrieve")
    assert query == "¿Es normal que se despierte mucho por la noche?\nSe despierta mucho"


async def test_the_model_cannot_overrule_a_correction_the_rules_saw():
    s = Surface(via="model", turn="new", search_query="niño enfermo guardería")
    history = [_u(GUARDERIA), _a(ASKED), _u("Menos de un mes"), _a(SICK_FRAME)]
    await _turn(s.agent(), "No es enfermo", history)
    _, query, _ = s.one("retrieve")
    assert "enfermo" not in query


# --- the chat: same thread rules, no questions ------------------------------------


async def test_the_chat_drops_the_fever_from_a_new_topic_too():
    s = Surface()
    await _turn(s.chat(), "¿Cuándo puede empezar a comer huevo?", [_u(FEVER_NOTE), _a(NOTED)])
    _, _, _, history = s.one("stream")
    assert history == []


async def test_the_chat_never_asks_the_behaviour_round():
    s = Surface()
    events, final = await _turn(s.chat(), GUARDERIA, [])
    assert final["kind"] == "answer" and _cards(events) == []
    _, query, _ = s.one("retrieve")
    assert query == GUARDERIA


# --- the demo: no thread, nothing moves ---------------------------------------------


@pytest.mark.parametrize("question", [GUARDERIA, SPOTS, SLEEP])
async def test_the_demo_searches_and_answers_a_first_turn_as_before(question):
    fakes = Fakes(evidence=())
    out = await run_graph(
        {"surface": "demo", "locale": "es", "message": question, "account": False,
         "facts": ProfileFacts(None, None, None, None, 5)},
        fakes.deps(),
    )
    assert out["kind"] in ("no_evidence", "experience_only")
    (_, texts), = [c for c in fakes.calls if c[0] == "embed"]
    assert texts[0] == question
    assert out.get("clarify") is None


async def test_a_follow_up_on_the_noted_fever_keeps_it_because_it_is_the_topic():
    s = Surface()
    await _turn(s.agent(), "¿Y qué hago?", [_u(FEVER_NOTE), _a(NOTED)])
    _, query, _ = s.one("retrieve")
    assert query == f"{FEVER_NOTE}\n¿Y qué hago?"
    _, _, _, history = s.one("stream")
    assert history == [_u(FEVER_NOTE), _a(NOTED)]


async def test_a_diary_line_inside_a_topic_still_becomes_a_card():
    """Routed with her topic, "Ha hecho 3 cacas hoy" after a question read as
    a question; alone it is a diary line, and that is what she meant."""
    from adelia.agent import route as r

    async def real_route(message, **kwargs):
        return await r.route(message, **kwargs)

    s = Surface()
    deps = s.agent()
    deps = GraphDeps(**{**deps.__dict__, "route": real_route})
    history = [_u("¿Es normal que haga cacas verdes?"), _a("Sí, suele [ev_1].")]
    events, final = await _turn(deps, "Ha hecho 3 cacas hoy", history)
    assert final["kind"] == "confirm"
    assert [c["type"] for c in _cards(events)] == ["confirm"]


async def test_the_second_refusal_still_sends_her_to_the_pediatrician():
    s = Surface(evidence=())
    history = [_u(SPOTS), _a(ASKED_WHEN_NOTHING), _u("Hace una semana"),
               _a(no_evidence_reply("es") + "\n\nPara la consulta, esto es lo que me has contado:")]
    events, _ = await _turn(s.agent(), "Pero no se le quitan con nada", history)
    assert "pediatra" in _text(events).split("\n")[0]


async def test_the_chat_keeps_the_whole_refusal_every_time():
    s = Surface(evidence=())
    history = [_u(SPOTS), _a(no_evidence_reply("es"))]
    events, _ = await _turn(s.chat(), "Pero no se le quitan con nada", history)
    assert _text(events) == no_evidence_reply("es")


# --- the battery's gaps (2026-11-11) -------------------------------------------------
#
# scripts/conversation_battery.py marked 13 turns as known defects. The worst:
# after a referral for fever at 2 months, «le doy apiretal mientras» was
# answered as if the referral had never been said, because the guard read the
# new message alone.

from adelia.agent.route import route_by_rules  # noqa: E402
from adelia.services.answer_contract import (  # noqa: E402
    out_of_scope_reply,
    red_flag_opening,
    red_flag_reply,
)

AGE_2 = ProfileFacts(None, "Lucía", None, "F", 2)
FEVER_2M = "tiene 38,2 y no para de llorar"


class Rules(Surface):
    """The real routing rules; where they abstain, this surface's decision (the
    classifier's answer, or its fallback)."""

    async def route(self, message, **kwargs):
        self.calls.append(("route", message, kwargs))
        ruled = route_by_rules(message, locale=kwargs.get("locale", "es"),
                               has_account=kwargs.get("has_account", False),
                               facts=kwargs.get("facts"))
        return ruled or self.decision


@pytest.mark.parametrize("locale, first, then", [
    ("es", FEVER_2M, "le doy apiretal mientras"),
    ("es", FEVER_2M, "y si le baja?"),
    ("es", FEVER_2M, "puedo esperar a mañana?"),
    ("es", FEVER_2M, "lo baño con agua fria?"),
    ("fr", "mon bébé a 38,3", "il dort beaucoup aussi"),
    ("fr", "mon bébé a 38,3", "je lui donne du doliprane en attendant ?"),
])
async def test_after_a_referral_her_follow_up_gets_the_referral_again(locale, first, then):
    s = Surface()
    history = [_u(first), _a(red_flag_reply("fever_under_3_months", locale))]
    events, final = await _turn(s.agent(), then, history, facts=AGE_2, locale=locale)
    assert final["kind"] == "red_flag"
    assert final["flag"].code == "fever_under_3_months"
    assert _text(events).startswith(red_flag_opening(locale))
    assert s.calls == [], "no route, no retrieval, no model before the referral"
    assert not _cards(events)


async def test_the_referral_holds_on_its_own_code_when_her_words_alone_do_not_fire_it():
    s = Surface()
    history = [_u("lleva un rato raro"), _a(red_flag_reply("dehydration", "es"))]
    _, final = await _turn(s.agent(), "y le doy agua?", history, facts=AGE_2)
    assert final["kind"] == "red_flag" and final["flag"].code == "dehydration"
    assert s.calls == []


async def test_a_new_topic_she_marks_after_a_referral_is_routed_as_usual():
    s = Surface(intent="question")
    history = [_u(FEVER_2M), _a(red_flag_reply("fever_under_3_months", "es"))]
    _, final = await _turn(s.agent(), "otra cosa, cuantas tomas hace por la noche a esta edad",
                           history, facts=AGE_2)
    assert final["kind"] == "answer" and "route" in s.names()


async def test_after_noting_a_fever_her_question_is_routed_on_its_own():
    """«y q hago si sube mas» inherited the diary rule of the topic's first message
    and became a second card to note. The type of turn wins over that rule."""
    s = Rules(intent="question")
    history = [_u("ha tenido 38,4 a las 9"), _a("Anotado: 38,4 °C, hoy a las 9:00.")]
    events, final = await _turn(s.agent(), "y q hago si sube mas", history)
    assert final["intent"] == "plan" and final["kind"] == "answer"
    assert not [c for c in _cards(events) if c["type"] == "confirm"]
    _, routed, _ = s.one("route")
    assert routed == "y q hago si sube mas"


async def test_after_her_own_data_a_fact_question_is_not_the_tool_loop():
    s = Rules(intent="plan")
    history = [_u("que vacunas le tocan ahora"), _a("Le toca la triple vírica [ev_1].")]
    _, final = await _turn(s.agent(), "es normal q tenga fiebre despues de la vacuna", history)
    assert final["intent"] == "question" and "track" not in s.names()


async def test_a_follow_up_the_rules_cannot_place_does_not_inherit_the_diary_rule():
    s = Rules(intent="question", via="model")
    history = [_u("ha dormido 3 h de siesta"), _a("Anotado: siesta de 3 h, hoy.")]
    events, final = await _turn(s.agent(), "y eso es mucho", history)
    assert final["intent"] == "question"
    assert not [c for c in _cards(events) if c["type"] == "confirm"]


async def test_a_follow_up_still_reads_its_topic_when_her_message_alone_says_nothing():
    """«y por la noche» alone has no rule; with the topic it keeps reading as it did."""
    s = Rules(intent="question", via="model")
    _, _ = await _turn(s.agent(), "¿y por la noche?", [_u(SLEEP), _a(SLEEP_ANSWER)])
    _, routed, _ = s.one("route")
    assert routed == f"{SLEEP}\n¿y por la noche?"


async def test_an_adult_question_on_the_agent_gets_the_redirect_and_nothing_else():
    s = Surface(intent="other")
    events, final = await _turn(s.agent(), "yo tengo dolor de espalda desde el parto", [])
    assert final["kind"] == "no_evidence"
    assert _text(events) == out_of_scope_reply("es")
    assert s.names() == ["route"]
    assert not _cards(events) and final["evidence_citations"] == []


async def test_a_model_other_that_names_the_baby_is_answered_on_the_plan_path():
    s = Surface(intent="other", via="model")
    _, final = await _turn(s.agent(), "mi bebe y yo tenemos tos desde ayer", [])
    assert final["intent"] == "plan" and "retrieve" in s.names() and "track" not in s.names()


@pytest.mark.parametrize("message, shape", [
    ("is it ok to give him water", "question"),
    ("tiene mocos desde ayer", "plan"),
    ("hola, una cosa", "plan"),
])
async def test_with_the_classifier_down_the_agent_never_falls_into_the_tool_loop(message, shape):
    """The 429 of October: every turn the rules could not place went to the tool
    loop, with no answer contract. Now it is the sourced answer (or its clarify
    round), shaped by what the message looks like."""
    s = Surface(intent="plan", via="fallback")
    _, final = await _turn(s.agent(), message, [])
    assert final["intent"] == shape and "track" not in s.names()
    assert "retrieve" in s.names()


async def test_the_chat_keeps_the_plan_for_its_fallback_and_for_other():
    """The golden gate runs the chat without a model: its fallback stays the plan."""
    for intent, via in (("plan", "fallback"), ("other", "rule")):
        s = Surface(intent=intent, via=via)
        _, final = await _turn(s.chat(), "is it ok to give him water", [])
        assert final["intent"] == "plan" and final["kind"] == "answer"


@pytest.mark.parametrize("message", ["Lleva dos semanas, y en casa sí, me mira y sonríe",
                                     "y cuando me preocupo"])
async def test_a_behaviour_topic_after_its_round_is_the_plan_without_paying_the_router(message):
    """AGENT_GRAPH.md, `thread`: a behaviour worry asks first, then answers. After
    the round there is nothing left for the routing model to decide: the plan,
    with «Cuándo ir al médico», by rule (and also when the model is down)."""
    s = Surface(intent="question", via="model")
    history = [_u(GUARDERIA), _a(ASKED)]
    if message.startswith("y "):
        history += [_u("Menos de un mes · Sí, todo eso"), _a("Es la adaptación [ev_1].")]
    _, final = await _turn(s.agent(), message, history)
    assert final["intent"] == "plan" and final["intent_via"] == "rule"
    assert "route" not in s.names()


async def test_her_own_data_inside_a_behaviour_topic_still_goes_to_her_record():
    s = Rules(intent="question", via="model")
    history = [_u(GUARDERIA), _a(ASKED), _u("Menos de un mes · Sí, todo eso"),
               _a("Es la adaptación [ev_1].")]
    _, final = await _turn(s.agent(), "y en que percentil esta", history)
    assert final["intent"] == "track"


async def test_a_missing_symptom_is_asked_as_how_he_is_and_since_when():
    """The routing set and the classifier call it `symptom`: there is no button for
    a symptom, so the agent asks the two questions that make her say it."""
    s = Surface(intent="clarify", missing=["symptom"], via="model")
    events, final = await _turn(s.agent(), "le pasa algo pero no se que es", [])
    (card,) = _cards(events)
    assert [q["field"] for q in card["payload"]["questions"]] == ["general_state", "since_when"]
    assert final["kind"] == "clarify"


async def test_with_the_classifier_down_a_drug_said_earlier_in_the_topic_keeps_the_plan():
    s = Surface(intent="plan", via="fallback")
    _, final = await _turn(s.agent(), "¿y ahora?", [_u("¿le doy ibuprofeno?"),
                                                     _a("No tengo fuentes [ev_1].")])
    assert final["intent"] == "plan" and "track" not in s.names()
