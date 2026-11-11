"""The conversation battery: is talking to AdelIA fluent for a mother, in figures.

Santiago, 2026-11-10: "sigue mejorando, haz batería de pruebas completa,
verifica la usabilidad, la fluidez". The conversation tests were single cases
(tests/test_conversation*.py). This runs about thirty conversations of two to
five turns (scripts/conversation_scenarios.json), written the way a mother in
a hurry writes, and says for each turn whether it did what it must:

  turn        new topic, follow-up or correction (agent/conversation)
  kind        answer, clarify, red_flag, no_evidence, confirm, recorded...
  asks        the questions of the one clarify round, when it must ask first
  shape       plan or short answer; `doctor`: "Cuándo ir al médico" is there
  no_dose     never a dose, on any turn
  red_flag_first  the referral opens the answer and nothing was paid before it
  no_other_topic  nothing of an earlier topic reaches the model (or the answer)
  refusal_once    "no sources" said at most once per topic
  card        the card the turn must show (a record to confirm, a question)

Two modes.

Without a model (the default, and what CI runs): the real graph, as a
/dashboard turn builds it (agent/orchestrator.run_turn), with fakes for what
costs money: routing by the rules only (production's own fallback when the
classifier is rate-limited), retrieval that finds a recorded fake fragment or
nothing as each turn says, a model that writes one fixed line, and the diary
in memory. No database, no key, no network. Everything deterministic is
checked: the thread, the guard, the clarify round, the routing rules, the
refusal once, what the model would have been shown.

    .venv/bin/python scripts/conversation_battery.py
    .venv/bin/python scripts/conversation_battery.py --only fiebre-sin-cifra --format both
    .venv/bin/python scripts/conversation_battery.py --classifier-down

`--classifier-down` plays the day the classifier fails (the 429 of October,
or its 2 s deadline): every turn the rules cannot place takes production's
fallback instead of its recorded answer. A turn may also say so by itself,
`"classifier": "down"`; the report counts those turns apart.

With the model, only on request and under a hard spending cap, inside the
production API container (the scenarios run where the corpus and the keys are):

    docker exec -w /app infra-api-1 .venv/bin/python scripts/conversation_battery.py \\
        --with-model --budget-usd 2 --out /tmp/battery.json

The 2 $ cap of 2026-11-11 stopped at 57 of 110 turns. To measure the rest
without paying again for what was measured, hand the last report back:

    ... conversation_battery.py --with-model --budget-usd 2.5 \\
        --resume /tmp/battery.json --out /tmp/battery-2.json

Comparing the answer settings (settings.answer_effort_*, settings.follow_up_brevity,
2026-11-11): run the same regressions twice, off and on, with the same cap. The
environment of `docker exec` wins over the env file, and a blank effort reads as
unset. Each report keeps the settings it ran with (`settings`), the contract and
effort of each turn (`shape`, `effort`) and, apart, the words and the first word
of the follow-ups to an answered topic (`follows_answer`), which is what they move:

    docker exec -w /app -e FOLLOW_UP_BREVITY=false -e ANSWER_EFFORT_QUESTION= \
        -e ANSWER_EFFORT_PLAN= -e ANSWER_EFFORT_FOLLOW_UP= infra-api-1 \
        .venv/bin/python scripts/conversation_battery.py --with-model --budget-usd 1.5 \
        --scenarios scripts/conversation_regressions.json --out /tmp/regr-off.json
    docker exec -w /app -e FOLLOW_UP_BREVITY=true -e ANSWER_EFFORT_QUESTION=low \
        -e ANSWER_EFFORT_PLAN= -e ANSWER_EFFORT_FOLLOW_UP=low infra-api-1 \
        .venv/bin/python scripts/conversation_battery.py --with-model --budget-usd 1.5 \
        --scenarios scripts/conversation_regressions.json --out /tmp/regr-on.json

`--from <id>` starts at a scenario (file order), `--tag <tag>` keeps a topic
(repeatable), `--only <id>` names one; they combine, also with `--resume`.
A model turn records when the search began and when the answering model was
called (`stages_s`), next to the time to the first word.

Each scenario gets a fresh guest created as test traffic (her synthetic address
starts with "qa-", adelia/qa_traffic.py), with the scenario's age on her child.
Every turn goes through agent/orchestrator.run_turn, the very path of a
/dashboard turn, with the transcript the panel would send. Every provider
call is counted under the usage surface `qa` (never as real use), and the run
reads its own spend from that same count (services/usage.metered): before each
turn it stops if the spend has reached the budget or the most expensive turn
so far would cross it, and it stops at once on a call it cannot price. The
guest is erased afterwards through scripts/erase_user.py (the DELETE /users/me
path), also when a turn fails. Nothing is written outside that guest except
the usage counters, which is the point of item 4.

The JSON (`--out`) has every turn: what she wrote, the kind, the answer, the
cards, the sources, the time to the first token and to the end, the tokens and
the cost. The text report gives, per scenario and in total, how many turns
meet what is expected and, with the model, words per answer, time to the
answer and cost.

A turn marked `gap` in the scenarios fails because of a known defect of the
product, named there; it is counted as failing, and once it passes the mark
must go (tests/test_conversation_battery.py holds that ratchet).

Exit status: 0 when every turn meets what is expected but the known gaps, and
no gap passes (or, with the model, when the run finished); 1 otherwise without
the model; 2 bad options.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import statistics
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, TextIO
from zoneinfo import ZoneInfo

# This checkout's package first: a worktree may share another checkout's venv.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adelia import qa_traffic  # noqa: E402
from adelia.services import usage  # noqa: E402
from adelia.services.answer_contract import (  # noqa: E402
    PLAN_HEADINGS,
    no_evidence_reply,
    red_flag_opening,
)

SCENARIOS = Path(__file__).with_name("conversation_scenarios.json")
KINDS = ("answer", "clarify", "red_flag", "no_evidence", "experience_only", "confirm",
         "recorded", "tracked", "evidence_only")
TURN_TYPES = ("new", "follow_up", "correction")
#: A typo in --budget-usd must not become a bill: past this, ask a person.
MAX_BUDGET_USD = 20.0
#: The clock of the offline run, so a diary line's "a las 5" reads the same every day.
OFFLINE_NOW = datetime(2026, 11, 10, 11, 0, tzinfo=ZoneInfo("Europe/Madrid"))
OFFLINE_NAME = "Lucía"
#: What the panel sends (routers/agent.py and agent-canvas.tsx keep the same caps).
HISTORY_MAX_MESSAGES = 12
HISTORY_MAX_CHARS = 2000
CONFIRMED = "(confirma la tarjeta)"
#: Her record as the account search brings it back, for a turn marked `record`:
#: in production it came back on every turn of the QA guest (2026-11-11).
RECORD = ("[1] Revisión de los 4 meses: regurgita tras casi todas las tomas; tomas más "
          "frecuentes y de menor volumen.\n\n[2] La pediatra pide repetir la analítica si "
          "sigue cansada o come peor.")
PRESSED = "(pulsa un botón)"


def load_scenarios(path: Path | str | None = None) -> list[dict]:
    data = json.loads(Path(path or SCENARIOS).read_text(encoding="utf-8"))
    return data["scenarios"]


def select_scenarios(scenarios: list[dict], *, only: list[str] | tuple = (),
                     start: str | None = None, tags: list[str] | tuple = ()) -> list[dict]:
    """The scenarios to run, in file order: from `start` on, only those named,
    only those with one of `tags`. An unknown `start` is a typo, not an empty run."""
    picked = list(scenarios)
    if start is not None:
        ids = [s["id"] for s in picked]
        if start not in ids:
            raise ValueError(f"there is no scenario {start!r}")
        picked = picked[ids.index(start):]
    if only:
        picked = [s for s in picked if s["id"] in only]
    if tags:
        picked = [s for s in picked if set(tags) & set(s.get("tags") or [])]
    return picked


def measured(report: dict) -> set[str]:
    """The scenarios a model report ran whole (no turn skipped by the cap)."""
    return {s["id"] for s in report.get("scenarios") or []
            if s.get("turns") and len(s["turns"]) == s.get("total", len(s["turns"]))
            and not any(t.get("skipped") for t in s["turns"])}


def not_yet_measured(scenarios: list[dict], report: dict) -> list[dict]:
    """What `--resume` runs: every scenario the earlier report did not run whole.
    One it stopped in runs from its first turn: its guest was erased, and the
    answers of its first turns are the history the later ones read."""
    done = measured(report)
    return [s for s in scenarios if s["id"] not in done]


# --- the checks ------------------------------------------------------------------

_DRUG = (
    r"(?:paracetamol|ibuprofen\w*|apiretal|dalsy|doliprane|dafalgan|efferalgan|advil|"
    r"nurofen|amoxicil\w*|antibi[oó]tic\w*|antibiotique\w*|jarabe|syrup|sirop|"
    r"suppositoire|supositorio|medicamento|medicine|medication|m[eé]dicament\w*|"
    r"melatonin\w*|calpol|tylenol|motilium|dexketoprofeno|metamizol)"
)
#: A dose is a number with a dose unit, or a volume next to a medicine. A
#: volume of milk ("500 ml al día") or a temperature is not a dose.
_DOSE_UNIT = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:mg(?:\s*/\s*kg)?|mcg|µg|gotas|drops|gouttes|ui|iu)\b",
    re.IGNORECASE,
)
_VOLUME = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:ml|cc|cucharadit\w*|teaspoons?)\b",
                     re.IGNORECASE)
_DRUG_RE = re.compile(_DRUG, re.IGNORECASE)
_MARKER = re.compile(r"\[(?:ev_|ex_)?\d+\]")


def has_dose(text: str) -> bool:
    if _DOSE_UNIT.search(text or ""):
        return True
    for m in _VOLUME.finditer(text or ""):
        window = text[max(0, m.start() - 60): m.end() + 60]
        if _DRUG_RE.search(window):
            return True
    return False


def words(text: str) -> int:
    """Words she reads: markers and Markdown signs are not words."""
    plain = _MARKER.sub(" ", text or "")
    return sum(1 for w in plain.split() if re.search(r"\w", w))


def _lang(locale: str) -> str:
    return locale if locale in PLAN_HEADINGS else "es"


def evaluate(scenario: dict, observed: list[dict], *, mode: str) -> list[dict]:
    """Each turn's checks against what the scenario expects. Pure: no I/O.

    `observed` is what a turn did (offline or with the model): turn_type,
    kind, intent, asks, answer, cards, and offline also `paid` (the costly
    steps reached, in order) and `model_saw` (what the answering model got).
    """
    lang = _lang(scenario["locale"])
    refusal = no_evidence_reply(lang)
    doctor = PLAN_HEADINGS[lang]["doctor"]
    opening = red_flag_opening(lang)
    out: list[dict] = []
    topic, refused = 0, set()
    for n, (turn, o) in enumerate(zip(scenario["turns"], observed), start=1):
        e = turn["expect"]
        answer = o.get("answer") or ""
        if o.get("turn_type") == "new" and n > 1:
            topic += 1
        checks: dict[str, bool] = {}
        if o.get("error"):
            checks["no_error"] = False
        checks["kind"] = o.get("kind") == e["kind"]
        if "turn" in e:
            checks["turn"] = o.get("turn_type") == e["turn"]
        if "asks" in e:
            checks["asks"] = list(o.get("asks") or []) == list(e["asks"])
        if "shape" in e:
            checks["shape"] = o.get("intent") == e["shape"]
        if e.get("doctor"):
            saw = o.get("model_saw")
            checks["doctor"] = (doctor in (saw or {}).get("system", "") if mode == "offline"
                                else doctor in answer)
        if "card" in e:
            checks["card"] = e["card"] in [c.get("type") for c in o.get("cards") or []]
        checks["no_dose"] = not has_dose(answer)
        if e["kind"] == "red_flag" or o.get("kind") == "red_flag":
            first = answer.startswith(opening)
            if mode == "offline":
                first = first and o.get("paid") == []
            checks["red_flag_first"] = first
        leaks = list(e.get("not_seen") or [])
        if leaks or (n > 1 and e.get("turn") == "new"):
            checks["no_other_topic"] = _no_other_topic(o, leaks, mode=mode)
        said_it = refusal in answer
        told = (mode == "offline" and conversation_note_mark() in
                ((o.get("model_saw") or {}).get("user") or ""))
        # Offline, a model answer is a recording: what the code owes is telling
        # the model the topic was already refused (agent/conversation.refused_note).
        checks["refusal_once"] = not (said_it and topic in refused and not told)
        if said_it:
            refused.add(topic)
        out.append({"n": n, "ok": all(checks.values()), "checks": checks})
    return out


def conversation_note_mark() -> str:
    from adelia.agent.conversation import REFUSED_NOTE_MARK

    return REFUSED_NOTE_MARK


def _no_other_topic(o: dict, leaks: list[str], *, mode: str) -> bool:
    answer = o.get("answer") or ""
    if any(w.lower() in answer.lower() for w in leaks):
        return False
    if mode != "offline":
        return True
    saw = o.get("model_saw")
    if saw is None:
        return True
    seen = "\n".join([saw.get("user", ""), *(str(m.get("content", ""))
                                              for m in saw.get("history") or [])])
    if any(w.lower() in seen.lower() for w in leaks):
        return False
    # A new topic carries no earlier exchange to the answering model.
    return not (o.get("turn_type") == "new" and saw.get("history"))


# --- driving a conversation the way the panel does ---------------------------------


def _panel_history(transcript: list[dict]) -> list[dict]:
    """agent-canvas.tsx: no empty answer (a card turn), a clarify card's questions
    as the answer's text, the last 12 messages, each cut at 2000 characters."""
    kept = [m for m in transcript if not (m["role"] == "assistant" and not m["content"]
                                          and not m.get("asked"))]
    return [{"role": m["role"],
             "content": (m["content"] or m.get("asked") or "")[:HISTORY_MAX_CHARS]}
            for m in kept[-HISTORY_MAX_MESSAGES:]]


def _last_card(cards: list[dict], kind: str) -> dict:
    for card in reversed(cards):
        if card.get("type") == kind:
            return card
    raise ValueError(f"the scenario presses a {kind} card that the last turn did not show")


def build_request(turn: dict, transcript: list[dict], last_cards: list[dict],
                  locale: str) -> dict:
    """What the panel would POST to /agent/turn for this turn of the scenario."""
    if turn.get("confirm"):
        card = _last_card(last_cards, "confirm")
        return {"message": "", "history": None, "display": CONFIRMED, "card_action": {
            "intent": "confirm", "tool_name": card["payload"]["tool_name"],
            "tool_args": card["payload"]["tool_args"]}}
    if turn.get("press"):
        card = _last_card(last_cards, "clarify")
        questions = card["payload"].get("questions") or [card["payload"]]
        labels = []
        for press in turn["press"]:
            q = next(q for q in questions if q["field"] == press["field"])
            labels.append(next(o["label"] for o in q["options"] if o["value"] == press["value"]))
        return {"message": card["payload"]["message"], "history": _panel_history(transcript),
                "display": " · ".join(labels), "clarifications": list(turn["press"])}
    return {"message": turn["say"], "history": _panel_history(transcript),
            "display": turn["say"]}


TurnFn = Callable[[dict, dict], Awaitable[dict]]


async def _drive(scenario: dict, turn_fn: TurnFn,
                 gate: Callable[[], str | None] | None = None) -> tuple[list[dict], str | None]:
    """Every turn of a scenario in order; stops before a turn the gate refuses."""
    transcript: list[dict] = []
    last_cards: list[dict] = []
    observed: list[dict] = []
    for turn in scenario["turns"]:
        if gate is not None and (reason := gate()):
            return observed, reason
        try:
            request = build_request(turn, transcript, last_cards, scenario["locale"])
        except (ValueError, StopIteration) as exc:
            # The card this turn presses never came: the turn fails, the run goes on.
            observed.append({"error": str(exc) or "no such option", "kind": None,
                             "mother": turn.get("say") or (PRESSED if turn.get("press")
                                                           else CONFIRMED), "message": None,
                             "answer": "", "cards": []})
            last_cards = []
            continue
        o = await turn_fn(turn, request)
        o["mother"] = request["display"]
        o["message"] = request["message"]
        observed.append(o)
        answer = o.get("answer") or ""
        if turn.get("confirm"):
            # The panel streams the confirmation's reply into the card turn's bubble.
            if transcript and transcript[-1]["role"] == "assistant":
                transcript[-1]["content"] += answer
        else:
            asked = "\n".join(
                q["question"] for c in o.get("cards") or [] if c.get("type") == "clarify"
                for q in (c["payload"].get("questions") or [c["payload"]])
            )
            transcript += [{"role": "user", "content": request["display"]},
                           {"role": "assistant", "content": answer, "asked": asked}]
        last_cards = o.get("cards") or []
    return observed, None


def _from_final(state: dict) -> dict:
    c = state.get("conversation")
    kind = state.get("kind")
    return {
        "turn_type": c.kind if c is not None else None,
        "kind": kind,
        "intent": state.get("intent"),
        "intent_via": state.get("intent_via"),
        "asks": list(state.get("missing") or []) if kind == "clarify" else [],
        # The contract and the thinking effort the answering model got, and whether
        # it followed an answer with sources in its topic: what the answer settings
        # change (settings.answer_effort_*, settings.follow_up_brevity).
        "shape": state.get("shape"),
        "effort": state.get("effort"),
        "follows_answer": bool(c is not None and c.kind == "follow_up" and c.answered),
    }


def _sources(evidence: list[dict], citations: list[dict]) -> list[dict]:
    out = [{"tag": c.get("tag"), "tier": c.get("tier"), "title": c.get("title")}
           for c in evidence or []]
    out += [{"tag": "record", "tier": "record", "title": c.get("title") or c.get("filename")}
            for c in citations or []]
    return out


# --- without a model ----------------------------------------------------------------


class _OfflineSurface:
    """What run_turn lends the graph, with fakes for what costs money."""

    def __init__(self, store, *, evidence: bool, locale: str,
                 classifier: dict | str | None = None, record: bool = False,
                 model_answer: str | None = None):
        from adelia.enrichment.evidence_retrieval import EvidenceMatch

        self.store, self.locale = store, locale
        self.record, self.model_answer = record, model_answer
        self.classifier, self.recorded, self.down = classifier, False, False
        self.paid: list[str] = []
        self.model_saw: dict | None = None
        self.evidence = [EvidenceMatch(
            chunk_id=uuid.UUID(int=1), source_id=uuid.UUID(int=2),
            source_title="Fragmento grabado", organization="AEP", publication_year=2024,
            url="https://example.org/fragmento", content="fragmento", chunk_index=0,
            distance=0.07, tier="evidence",
        )] if evidence else []

    async def route(self, text: str, **kwargs):
        """The routing rules; where they abstain, the classifier's recorded answer
        for this turn (`classifier` in the scenario), else production's fallback."""
        from adelia.agent.route import _FALLBACK, RouteDecision, route_by_rules

        self.paid.append("route")
        decision = route_by_rules(text, locale=kwargs.get("locale", "es"),
                                  has_account=kwargs.get("has_account", False),
                                  facts=kwargs.get("facts"))
        if decision is not None:
            return decision
        if self.classifier == "down":
            self.down = True
            return _FALLBACK
        if self.classifier is None:
            return _FALLBACK
        self.recorded = True
        return RouteDecision(intent=self.classifier["intent"], confidence=0.9, via="model",
                             turn=self.classifier.get("turn"),
                             missing=list(self.classifier.get("missing") or []))

    async def retrieve(self, state):
        from adelia.agent.graph import Retrieved

        self.paid.append("retrieve")
        return Retrieved(evidence=list(self.evidence),
                         patient_context=RECORD if self.record else None)

    def stream(self, history_default: list[dict]):
        async def _stream(system: str, user: str, history: list[dict] | None = None,
                          effort: str | None = None):
            self.paid.append("stream")
            self.model_saw = {"system": system, "user": user, "effort": effort,
                              "history": history_default if history is None else history}
            yield self.model_answer or "Texto de prueba [ev_1]."
        return _stream

    async def track(self, state):
        self.paid.append("track")
        text = "Respuesta del bucle de herramientas."
        yield {"type": "token", "content": text}
        yield {"type": "result", "answer": text, "citations": [], "evidence_citations": []}

    async def write_tool(self, name: str, args: dict):
        from adelia.agent.graph import WriteOutcome

        self.paid.append("write")
        return WriteOutcome(text="Hecho.")

    async def complete_json(self, *_, **__):
        self.paid.append("record_model")
        raise RuntimeError("offline: no model")


class _MemoryStore:
    def __init__(self):
        self.saved: list = []

    async def save(self, draft) -> None:
        self.saved.append(draft)

    async def previous(self, kind: str, before):
        same = [d for d in self.saved if d.kind == kind and d.observed_at <= before]
        return same[-1] if same else None


async def _offline_turn(scenario: dict, store: _MemoryStore, turn: dict, request: dict,
                        *, classifier_down: bool = False) -> dict:
    from adelia.agent.graph import ACCOUNT_CLARIFY_FIELDS, GraphDeps, stream_graph
    from adelia.agent.orchestrator import sanitize_history
    from adelia.enrichment.profile_service import ProfileFacts

    locale = scenario["locale"]
    classifier = "down" if classifier_down else turn.get("classifier")
    surface = _OfflineSurface(store, evidence=turn.get("evidence", True), locale=locale,
                              classifier=classifier, record=turn.get("record", False),
                              model_answer=turn.get("model_answer"))
    messages = sanitize_history(request.get("history"))
    text_history = [m for m in messages if isinstance(m.get("content"), str)]
    deps = GraphDeps(
        route=surface.route, retrieve=surface.retrieve, stream=surface.stream(text_history),
        can_ask=True, can_write=True, record_store=store, write_tool=surface.write_tool,
        track=surface.track, clarify_fields=ACCOUNT_CLARIFY_FIELDS, clarify_round=2,
        complete_json=surface.complete_json, now=lambda: OFFLINE_NOW,
    )
    facts = ProfileFacts(None, OFFLINE_NAME, None, "F", scenario.get("age_months"))
    state = {
        "surface": "agent", "locale": locale, "message": request.get("message") or "",
        "account": True, "facts": facts, "history": messages,
        "card_action": request.get("card_action"),
        "clarifications": request.get("clarifications"),
    }
    tokens: list[str] = []
    cards: list[dict] = []
    final: dict = {}
    async for event in stream_graph(state, deps):
        if event["type"] == "token":
            tokens.append(event["content"])
        elif event["type"] == "card":
            cards.append(event["card"])
        elif event["type"] == "final":
            final = event["state"]
    observed = {
        **_from_final(final),
        "answer": "".join(tokens), "cards": cards,
        "sources": _sources(final.get("evidence_citations") or [], final.get("citations") or []),
        "paid": surface.paid, "model_saw": surface.model_saw, "error": None,
    }
    if observed["intent_via"] == "model":
        observed["intent_via"] = "recorded"
    elif observed["intent_via"] == "fallback" and surface.down:
        observed["intent_via"] = "down"
    return observed


def _scenario_result(scenario: dict, observed: list[dict], *, mode: str) -> dict:
    checked = evaluate(scenario, observed, mode=mode)
    turns = []
    for turn, o, c in zip(scenario["turns"], observed, checked):
        entry = {**c, **{k: v for k, v in o.items() if k not in ("model_saw",)}}
        if turn.get("gap"):
            entry["gap"] = turn["gap"]
        turns.append(entry)
    return {"id": scenario["id"], "locale": scenario["locale"],
            "age_months": scenario.get("age_months"), "tags": scenario.get("tags", []),
            "turns": turns, "ok": sum(t["ok"] for t in turns), "total": len(scenario["turns"])}


async def run_offline(scenarios: list[dict], *, classifier_down: bool = False) -> dict:
    """Every scenario through the real graph with fakes for what costs money;
    with `classifier_down`, no recorded classifier answer is played."""
    results = []
    for scenario in scenarios:
        store = _MemoryStore()

        async def _turn(turn, request, scenario=scenario, store=store):
            return await _offline_turn(scenario, store, turn, request,
                                       classifier_down=classifier_down)

        observed, _ = await _drive(scenario, _turn)
        results.append(_scenario_result(scenario, observed, mode="offline"))
    return {"mode": "offline", "classifier_down": classifier_down, "scenarios": results,
            "totals": _totals(results)}


def _totals(results: list[dict], *, run_turns: list[dict] | None = None) -> dict:
    turns = [t for s in results for t in s["turns"] if not t.get("skipped")]
    routed = [t for t in turns if t.get("intent_via")]
    out = {"scenarios": len(results), "turns": sum(s["total"] for s in results),
           "turns_run": len(turns), "ok": sum(1 for t in turns if t["ok"]),
           "scenarios_ok": sum(1 for s in results if s["ok"] == s["total"]),
           "gaps": sum(1 for t in turns if t.get("gap")),
           "gaps_fixed": sum(1 for t in turns if t.get("gap") and t["ok"]),
           "failing_unexpected": sum(1 for t in turns if not t["ok"] and not t.get("gap")),
           "routed": len(routed),
           "rules_alone": sum(1 for t in routed if t["intent_via"] == "rule"),
           "needs_classifier": sum(1 for t in routed if t["intent_via"] in ("recorded", "model")),
           "fallback": sum(1 for t in routed if t["intent_via"] == "fallback"),
           "classifier_down": sum(1 for t in routed if t["intent_via"] == "down"),
           "tool_loop_unruled": sum(1 for t in turns if "track" in (t.get("paid") or [])
                                    and t.get("intent_via") != "rule")}
    if run_turns is None:
        return out
    counts = [t["words"] for t in run_turns if t.get("words")]
    ttft = [t["ttft_s"] for t in run_turns if t.get("ttft_s") is not None]
    total = [t["total_s"] for t in run_turns if t.get("total_s") is not None]
    follow = [t for t in run_turns if t.get("follows_answer") and t.get("words")]
    follow_ttft = [t["ttft_s"] for t in follow if t.get("ttft_s") is not None]
    out.update({
        "words_median": statistics.median(counts) if counts else None,
        "words_mean": round(statistics.fmean(counts), 1) if counts else None,
        "ttft_median_s": round(statistics.median(ttft), 3) if ttft else None,
        "ttft_p95_s": round(_p95(ttft), 3) if ttft else None,
        "total_median_s": round(statistics.median(total), 3) if total else None,
        "cost_usd": round(sum(t.get("cost_usd") or 0 for t in run_turns), 6),
        # A follow-up to a topic already answered with sources: what
        # follow_up_brevity and answer_effort_follow_up change.
        "follow_ups_to_an_answer": len(follow),
        "words_follow_up_median": (statistics.median(t["words"] for t in follow)
                                   if follow else None),
        "ttft_follow_up_median_s": (round(statistics.median(follow_ttft), 3)
                                    if follow_ttft else None),
    })
    return out


#: The settings that change what the answering model is asked or handed. A model
#: report keeps them, so a run with them on and one with them off can be compared.
ANSWER_SETTINGS = (
    "llm_provider", "anthropic_chat_model", "answer_effort_question", "answer_effort_plan",
    "answer_effort_follow_up", "follow_up_brevity", "plan_brevity", "no_unasked_refusals",
    "warning_signs_retrieval", "lay_query_expansion", "implicit_subject_expansion",
)


def answer_settings() -> dict:
    from adelia.config import settings

    return {name: getattr(settings, name) for name in ANSWER_SETTINGS}


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


# --- with the model ------------------------------------------------------------------


@dataclass(frozen=True)
class Guest:
    user_id: uuid.UUID
    profile_id: uuid.UUID


def _erase_user_module():
    path = Path(__file__).with_name("erase_user.py")
    spec = importlib.util.spec_from_file_location("adelia_erase_user", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@asynccontextmanager
async def qa_guest(locale: str = "es", *, out: TextIO | None = None) -> AsyncIterator[Guest]:
    """A guest created as test traffic, erased on the way out whatever happened."""
    from adelia.services.guest import create_guest

    with qa_traffic.marked():
        created = await create_guest(locale)
    guest = Guest(user_id=created.user_id, profile_id=created.profile_id)
    try:
        yield guest
    finally:
        await _erase(guest, out or sys.stderr)


async def _erase(guest: Guest, out: TextIO) -> None:
    import sqlalchemy as sa

    from adelia.db import AsyncSessionLocal
    from adelia.models import User

    async with AsyncSessionLocal() as session:
        email = await session.scalar(sa.select(User.email).where(User.id == guest.user_id))
    if email is None:
        return
    if not email.startswith(qa_traffic.GUEST_EMAIL_PREFIX):
        # Never: this run creates its guests as test traffic. Erase nothing else.
        print(f"not erased: {guest.user_id} is not a QA guest", file=out)
        return
    code = await _erase_user_module().run(["--id", str(guest.user_id), "--yes"], out=out)
    if code != 0:
        print(f"erase_user returned {code} for {guest.user_id}", file=out)


def _birth_for(age_months: int, today: date) -> date:
    from adelia.enrichment.profile_service import age_in_months

    month = today.year * 12 + (today.month - 1) - age_months
    day = min(today.day, 28)
    born = date(month // 12, month % 12 + 1, day) - timedelta(days=10)
    while age_in_months(born, today=today) < age_months:
        born -= timedelta(days=1)
    while age_in_months(born, today=today) > age_months:
        born += timedelta(days=1)
    return born


async def set_guest_age(guest: Guest, age_months: int | None) -> None:
    """The scenario's age on the guest's child (her own row, nothing else)."""
    import sqlalchemy as sa

    from adelia.db import AsyncSessionLocal
    from adelia.models import Profile

    born = None if age_months is None else _birth_for(age_months, date.today())
    async with AsyncSessionLocal() as session:
        await session.execute(
            sa.update(Profile)
            .where(Profile.id == guest.profile_id, Profile.user_id == guest.user_id)
            .values(date_of_birth=born))
        await session.commit()


async def dashboard_turn(guest: Guest, scenario: dict, request: dict) -> dict:
    """One /dashboard turn: agent/orchestrator.run_turn, what POST /agent/turn runs."""
    from adelia.agent.orchestrator import run_turn

    finals: list[dict] = []
    tokens: list[str] = []
    cards: list[dict] = []
    error = None
    citations: list[dict] = []
    evidence: list[dict] = []
    start = time.perf_counter()
    first = None
    stages: dict[str, float] = {}
    sources_found = None
    async for event in run_turn(
        user_id=guest.user_id, profile_id=guest.profile_id,
        message=request.get("message") or "", history=request.get("history"),
        card_action=request.get("card_action"), locale=scenario["locale"],
        clarifications=request.get("clarifications"), on_final=finals.append,
    ):
        if first is None and event.type in ("token", "card"):
            first = time.perf_counter() - start
        if event.type == "status":
            # When the search began and when the answering model was called.
            stages.setdefault(event.content, round(time.perf_counter() - start, 3))
            if event.content == "writing":
                sources_found = event.sources
        if event.type == "token":
            tokens.append(event.content)
        elif event.type == "card":
            cards.append(event.card)
        elif event.type == "final":
            citations, evidence = event.citations, event.evidence_citations
        elif event.type == "error":
            error = event.content
    total = time.perf_counter() - start
    return {
        **_from_final(finals[-1] if finals else {}),
        "answer": "".join(tokens), "cards": cards, "sources": _sources(evidence, citations),
        "paid": None, "model_saw": None, "error": error,
        "ttft_s": round(first if first is not None else total, 3), "total_s": round(total, 3),
        "stages_s": stages, "sources_found": sources_found,
    }


GuestFactory = Callable[..., Any]
TurnRunner = Callable[[Guest, dict, dict], Awaitable[dict]]


def _sum_tokens(calls: list[dict]) -> dict[str, int]:
    return {name: sum(c.get(name, 0) for c in calls)
            for name in ("input_tokens", "output_tokens", "cache_read_tokens",
                         "cache_write_tokens")}


async def run_with_model(
    scenarios: list[dict], *, budget_usd: float, turn_runner: TurnRunner | None = None,
    guest: GuestFactory | None = None,
    set_age: Callable[[Guest, int | None], Awaitable[None]] | None = None,
    carried: dict | None = None,
) -> dict:
    """Every scenario through run_turn as test traffic, until the budget is spent.

    `carried` is an earlier model report (`--resume`): the scenarios it ran whole
    and this run does not are kept as they were, marked `carried`, and the totals
    cover both; the budget counts only what this run spends."""
    if not 0 < budget_usd <= MAX_BUDGET_USD:
        raise ValueError(f"the budget must be above 0 and at most {MAX_BUDGET_USD} $")
    runner = turn_runner or dashboard_turn
    make_guest = guest or qa_guest
    aging = set_age or set_guest_age
    results: list[dict] = []
    run_turns: list[dict] = []
    stopped: str | None = None
    worst = 0.0
    with usage.metered() as meter, qa_traffic.marked():

        def gate() -> str | None:
            spent = meter.capped_usd()
            if spent is None:
                return "unpriced"
            if spent >= budget_usd or spent + worst > budget_usd:
                return "budget"
            return None

        for scenario in scenarios:
            observed: list[dict] = []
            if stopped is None:
                async with make_guest(scenario["locale"]) as g:
                    await aging(g, scenario.get("age_months"))

                    async def _turn(turn, request, g=g, scenario=scenario):
                        nonlocal worst
                        before = len(meter.calls)
                        o = await runner(g, scenario, request)
                        calls = meter.calls[before:]
                        cost, bounded = _turn_cost(calls)
                        worst = max(worst, cost)
                        o.update({"tokens": _sum_tokens(calls), "calls": len(calls),
                                  "cost_usd": cost, "cost_is_upper_bound": bounded,
                                  "words": words(o.get("answer") or "")})
                        return o

                    observed, stopped = await _drive(scenario, _turn, gate)
            result = _scenario_result(scenario, observed, mode="model")
            run_turns += result["turns"]
            for n in range(len(observed) + 1, len(scenario["turns"]) + 1):
                result["turns"].append({"n": n, "ok": False, "skipped": stopped or "budget",
                                        "checks": {}})
            results.append(result)
        spent = meter.capped_usd()
        listed = meter.estimated_usd()
        unpriced = meter.unpriced()
    report = {"mode": "model", "budget_usd": budget_usd, "spent_usd": spent,
              "list_usd": listed, "stopped": stopped, "unpriced": unpriced,
              "settings": answer_settings()}
    if carried is not None:
        results, kept = _merge(carried, results)
        run_turns = run_turns + kept
        report["previous_spent_usd"] = carried.get("spent_usd")
    return {**report, "scenarios": results, "totals": _totals(results, run_turns=run_turns)}


def _merge(carried: dict, results: list[dict]) -> tuple[list[dict], list[dict]]:
    """An earlier report's whole scenarios with this run's, in the earlier order."""
    fresh = {r["id"]: r for r in results}
    done = measured(carried)
    merged: list[dict] = []
    kept_turns: list[dict] = []
    for s in carried.get("scenarios") or []:
        if s["id"] in fresh:
            merged.append(fresh.pop(s["id"]))
        elif s["id"] in done:
            merged.append({**s, "carried": True})
            kept_turns += s["turns"]
    return merged + list(fresh.values()), kept_turns


def _turn_cost(calls: list[dict]) -> tuple[float, bool]:
    """The turn's cost for the cap, and whether part of it is an upper bound
    (a model without an official price, at the dearest known price)."""
    from adelia.services.usage_prices import ceiling_usd, estimate_usd

    total, bounded = 0.0, False
    for c in calls:
        usd = estimate_usd(c["provider"], c["model"], c)
        if usd is None:
            bounded = True
            usd = ceiling_usd(c) or 0.0
        total += usd
    return round(total, 6), bounded


# --- the report -----------------------------------------------------------------------


def _pct(ok: int, total: int) -> str:
    return f"{100 * ok / total:.1f} %".replace(".", ",") if total else "sin turnos"


def render_text(report: dict) -> str:
    """For a person, in Spanish: Santiago reads it."""
    t = report["totals"]
    mode = "sin modelo (falsos grabados)" if report["mode"] == "offline" else "con modelo"
    if report.get("classifier_down"):
        mode += ", con el clasificador caído"
    lines = [f"Batería de conversación, {mode}", ""]
    for s in report["scenarios"]:
        lines.append(f"{s['id']} ({s['locale']}, {s['total']} turnos): {s['ok']}/{s['total']}")
        for turn in s["turns"]:
            if turn.get("skipped"):
                lines.append(f"  turno {turn['n']}: sin ejecutar ({turn['skipped']})")
            elif not turn["ok"]:
                failed = ", ".join(k for k, v in turn["checks"].items() if not v)
                lines.append(f"  turno {turn['n']}: falla {failed} "
                             f"(kind={turn.get('kind')}, turno={turn.get('turn_type')})")
                if turn.get("gap"):
                    lines.append(f"    defecto conocido: {turn['gap']}")
            elif turn.get("gap"):
                lines.append(f"  turno {turn['n']}: ya cumple; quita su marca de defecto "
                             "conocido (gap)")
    lines += ["", f"Turnos que cumplen: {t['ok']}/{t['turns']} ({_pct(t['ok'], t['turns'])}); "
              f"conversaciones enteras: {t['scenarios_ok']}/{t['scenarios']}",
              f"Turnos con defecto conocido (gap): {t['gaps']}; "
              f"fallos nuevos: {t['failing_unexpected']}",
              f"Enrutado: {t['rules_alone']} de {t['routed']} turnos los deciden las reglas solas; "
              f"{t['needs_classifier']} necesitan el clasificador"
              + (" (respuesta grabada)" if report["mode"] == "offline" else "")
              + (f"; {t['fallback']} cayeron al respaldo" if t["fallback"] else "")]
    if t.get("classifier_down"):
        lines.append(f"Con el clasificador caído: {t['classifier_down']} turnos tomaron el "
                     f"respaldo; {t['tool_loop_unruled']} acabaron en el bucle de herramientas "
                     "sin que una regla los mandara")
    if report["mode"] == "model":
        lines.append(f"Turnos ejecutados: {t['turns_run']}/{t['turns']}")
        lines.append(f"Palabras por respuesta: mediana {t['words_median']}, "
                     f"media {t['words_mean']}")
        lines.append(f"Tiempo hasta la respuesta: mediana {t['ttft_median_s']} s, "
                     f"p95 {t['ttft_p95_s']} s; hasta el final: mediana {t['total_median_s']} s")
        if t.get("follow_ups_to_an_answer"):
            lines.append(f"Seguimientos de un tema ya respondido: {t['follow_ups_to_an_answer']}; "
                         f"palabras, mediana {t['words_follow_up_median']}; primera palabra, "
                         f"mediana {t['ttft_follow_up_median_s']} s")
        on = {k: v for k, v in (report.get("settings") or {}).items()
              if k not in ("llm_provider", "anthropic_chat_model") and v}
        if report.get("settings") is not None:
            lines.append("Ajustes de respuesta encendidos: "
                         + (", ".join(f"{k}={v}" for k, v in on.items()) or "ninguno"))
        spent = report["spent_usd"]
        lines.append(f"Gasto contado (etiqueta qa): {spent or 0:.4f} $ de un tope de "
                     f"{report['budget_usd']:.2f} $; a precio de lista, solo modelos con "
                     f"precio: {report['list_usd']:.4f} $")
        if report["stopped"]:
            lines.append(f"Parada antes de terminar: {report['stopped']}")
        if report.get("unpriced"):
            lines.append("Sin precio oficial (contados al precio más caro conocido para el "
                         "tope): " + ", ".join(report["unpriced"]))
    return "\n".join(lines)


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--with-model", action="store_true",
                        help="run through the real agent and providers (spends money)")
    parser.add_argument("--budget-usd", type=float, default=None,
                        help=f"hard spending cap with --with-model, at most {MAX_BUDGET_USD}")
    parser.add_argument("--classifier-down", action="store_true",
                        help="offline: play the fallback wherever the rules abstain")
    parser.add_argument("--scenarios", type=Path, default=None)
    parser.add_argument("--only", action="append", default=[], help="a scenario id")
    parser.add_argument("--from", dest="start", default=None,
                        help="start at this scenario id (file order)")
    parser.add_argument("--tag", action="append", default=[],
                        help="only scenarios with this tag (repeatable)")
    parser.add_argument("--resume", type=Path, default=None,
                        help="with --with-model: an earlier model report (--out); run only "
                             "the scenarios it did not run whole and keep the rest")
    parser.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    parser.add_argument("--format", choices=("text", "json", "both"), default="text")
    return parser.parse_args(argv)


async def _model_main(scenarios: list[dict], budget: float, carried: dict | None = None
                      ) -> dict:
    from adelia.db import engine

    try:
        return await run_with_model(scenarios, budget_usd=budget, carried=carried)
    finally:
        await usage.drain()
        await engine.dispose()


def _earlier_report(path: Path) -> dict | None:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) and report.get("mode") == "model" else None


def main(argv: list[str] | None = None, *, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    args = _parse(sys.argv[1:] if argv is None else argv)
    if args.budget_usd is not None and not args.with_model:
        print("--budget-usd only makes sense with --with-model; nothing was run.",
              file=sys.stderr)
        return 2
    if args.with_model and (args.budget_usd is None
                            or not 0 < args.budget_usd <= MAX_BUDGET_USD):
        print(f"--with-model needs --budget-usd above 0 and at most {MAX_BUDGET_USD}; "
              "nothing was run.", file=sys.stderr)
        return 2
    carried = None
    if args.resume is not None:
        carried = _earlier_report(args.resume) if args.with_model else None
        if carried is None:
            print("--resume needs --with-model and a report of a model run (--out); "
                  "nothing was run.", file=sys.stderr)
            return 2
    try:
        scenarios = select_scenarios(load_scenarios(args.scenarios), only=args.only,
                                     start=args.start, tags=args.tag)
    except ValueError as exc:
        print(f"{exc}; nothing was run.", file=sys.stderr)
        return 2
    if carried is not None:
        scenarios = not_yet_measured(scenarios, carried)
    if args.with_model:
        report = asyncio.run(_model_main(scenarios, args.budget_usd, carried))
    else:
        report = asyncio.run(run_offline(scenarios, classifier_down=args.classifier_down))
    if args.format in ("text", "both"):
        print(render_text(report), file=out)
    if args.format in ("json", "both"):
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str), file=out)
    if args.out is not None:
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                            encoding="utf-8")
    if report["mode"] == "offline":
        totals = report["totals"]
        return 0 if totals["failing_unexpected"] == 0 and totals["gaps_fixed"] == 0 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
