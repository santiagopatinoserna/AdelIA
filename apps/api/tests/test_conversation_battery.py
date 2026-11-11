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

import asyncio
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


HOLDOUT = "control_sobreajuste"


def test_about_thirty_conversations_of_two_to_five_turns_mostly_in_spanish():
    everything = cb.load_scenarios()
    scenarios = [s for s in everything if HOLDOUT not in s["tags"]]

    assert 28 <= len(scenarios) <= 36
    assert len({s["id"] for s in everything}) == len(everything)
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
    # Every gap of 2026-11-10 was fixed on 2026-11-11; the ratchet itself is
    # pinned with a scenario of its own below.
    assert 0 <= totals["gaps"] <= 15
    assert report["mode"] == "offline"


REGRESSIONS = Path(cb.__file__).with_name("conversation_regressions.json")


async def test_the_sixteen_turns_that_failed_with_the_real_model_pass_without_it():
    """The battery with the real model in production (2026-11-11) stopped at its
    2 $ cap after 57 of 110 turns: 41 met what was expected, 16 did not. Their
    conversations are scripts/conversation_regressions.json, replayed without a
    model: the real classifier's decision on each turn it was asked, whether the
    search found evidence and her record, and the model's real answer as the
    history the next turn reads. On main they gave 20 of 32."""
    report = await cb.run_offline(cb.load_scenarios(REGRESSIONS))

    failing = [(s["id"], t["n"], [k for k, ok in t["checks"].items() if not ok])
               for s in report["scenarios"] for t in s["turns"] if not t["ok"]]
    assert failing == []
    assert report["totals"]["turns"] == 32


def test_each_regression_keeps_what_production_did():
    data = json.loads(REGRESSIONS.read_text(encoding="utf-8"))
    failed = [f for s in data["scenarios"] for t in s["turns"] for f in t["real"]["failed"]]
    turns = [t for s in data["scenarios"] for t in s["turns"]]
    assert sum(1 for t in turns if t["real"]["failed"]) == 16
    assert Counter(failed) == {"doctor": 7, "refusal_once": 7, "turn": 2, "kind": 2}
    for t in turns:
        if t["real"]["intent_via"] == "model":
            assert t["classifier"] == {"intent": t["real"]["intent"],
                                       "turn": t["real"]["turn_type"]}
        if t["real"]["intent_via"] == "fallback":
            assert t["classifier"] == "down"


def test_six_control_conversations_written_before_the_fixes_of_2026_11_11():
    """The overfitting control: six conversations written before reading the
    code of the fixes for the battery's gaps, in the three languages, with
    turns where the classifier is down."""
    holdout = [s for s in cb.load_scenarios() if HOLDOUT in s["tags"]]

    assert len(holdout) == 6
    assert {s["locale"] for s in holdout} == {"es", "en", "fr"}
    assert any(t.get("classifier") == "down" for s in holdout for t in s["turns"])


def test_a_gap_that_passes_is_reported_and_fails_the_run(monkeypatch):
    scenario = {"id": "x", "locale": "es", "age_months": 8, "tags": [], "turns": [
        {"say": "Se ha puesto morado", "expect": {"turn": "new", "kind": "red_flag"},
         "gap": "un defecto ya arreglado"},
    ]}
    report = asyncio.run(cb.run_offline([scenario]))

    assert report["totals"]["gaps_fixed"] == 1
    monkeypatch.setattr(cb, "load_scenarios", lambda *_a, **_k: [scenario])
    out = io.StringIO()
    assert cb.main([], out=out) == 1
    assert "quita su marca" in out.getvalue()


async def test_a_turn_marked_classifier_down_takes_the_fallback_and_says_so():
    scenario = {"id": "x", "locale": "en", "age_months": 9, "tags": [], "turns": [
        {"say": "is it ok to give him water", "classifier": "down",
         "expect": {"turn": "new", "kind": "answer", "shape": "question"}},
    ]}
    report = await cb.run_offline([scenario])

    (turn,) = report["scenarios"][0]["turns"]
    assert turn["intent_via"] == "down" and turn["ok"]
    assert "track" not in turn["paid"]
    assert report["totals"]["classifier_down"] == 1 and report["totals"]["fallback"] == 0


async def test_with_the_classifier_down_no_turn_falls_into_the_tool_loop():
    """The 429 of October: every turn the rules could not place went to the
    agent's tool loop. With `classifier_down` the whole battery plays that day."""
    scenarios = cb.load_scenarios()
    report = await cb.run_offline(scenarios, classifier_down=True)

    turns = [(s, t) for s in report["scenarios"] for t in s["turns"]]
    loop = [(s["id"], t["n"]) for s, t in turns
            if "track" in (t.get("paid") or []) and t.get("intent_via") != "rule"]
    assert loop == []
    expected = {(s["id"], n): turn["expect"]["kind"] for s in scenarios
                for n, turn in enumerate(s["turns"], start=1)}
    flags = [(s["id"], t["n"]) for s, t in turns if expected[(s["id"], t["n"])] == "red_flag"]
    assert flags and all(t["kind"] == "red_flag" for s, t in turns
                         if (s["id"], t["n"]) in flags)
    assert report["totals"]["classifier_down"] > 0
    assert report["classifier_down"] is True
    assert "clasificador caído" in cb.render_text(report)


def test_the_classifier_down_run_is_an_option(monkeypatch):
    seen: list = []

    async def _offline(scenarios, *, classifier_down=False):
        seen.append(classifier_down)
        return {"mode": "offline", "classifier_down": classifier_down, "scenarios": [],
                "totals": cb._totals([])}

    monkeypatch.setattr(cb, "run_offline", _offline)
    monkeypatch.setattr(cb, "load_scenarios", lambda *_a, **_k: [])

    cb.main(["--classifier-down"], out=io.StringIO())
    cb.main([], out=io.StringIO())
    assert seen == [True, False]


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


async def test_a_model_turn_records_when_each_stage_began(monkeypatch):
    """The battery with the real model gave only the time to the first word and
    to the end; the next run says how long the search and the routing took."""
    from adelia.agent import orchestrator
    from adelia.agent.events import AgentEvent

    async def fake_run_turn(**kwargs):
        yield AgentEvent(type="status", content="searching")
        await asyncio.sleep(0.01)
        yield AgentEvent(type="status", content="writing", sources=2)
        await asyncio.sleep(0.01)
        yield AgentEvent(type="token", content="Hola")
        yield AgentEvent(type="final")

    monkeypatch.setattr(orchestrator, "run_turn", fake_run_turn)
    guest = cb.Guest(user_id=uuid.uuid4(), profile_id=uuid.uuid4())
    o = await cb.dashboard_turn(guest, {"locale": "es"}, {"message": "hola", "history": []})
    assert set(o["stages_s"]) == {"searching", "writing"}
    assert 0 <= o["stages_s"]["searching"] <= o["stages_s"]["writing"] <= o["ttft_s"]
    assert o["sources_found"] == 2


# --- running only part of it (the 2 $ cap stopped at 57 of 110, 2026-11-11) ----------


def test_from_starts_at_a_scenario_and_tag_keeps_its_topic():
    scenarios = cb.load_scenarios()
    ids = [s["id"] for s in scenarios]
    start = ids.index("anotar-sueño")

    picked = cb.select_scenarios(scenarios, start="anotar-sueño")
    assert [s["id"] for s in picked] == ids[start:]
    fr = cb.select_scenarios(scenarios, tags=["fiebre"])
    assert fr and all("fiebre" in s["tags"] for s in fr)
    both = cb.select_scenarios(scenarios, only=["dientes", "vacunas"], tags=["dientes"])
    assert [s["id"] for s in both] == ["dientes"]
    with pytest.raises(ValueError):
        cb.select_scenarios(scenarios, start="no-existe")


def _previous_run(stopped_at: str) -> dict:
    """A model report like the one of 2026-11-11: whole scenarios, then skips."""
    out, stop = [], False
    for s in cb.load_scenarios():
        stop = stop or s["id"] == stopped_at
        turns = [({"n": n, "ok": False, "skipped": "budget", "checks": {}} if stop else
                  {"n": n, "ok": True, "checks": {"kind": True}, "kind": "answer",
                   "words": 100, "ttft_s": 7.0, "total_s": 8.5, "cost_usd": 0.03})
                 for n in range(1, len(s["turns"]) + 1)]
        out.append({"id": s["id"], "locale": s["locale"], "age_months": s.get("age_months"),
                    "tags": s.get("tags", []), "turns": turns,
                    "ok": 0 if stop else len(turns), "total": len(turns)})
    return {"mode": "model", "spent_usd": 1.93, "scenarios": out}


async def test_resume_runs_only_what_the_last_run_did_not_measure(monkeypatch):
    """`--resume <report.json>`: the scenarios that ran whole are carried over
    as they were and not paid again; the one it stopped in and the rest run.
    A half-run scenario runs from its first turn: its guest is gone and the
    answers of its first turns are the next turns' history."""
    async def _record(*_, **__):
        return None

    monkeypatch.setattr(usage, "record", _record)
    previous = _previous_run("anotar-sueño")
    scenarios = cb.load_scenarios()
    todo = cb.not_yet_measured(scenarios, previous)
    ran = {s["id"] for s in todo}
    assert "anotar-sueño" in ran and "guarderia-real-9nov-1" not in ran
    assert sum(len(s["turns"]) for s in todo) == 53

    seen: list[str] = []

    async def _turn(guest, scenario, request):
        seen.append(scenario["id"])
        return _observed(answer="Respuesta [ev_1].", model_saw=None)

    report = await cb.run_with_model(
        todo, budget_usd=1, turn_runner=_turn, guest=_fake_guest, set_age=_no_age,
        carried=previous,
    )
    assert set(seen) == ran
    assert [s["id"] for s in report["scenarios"]] == [s["id"] for s in scenarios]
    carried = [s for s in report["scenarios"] if s.get("carried")]
    assert {s["id"] for s in carried} == {s["id"] for s in scenarios} - ran
    assert report["totals"]["turns_run"] == 110
    assert report["previous_spent_usd"] == pytest.approx(1.93)


def test_resume_is_an_option_and_needs_a_model_report(tmp_path, monkeypatch, capsys):
    offline = tmp_path / "offline.json"
    offline.write_text(json.dumps({"mode": "offline", "scenarios": []}), encoding="utf-8")
    assert cb.main(["--with-model", "--budget-usd", "1", "--resume", str(offline)]) == 2
    assert "nothing was run" in capsys.readouterr().err
    assert cb.main(["--resume", str(offline)]) == 2


# --- comparing the answer settings on and off (2026-11-11, round 3) --------------------
#
# settings.answer_effort_* and settings.follow_up_brevity are measured by running the
# regressions with the model twice, without and with them. Each report says which
# settings it ran with, what contract and effort each turn got, and the words and
# time of the follow-ups to an answered topic apart, which is what they change.

REGRESSIONS_2 = Path(cb.__file__).with_name("conversation_regressions_2.json")


async def test_a_model_report_says_which_answer_settings_it_ran_with(monkeypatch):
    from adelia.config import settings

    async def _record(*_, **__):
        return None

    monkeypatch.setattr(usage, "record", _record)
    monkeypatch.setattr(settings, "follow_up_brevity", True)
    monkeypatch.setattr(settings, "answer_effort_follow_up", "low")
    report = await cb.run_with_model(
        cb.load_scenarios()[:1], budget_usd=1, turn_runner=_spending_turn(100),
        guest=_fake_guest, set_age=_no_age,
    )
    assert report["settings"]["follow_up_brevity"] is True
    assert report["settings"]["answer_effort_follow_up"] == "low"
    assert report["settings"]["answer_effort_plan"] is None
    assert {"plan_brevity", "no_unasked_refusals", "answer_effort_question"} <= set(
        report["settings"])


def test_each_turn_says_its_contract_its_effort_and_whether_it_follows_an_answer():
    from adelia.agent import conversation as conv

    c = conv.read("y si le doy zumo de pera", [
        {"role": "user", "content": "lleva 4 dias sin hacer caca"},
        {"role": "assistant", "content": "No es necesariamente un problema [ev_1]."}])
    o = cb._from_final({"conversation": c, "kind": "answer", "intent": "plan",
                        "shape": "follow_up", "effort": "low"})
    assert (o["shape"], o["effort"], o["follows_answer"]) == ("follow_up", "low", True)
    assert cb._from_final({"kind": "red_flag"})["follows_answer"] is False


def test_the_totals_give_the_follow_ups_to_an_answer_apart():
    turns = [
        {"ok": True, "words": 200, "ttft_s": 15.0, "total_s": 20.0, "follows_answer": False},
        {"ok": True, "words": 60, "ttft_s": 5.0, "total_s": 6.0, "follows_answer": True},
        {"ok": True, "words": 80, "ttft_s": 7.0, "total_s": 8.0, "follows_answer": True},
    ]
    results = [{"id": "x", "turns": turns, "ok": 3, "total": 3}]
    t = cb._totals(results, run_turns=turns)
    assert t["follow_ups_to_an_answer"] == 2
    assert t["words_follow_up_median"] == 70
    assert t["ttft_follow_up_median_s"] == 6.0
    assert t["words_median"] == 80
    assert "Seguimientos de un tema ya respondido: 2" in cb.render_text(
        {"mode": "model", "totals": {**t, "turns": 3, "scenarios": 1}, "scenarios": [],
         "spent_usd": 0.1, "budget_usd": 1.0, "list_usd": 0.1, "stopped": None})


async def test_offline_the_effort_the_graph_asked_for_reaches_the_fake_model(monkeypatch):
    from adelia.config import settings

    monkeypatch.setattr(settings, "answer_effort_plan", "low")
    scenario = {"id": "x", "locale": "es", "age_months": 5, "tags": [], "turns": [
        {"say": "lleva 4 dias sin hacer caca", "expect": {"turn": "new", "kind": "answer"}}]}
    report = await cb.run_offline([scenario])
    (turn,) = report["scenarios"][0]["turns"]
    assert turn["ok"] and turn["effort"] == "low" and turn["shape"] == "plan"


async def test_the_six_failures_of_the_replay_pass_without_the_model():
    """battery-regr-20261111-0408.json: 26 of 32. Three conversations failed on
    the code (piel-granitos, estreñimiento, guarderia-botones, turn 3): they are
    scripts/conversation_regressions_2.json as production played them, every
    follow-up's search with its sources found. The other three (guarderia-real-
    9nov-1 turn 3, no-gatea and golpe-en-la-cabeza turn 1) are searches that did
    not bring the guide the corpus holds; they are already in
    conversation_regressions.json with the same classifier decisions."""
    report = await cb.run_offline(cb.load_scenarios(REGRESSIONS_2))
    failing = [(s["id"], t["n"], [k for k, ok in t["checks"].items() if not ok])
               for s in report["scenarios"] for t in s["turns"] if not t["ok"]]
    assert failing == []
    assert [s["id"] for s in report["scenarios"]] == [
        "real2-guarderia-botones", "real2-piel-granitos", "real2-estreñimiento"]
    piel = report["scenarios"][1]["turns"]
    assert [t["kind"] for t in piel] == ["clarify", "no_evidence", "no_evidence"]


def test_the_replay_keeps_what_production_did():
    data = json.loads(REGRESSIONS_2.read_text(encoding="utf-8"))
    turns = [t for s in data["scenarios"] for t in s["turns"]]
    assert sum(1 for t in turns if t["real"]["failed"]) == 3
    for t in turns:
        if t["real"]["intent_via"] == "model":
            assert t["classifier"]["intent"] == t["real"]["intent"]
            assert t["classifier"]["turn"] == t["real"]["turn_type"]
        if t["real"]["intent_via"] == "fallback":
            assert t["classifier"] == "down"
        if t["real"].get("sources_found"):
            assert t["evidence"] is True


# --- the three search failures of #73 (2026-11-11, round 4) ----------------------------
#
# battery-regr-20261111-0408.json left three turns that failed on the search, not the
# code: the bump on the head (SEUP's sheet did not come), «no gatea» (UNICEF alone) and
# the guardería topic after «No es enfermo» (no development warning signs). Without a
# model the search is a fake, so a turn says what the account search must ADD to her
# words (`search_adds`: the lexicon's terms, the development words) and, with the
# model, which sources the answering model must be handed (`found`).

REGRESSIONS_3 = Path(cb.__file__).with_name("conversation_regressions_3.json")


async def test_the_three_search_failures_pass_without_the_model():
    report = await cb.run_offline(cb.load_scenarios(REGRESSIONS_3))
    failing = [(s["id"], t["n"], [k for k, ok in t["checks"].items() if not ok])
               for s in report["scenarios"] for t in s["turns"] if not t["ok"]]
    assert failing == []
    checked = [t for s in report["scenarios"] for t in s["turns"]
               if "search_adds" in t["checks"]]
    assert len(checked) >= 6


def test_each_search_regression_says_what_production_missed_and_what_must_come():
    data = json.loads(REGRESSIONS_3.read_text(encoding="utf-8"))
    ids = [s["id"] for s in data["scenarios"]]
    assert {"real3-golpe-en-la-cabeza", "real3-no-gatea", "real3-guarderia-real-9nov-1"} <= set(
        ids)
    missed = [t for s in data["scenarios"] for t in s["turns"] if t.get("real", {}).get("failed")]
    # golpe T1, no-gatea T1, guardería T2 and T3: each says what was missed and
    # what the search must add and bring now.
    assert len(missed) == 4
    for t in missed:
        assert t["expect"].get("search_adds") and t["expect"].get("found"), t["say"]
    for s in data["scenarios"]:
        for t in s["turns"]:
            if t.get("real", {}).get("intent_via") == "model":
                assert t["classifier"]["intent"] == t["real"]["intent"]


def test_offline_a_search_that_does_not_add_the_corpus_words_fails():
    scenario = {"locale": "es", "turns": [
        {"expect": {"kind": "answer", "search_adds": ["traumatismo craneal"]}}]}
    good = {"kind": "answer", "searched": ["se ha dado en la cabeza\ntraumatismo craneal"]}
    bad = {"kind": "answer", "searched": []}
    assert cb.evaluate(scenario, [good], mode="offline")[0]["checks"]["search_adds"] is True
    assert cb.evaluate(scenario, [bad], mode="offline")[0]["checks"]["search_adds"] is False
    # With the model the real search speaks for itself (`found`).
    assert "search_adds" not in cb.evaluate(scenario, [bad], mode="model")[0]["checks"]


def test_with_the_model_found_reads_what_the_answering_model_was_handed():
    scenario = {"locale": "es", "turns": [
        {"expect": {"kind": "answer", "found": ["Traumatismo craneal.*SEUP"]}}]}
    handed = {"kind": "answer",
              "handed": ["Accidentes infantiles", "Traumatismo craneal, información para "
                         "padres (SEUP)"]}
    missed = {"kind": "answer", "handed": ["Cuidado con las caídas de los niños"]}
    assert cb.evaluate(scenario, [handed], mode="model")[0]["checks"]["found"] is True
    assert cb.evaluate(scenario, [missed], mode="model")[0]["checks"]["found"] is False
    # Offline the fragment is a fake: nothing to read.
    assert "found" not in cb.evaluate(scenario, [missed], mode="offline")[0]["checks"]


def test_a_turn_reports_the_titles_the_answering_model_was_handed():
    from tests.test_chat_orchestrator import _evidence_match

    o = cb._from_final({"kind": "answer", "evidence": [_evidence_match()]})
    assert o["handed"] == ["Reflujo (GER) vs enfermedad por reflujo (GERD)"]
    assert cb._from_final({"kind": "red_flag"})["handed"] == []


async def test_offline_the_fake_search_records_what_the_account_search_would_add():
    """With the lexicon (on in production) and the development search, whatever
    this process's settings say: offline checks the code that decides, not the
    environment it runs in."""
    def _one(say: str) -> dict:
        return {"id": say, "locale": "es", "age_months": 10, "tags": [], "turns": [
            {"say": say, "classifier": {"intent": "plan", "turn": "new"},
             "expect": {"turn": "new", "kind": "answer"}}]}

    report = await cb.run_offline([_one("se ha caido de la cama y se ha dado en la cabeza"),
                                   _one("no gatea y ya tiene 10 meses")])
    (head,), (crawl,) = [s["turns"] for s in report["scenarios"]]
    assert any("traumatismo craneal" in s for s in head["searched"])
    assert not any("signos de alarma" in s for s in head["searched"])
    assert any("signos de alarma" in s for s in crawl["searched"])


# --- round 5: the resumed run of 2026-11-11, 17:04 (battery-resume-20261111-1704) ----
#
# 86 of 110 turns, but the 53 run today and the 57 carried from the morning were
# measured on different code and settings; the report now gives this run apart.
# Four of today's turns ended in Mistral's 429 on the search's embedding:
# scripts/conversation_regressions_4.json replays them without a model, the
# provider's refusal included (`search_fails`). Six turns took the classifier's
# fallback and the report could not say why: each turn now keeps how long routing
# took and the fallback's reason.

REGRESSIONS_4 = Path(cb.__file__).with_name("conversation_regressions_4.json")


def _say(text: str, **turn) -> dict:
    return {"say": text, **turn}


async def test_offline_a_search_the_provider_refuses_once_is_answered(monkeypatch):
    from adelia.agent import graph

    monkeypatch.setattr(graph, "SEARCH_RETRY_PAUSE_S", 0)
    scenario = {"id": "x", "locale": "es", "age_months": 8, "tags": [], "turns": [
        _say("tiene mocos desde ayer", search_fails=1, classifier={"intent": "plan"},
             expect={"turn": "new", "kind": "answer"})]}
    report = await cb.run_offline([scenario])
    (turn,) = report["scenarios"][0]["turns"]
    assert turn["ok"] and turn["error"] is None


async def test_offline_a_turn_that_raises_is_a_failed_turn_not_a_crashed_run(monkeypatch):
    """run_turn turns an exception into the panel's error frame; offline does the same,
    so the turn fails with `no_error` and the next scenario still runs."""
    from adelia.agent import graph

    monkeypatch.setattr(graph, "SEARCH_RETRY_PAUSE_S", 0)
    broken = {"id": "x", "locale": "es", "age_months": 8, "tags": [], "turns": [
        _say("tiene mocos desde ayer", search_fails=2, classifier={"intent": "plan"},
             expect={"turn": "new", "kind": "answer"})]}
    fine = {"id": "y", "locale": "es", "age_months": 8, "tags": [], "turns": [
        _say("tiene mocos desde ayer", classifier={"intent": "plan"},
             expect={"turn": "new", "kind": "answer"})]}
    report = await cb.run_offline([broken, fine])
    (bad,), (good,) = [s["turns"] for s in report["scenarios"]]
    assert bad["ok"] is False and bad["checks"]["no_error"] is False
    assert "429" in bad["error"]
    assert good["ok"]


async def test_the_four_turns_the_provider_refused_pass_without_the_model(monkeypatch):
    from adelia.agent import graph

    monkeypatch.setattr(graph, "SEARCH_RETRY_PAUSE_S", 0)
    report = await cb.run_offline(cb.load_scenarios(REGRESSIONS_4))
    failing = [(s["id"], t["n"], [k for k, ok in t["checks"].items() if not ok])
               for s in report["scenarios"] for t in s["turns"] if not t["ok"]]
    assert failing == []
    assert report["totals"]["turns"] == 11


def test_each_refused_turn_keeps_what_production_did():
    data = json.loads(REGRESSIONS_4.read_text(encoding="utf-8"))
    turns = [t for s in data["scenarios"] for t in s["turns"]]
    refused = [t for t in turns if t["real"]["failed"]]
    assert len(refused) == 4
    assert all(t["search_fails"] == 1 and "429" in t["real"]["error"] for t in refused)
    assert all("search_fails" not in t for t in turns if not t["real"]["failed"])
    for t in turns:
        if t["real"]["intent_via"] == "model":
            assert t["classifier"] == {"intent": t["real"]["intent"],
                                       "turn": t["real"]["turn_type"]}
        if t["real"]["intent_via"] == "fallback":
            assert t["classifier"] == "down"
        if t["real"].get("sources_found"):
            assert t["evidence"] is True


def test_each_turn_keeps_how_long_routing_took_and_why_it_fell_back():
    o = cb._from_final({"kind": "answer", "intent": "plan", "intent_via": "fallback",
                        "route_s": 2.004, "route_reason": "timeout"})
    assert (o["route_s"], o["route_reason"]) == (2.004, "timeout")
    assert cb._from_final({"kind": "red_flag"})["route_s"] is None


def test_the_totals_count_the_fallbacks_by_reason():
    turns = [{"ok": True, "intent_via": "fallback", "route_reason": "timeout"},
             {"ok": True, "intent_via": "fallback", "route_reason": "timeout"},
             {"ok": True, "intent_via": "fallback", "route_reason": "error:RateLimitError 429"},
             {"ok": True, "intent_via": "model", "route_reason": None}]
    t = cb._totals([{"id": "x", "turns": turns, "ok": 4, "total": 4}])
    assert t["fallback"] == 3
    assert t["fallback_reasons"] == {"timeout": 2, "error:RateLimitError 429": 1}


async def test_a_resumed_report_gives_this_runs_turns_apart(monkeypatch):
    async def _record(*_, **__):
        return None

    monkeypatch.setattr(usage, "record", _record)
    previous = _previous_run("anotar-sueño")
    todo = cb.not_yet_measured(cb.load_scenarios(), previous)

    async def _turn(guest, scenario, request):
        return _observed(answer="Respuesta [ev_1].", model_saw=None, ttft_s=3.0, total_s=4.0)

    report = await cb.run_with_model(
        todo, budget_usd=1, turn_runner=_turn, guest=_fake_guest, set_age=_no_age,
        carried=previous,
    )
    assert report["totals"]["turns_run"] == 110
    this_run = report["totals_run"]
    assert this_run["turns"] == this_run["turns_run"] == 53
    assert this_run["ttft_median_s"] == 3.0 and report["totals"]["ttft_median_s"] == 7.0
    text = cb.render_text(report)
    assert "Esta pasada: " in text and "/53" in text
