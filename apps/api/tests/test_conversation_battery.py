"""The conversation battery (scripts/conversation_battery.py), 2026-11-10.

Santiago: "sigue mejorando, haz batería de pruebas completa, verifica la
usabilidad, la fluidez". Until now the conversation tests were single cases
(tests/test_conversation*.py). The battery is about thirty conversations of
two to five turns, written the way a mother in a hurry writes, each with what
every turn must do, and a figure: how many turns do it.

Pinned here:
  * the scenarios cover what he listed, in es (most), en and fr;
  * without a model (the default, and CI) every deterministic expectation
    holds, through the real graph with recorded fakes for what costs money;
  * each check catches what it is for (a dose, a second "no sources" in a
    topic, another topic's words reaching the model, a red flag that paid
    for something first);
  * the model mode never starts without `--with-model` and a budget, stops
    when the usage count reaches the budget, writes the whole transcript
    with time, tokens and cost per turn, and erases its QA guest even when a
    turn blows up.
"""
from __future__ import annotations

import io
import json
import sys
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import sqlalchemy as sa

from adelia import qa_traffic
from adelia.services import usage, usage_prices
from adelia.services.answer_contract import no_evidence_reply, red_flag_reply
from tests.pg_gate import PG_AVAILABLE

API_DIR = Path(__file__).parents[1]
sys.path.insert(0, str(API_DIR / "scripts"))
import conversation_battery as cb  # noqa: E402

needs_pg = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")


@pytest.fixture(autouse=True)
def _no_pinned_surface(monkeypatch):
    monkeypatch.delenv(usage.SURFACE_ENV, raising=False)


# --- 1. the scenarios ---------------------------------------------------------------


def test_about_thirty_conversations_of_two_to_five_turns_mostly_in_spanish():
    scenarios = cb.load_scenarios()

    assert 28 <= len(scenarios) <= 36
    assert len({s["id"] for s in scenarios}) == len(scenarios)
    langs = Counter(s["locale"] for s in scenarios)
    assert langs["es"] > len(scenarios) / 2 and langs["en"] >= 3 and langs["fr"] >= 3
    for s in scenarios:
        assert 2 <= len(s["turns"]) <= 5, s["id"]
        for turn in s["turns"]:
            expect = turn["expect"]
            assert expect["kind"] in cb.KINDS, s["id"]
            if not turn.get("confirm"):
                assert expect["turn"] in cb.TURN_TYPES, s["id"]


def test_the_scenarios_cover_every_topic_santiago_listed():
    tags = {t for s in cb.load_scenarios() for t in s["tags"]}

    assert {
        "fiebre", "fiebre_menor_3m", "sueño", "noche", "tomas", "complementaria",
        "guarderia", "conversacion_real", "desarrollo", "colico", "vomitos", "diarrea",
        "piel", "dientes", "estreñimiento", "vacunas", "golpe_cabeza", "anotar",
        "correccion_edad", "cambio_tema", "pregunta_vaga", "bandera_roja_a_mitad", "dosis",
        "fuera_de_edad", "adulto",
    } <= tags


def test_the_two_real_conversations_of_9_november_are_in_it_word_for_word():
    from tests.test_conversation import FEVER_NOTE, GUARDERIA

    said = {t.get("say") for s in cb.load_scenarios() for t in s["turns"]}

    assert {GUARDERIA, "Pero todos los días está así", "No es enfermo", FEVER_NOTE,
            "Es tema nuevo. No tiene fiebre ninads"} <= said


def test_mothers_write_in_a_hurry_short_and_mostly_without_question_marks():
    first = [s["turns"][0]["say"] for s in cb.load_scenarios() if s["turns"][0].get("say")]
    short = [t for t in first if len(t.split()) <= 14]
    bare = [t for t in first if "¿" not in t and "?" not in t]

    assert len(short) >= 0.7 * len(first)
    assert len(bare) >= 0.5 * len(first)


# --- 2. without a model -------------------------------------------------------------


async def test_without_a_model_every_turn_meets_what_is_expected_but_the_known_gaps():
    """A ratchet. Every turn meets what is expected, except the turns marked
    `gap` (a defect of the product the battery found, with its reason), and
    those must still fail: once one is fixed, the mark goes and the figure
    goes up; a turn that breaks fails here."""
    report = await cb.run_offline(cb.load_scenarios())

    turns = [(s["id"], t) for s in report["scenarios"] for t in s["turns"]]
    failing = [(sid, t["n"], [k for k, ok in t["checks"].items() if not ok])
               for sid, t in turns if not t["ok"] and not t.get("gap")]
    fixed = [(sid, t["n"]) for sid, t in turns if t["ok"] and t.get("gap")]
    assert failing == []
    assert fixed == [], "a known gap now passes: remove its `gap` mark"
    totals = report["totals"]
    assert totals["turns"] > 60 and totals["ok"] == totals["turns"] - totals["gaps"]
    assert 0 < totals["gaps"] <= 15
    assert report["mode"] == "offline"


async def test_the_report_counts_what_the_rules_decide_alone():
    """Where the routing rules abstain, production asks the classifier; when it
    is down (429 in October) the turn falls to the tool loop. The offline run
    plays the classifier's recorded answer and says how many turns needed it."""
    report = await cb.run_offline(cb.load_scenarios())

    via = Counter(t.get("intent_via") for s in report["scenarios"] for t in s["turns"])
    assert report["totals"]["needs_classifier"] == via["recorded"] > 0
    assert via["fallback"] == 0, "a turn the rules cannot place has no recorded answer"
    text = cb.render_text(report)
    assert "clasificador" in text and "defecto conocido" in text
    assert "—" not in text


async def test_the_offline_run_touches_no_database_and_no_provider(monkeypatch):
    def _boom(*_, **__):
        raise AssertionError("the offline battery must not open a session")

    monkeypatch.setattr("adelia.db.AsyncSessionLocal", _boom)
    monkeypatch.setattr("adelia.agent.graph.AsyncSessionLocal", _boom)
    counted: list = []
    monkeypatch.setattr(usage, "count", lambda *a, **k: counted.append(a))

    report = await cb.run_offline(cb.load_scenarios()[:5])

    assert report["totals"]["turns"] > 0 and counted == []


async def test_a_red_flag_in_the_middle_comes_first_and_pays_for_nothing():
    (scenario,) = [s for s in cb.load_scenarios() if "bandera_roja_a_mitad" in s["tags"]][:1]
    report = await cb.run_offline([scenario])

    flagged = [t for t in report["scenarios"][0]["turns"] if t["kind"] == "red_flag"]
    assert flagged and all(t["paid"] == [] and t["checks"]["red_flag_first"] for t in flagged)


# --- 3. the checks catch what they are for -----------------------------------------


@pytest.mark.parametrize("text", [
    "Dale 15 mg/kg de paracetamol cada 6 horas",
    "Puedes darle 2,5 ml de Apiretal",
    "Give 120 mg of paracetamol",
    "Donne-lui 5 gouttes de Doliprane",
])
def test_a_dose_is_caught(text):
    assert cb.has_dose(text)


@pytest.mark.parametrize("text", [
    "A los 6 meses, unos 500 a 600 ml de leche al día [ev_1].",
    "Si tiene más de 38 °C, llama al pediatra.",
    "No te puedo dar una dosis: pregúntalo a tu pediatra.",
])
def test_milk_a_temperature_or_declining_a_dose_is_not_a_dose(text):
    assert not cb.has_dose(text)


def _observed(**over) -> dict:
    base = {"turn_type": "new", "kind": "answer", "intent": "question", "asks": [],
            "answer": "Respuesta [ev_1].", "cards": [], "paid": ["route", "retrieve", "stream"],
            "model_saw": {"system": "", "user": "pregunta", "history": []}, "error": None}
    base.update(over)
    return base


def test_the_refusal_said_twice_in_a_topic_fails_the_second_turn():
    refusal = no_evidence_reply("es")
    scenario = {"id": "x", "locale": "es", "turns": [
        {"say": "a", "expect": {"turn": "new", "kind": "no_evidence"}},
        {"say": "b", "expect": {"turn": "follow_up", "kind": "no_evidence"}},
    ]}
    observed = [
        _observed(kind="no_evidence", answer=refusal),
        _observed(turn_type="follow_up", kind="no_evidence", answer=refusal),
    ]

    turns = cb.evaluate(scenario, observed, mode="offline")

    assert turns[0]["checks"]["refusal_once"] and not turns[1]["checks"]["refusal_once"]


def test_another_topic_reaching_the_model_fails():
    scenario = {"id": "x", "locale": "es", "turns": [
        {"say": "huevo", "expect": {"turn": "new", "kind": "answer", "not_seen": ["38,7"]}},
    ]}
    leaked = _observed(model_saw={"system": "", "user": "huevo",
                                  "history": [{"role": "assistant", "content": "38,7 °C"}]})

    (turn,) = cb.evaluate(scenario, [leaked], mode="offline")

    assert not turn["checks"]["no_other_topic"] and not turn["ok"]


def test_a_red_flag_that_paid_for_routing_first_fails():
    scenario = {"id": "x", "locale": "es", "turns": [
        {"say": "morado", "expect": {"turn": "new", "kind": "red_flag"}},
    ]}
    late = _observed(kind="red_flag", answer=red_flag_reply("cyanosis", "es"), paid=["route"])

    (turn,) = cb.evaluate(scenario, [late], mode="offline")

    assert not turn["checks"]["red_flag_first"]


def test_a_plan_without_the_doctor_section_fails_with_the_model():
    scenario = {"id": "x", "locale": "es", "turns": [
        {"say": "fiebre", "expect": {"turn": "new", "kind": "answer", "shape": "plan",
                                     "doctor": True}},
    ]}
    plan = _observed(intent="plan", answer="## Hoy\n- Agua [ev_1].", model_saw=None)

    (turn,) = cb.evaluate(scenario, [plan], mode="model")

    assert not turn["checks"]["doctor"]
    assert turn["checks"]["shape"]


# --- 4. the model mode: the option, the budget, the guest ----------------------------


def test_the_model_mode_never_starts_without_the_option(monkeypatch, capsys):
    started: list = []

    async def _model(*_, **__):
        started.append(True)
        return {}

    monkeypatch.setattr(cb, "run_with_model", _model)
    monkeypatch.setattr(cb, "load_scenarios", lambda *_a, **_k: [])

    assert cb.main([]) == 0
    assert cb.main(["--budget-usd", "2"]) == 2
    assert cb.main(["--with-model"]) == 2
    assert cb.main(["--with-model", "--budget-usd", "0"]) == 2
    assert cb.main(["--with-model", "--budget-usd", str(cb.MAX_BUDGET_USD + 1)]) == 2
    assert started == []


def _spending_turn(cost_tokens: int = 10_000):
    """A fake dashboard turn that spends: 10k input tokens of Opus 5.5 is 0.04 $."""
    async def _turn(guest, scenario, request):
        usage.count("agent_step", "anthropic", "claude-opus-5-5", input_tokens=cost_tokens)
        return _observed(answer="Respuesta [ev_1].", model_saw=None)
    return _turn


@asynccontextmanager
async def _fake_guest(locale="es"):
    yield cb.Guest(user_id=uuid.uuid4(), profile_id=uuid.uuid4())


async def test_the_model_run_stops_when_the_counted_spend_reaches_the_budget(monkeypatch):
    async def _record(*_, **__):
        return None

    monkeypatch.setattr(usage, "record", _record)
    scenarios = [s for s in cb.load_scenarios() if len(s["turns"]) >= 3][:3]

    report = await cb.run_with_model(
        scenarios, budget_usd=0.1, turn_runner=_spending_turn(), guest=_fake_guest,
        set_age=_no_age,
    )

    assert report["stopped"] == "budget"
    assert report["totals"]["turns_run"] == 2
    assert report["spent_usd"] == pytest.approx(0.08)
    assert report["spent_usd"] <= 0.1
    not_run = [t for s in report["scenarios"] for t in s["turns"] if t.get("skipped")]
    assert not_run and all(t["skipped"] == "budget" for t in not_run)


async def _no_age(guest, age_months):
    return None


async def test_a_call_without_a_price_counts_at_the_dearest_known_price(monkeypatch):
    """mistral-medium-latest, the default chat model, has no official price
    (usage_prices.json). Stopping on it would end every real run after one
    turn; guessing low would let the cap leak. Its tokens count at the
    dearest price known for each column, so the cap holds as an upper bound."""
    async def _record(*_, **__):
        return None

    async def _unpriced(guest, scenario, request):
        usage.count("chat", "mistral", "a-model-nobody-priced", input_tokens=10_000)
        return _observed(model_saw=None)

    monkeypatch.setattr(usage, "record", _record)
    scenarios = [s for s in cb.load_scenarios() if len(s["turns"]) >= 3][:3]
    report = await cb.run_with_model(
        scenarios, budget_usd=0.1, turn_runner=_unpriced, guest=_fake_guest, set_age=_no_age,
    )

    assert report["stopped"] == "budget" and report["totals"]["turns_run"] == 2
    assert report["spent_usd"] == pytest.approx(0.08)  # 10k tokens at 4 $ per million
    assert report["list_usd"] == 0
    assert report["unpriced"] == ["mistral/a-model-nobody-priced"]
    turn = report["scenarios"][0]["turns"][0]
    assert turn["cost_usd"] == pytest.approx(0.04) and turn["cost_is_upper_bound"]


async def test_a_call_no_known_price_can_bound_stops_the_run(monkeypatch):
    async def _record(*_, **__):
        return None

    async def _audio(guest, scenario, request):
        usage.count("transcribe", "mistral", "a-model-nobody-priced", audio_seconds=60)
        return _observed(model_saw=None)

    monkeypatch.setattr(usage, "record", _record)
    monkeypatch.setattr(usage_prices, "PRICES", {
        k: v for k, v in usage_prices.PRICES.items() if not v.per_audio_minute})
    report = await cb.run_with_model(
        cb.load_scenarios()[:2], budget_usd=1, turn_runner=_audio, guest=_fake_guest,
        set_age=_no_age,
    )

    assert report["stopped"] == "unpriced" and report["totals"]["turns_run"] == 1


async def test_every_model_turn_is_test_traffic_and_its_cost_is_in_the_transcript(monkeypatch):
    labels: list[str] = []

    async def _record(operation, provider, model, *, surface=None, **_):
        labels.append(surface)

    monkeypatch.setattr(usage, "record", _record)
    seen_qa: list[bool] = []

    async def _turn(guest, scenario, request):
        seen_qa.append(qa_traffic.is_qa())
        usage.count("agent_step", "anthropic", "claude-opus-5-5", input_tokens=1000,
                    output_tokens=100)
        return _observed(answer="Una respuesta corta de cinco palabras [ev_1].",
                         model_saw=None, ttft_s=0.4, total_s=1.2)

    scenario = cb.load_scenarios()[0]
    report = await cb.run_with_model([scenario], budget_usd=1, turn_runner=_turn,
                                     guest=_fake_guest, set_age=_no_age)
    await usage.drain()

    assert seen_qa and all(seen_qa) and set(labels) == {"qa"}
    turn = report["scenarios"][0]["turns"][0]
    assert turn["tokens"]["input_tokens"] == 1000 and turn["tokens"]["output_tokens"] == 100
    assert turn["cost_usd"] == pytest.approx(0.006)  # 1000 * 4 + 100 * 20, per million
    assert turn["words"] == 6 and turn["ttft_s"] == 0.4 and turn["total_s"] == 1.2
    assert turn["mother"] == scenario["turns"][0]["say"]
    summary = report["totals"]
    assert summary["words_median"] == 6 and summary["ttft_median_s"] == 0.4
    json.dumps(report)


@needs_pg
async def test_the_qa_guest_is_erased_even_when_a_turn_blows_up():
    from adelia.db import AsyncSessionLocal
    from adelia.models import Profile, User

    made: list[cb.Guest] = []

    async def _boom(guest, scenario, request):
        made.append(guest)
        raise RuntimeError("the provider fell over")

    with pytest.raises(RuntimeError):
        await cb.run_with_model(cb.load_scenarios()[:1], budget_usd=1, turn_runner=_boom)

    (guest,) = made
    async with AsyncSessionLocal() as session:
        assert await session.get(User, guest.user_id) is None
        assert await session.scalar(
            sa.select(sa.func.count()).select_from(Profile)
            .where(Profile.user_id == guest.user_id)) == 0


@needs_pg
async def test_the_qa_guest_is_a_marked_guest_and_takes_the_scenario_age():
    from adelia.db import AsyncSessionLocal
    from adelia.enrichment.profile_service import load_profile_facts
    from adelia.models import User

    out = io.StringIO()
    async with cb.qa_guest("es", out=out) as guest:
        async with AsyncSessionLocal() as session:
            user = await session.get(User, guest.user_id)
            assert user.is_guest and user.email.startswith(qa_traffic.GUEST_EMAIL_PREFIX)
        await cb.set_guest_age(guest, 2)
        assert (await load_profile_facts(user_id=guest.user_id,
                                         profile_id=guest.profile_id)).age_months == 2
        await cb.set_guest_age(guest, 18)
        assert (await load_profile_facts(user_id=guest.user_id,
                                         profile_id=guest.profile_id)).age_months == 18
    async with AsyncSessionLocal() as session:
        assert await session.get(User, guest.user_id) is None
    assert "erased" in out.getvalue()


@needs_pg
async def test_a_real_dashboard_turn_reports_what_the_graph_decided():
    """The default turn runner is orchestrator.run_turn, the panel's path. A red
    flag needs no key, so this runs in CI too."""
    async with cb.qa_guest("es", out=io.StringIO()) as guest:
        await cb.set_guest_age(guest, 1)
        with qa_traffic.marked():
            observed = await cb.dashboard_turn(
                guest, {"locale": "es"},
                {"message": "tiene 38,3 de fiebre", "history": []},
            )
    assert observed["kind"] == "red_flag" and observed["turn_type"] == "new"
    assert observed["answer"].startswith(red_flag_reply("fever_under_3_months", "es")[:20])
    assert observed["error"] is None and observed["total_s"] >= observed["ttft_s"] >= 0
