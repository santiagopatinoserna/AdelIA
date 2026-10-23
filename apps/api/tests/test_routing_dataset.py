"""The routing evaluation set (docs/specs/AGENT_GRAPH.md, "Cómo se mide").

`tests/data/routing_es.json` holds realistic messages in a mother's voice,
labelled by intent, plus the red-flag messages that must be caught by
`clinical/red_flags.detect` BEFORE routing. The small en/fr sets keep the
rules honest in the other two languages.

What is asserted without a key:
* the set is big enough to mean something (60+ Spanish messages, 10+ per
  intent, 8+ red flags);
* every red-flag message fires the guard, and no routed message does;
* the rules never send a `record` or a `plan` to `other`;
* when the rules decide, they are right (their job is to abstain otherwise).
The rules-only accuracy is printed so a run shows the coverage.

The model's accuracy needs a key and is marked `live_routing`.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from adelia.agent import route as r
from adelia.clinical import red_flags
from adelia.config import settings
from adelia.enrichment.profile_service import ProfileFacts

DATA = Path(__file__).parent / "data"
SETS = {"es": DATA / "routing_es.json", "en": DATA / "routing_en.json", "fr": DATA / "routing_fr.json"}


def load(locale: str) -> list[dict]:
    doc = json.loads(SETS[locale].read_text(encoding="utf-8"))
    default = doc.get("default", {})
    return [{**default, **item, "locale": locale} for item in doc["items"]]


def facts_for(item: dict) -> ProfileFacts | None:
    age = item.get("age_months")
    if age is None and not item.get("has_account"):
        return None
    return ProfileFacts(None, None, None, None, age)


def guard(item: dict):
    age = item.get("age_months")
    return red_flags.detect(item["text"], locale=item["locale"], age_months=age)


def routed(items: list[dict]) -> list[dict]:
    return [i for i in items if i["intent"] != "red_flag"]


ALL = [item for locale in SETS for item in load(locale)]
ES = load("es")


def test_the_spanish_set_is_big_enough_to_mean_something():
    counts = Counter(i["intent"] for i in ES)
    assert len(routed(ES)) >= 60
    assert counts["red_flag"] >= 8
    for intent in r.INTENTS:
        assert counts[intent] >= 10, f"{intent}: {counts[intent]} < 10"


def test_every_label_is_an_intent_or_red_flag():
    for item in ALL:
        assert item["intent"] in (*r.INTENTS, "red_flag"), item


@pytest.mark.parametrize("item", [i for i in ALL if i["intent"] == "red_flag"],
                         ids=lambda i: i["text"][:40])
def test_a_red_flag_is_caught_by_the_guard_before_route_is_consulted(item):
    flag = guard(item)
    assert flag is not None, "the guard missed it and route would have seen it"


def test_no_routed_message_trips_the_guard():
    """A routed label on a message the guard catches is a label that can never
    be exercised: the guard wins on every surface."""
    tripped = [(i["text"], guard(i).code) for i in routed(ALL) if guard(i) is not None]
    assert tripped == []


def _rules_results(items: list[dict]) -> list[tuple[dict, r.RouteDecision | None]]:
    return [
        (
            i,
            r.route_by_rules(
                i["text"], locale=i["locale"], has_account=i["has_account"], facts=facts_for(i)
            ),
        )
        for i in items
    ]


def test_the_rules_never_send_a_record_or_a_plan_to_other():
    bad = [
        (i["text"], i["intent"])
        for i, d in _rules_results(routed(ALL))
        if d is not None and d.intent == "other" and i["intent"] in ("record", "plan")
    ]
    assert bad == []


@pytest.mark.parametrize("locale", list(SETS))
def test_when_the_rules_decide_they_are_right(locale):
    results = _rules_results(routed(load(locale)))
    decided = [(i, d) for i, d in results if d is not None]
    wrong = [(i["text"], i["intent"], d.intent) for i, d in decided if d.intent != i["intent"]]
    accuracy = sum(1 for i, d in results if d is not None and d.intent == i["intent"]) / len(results)
    print(
        f"\nrules-only [{locale}]: accuracy {accuracy:.0%} "
        f"({len(decided)}/{len(results)} decided, {len(wrong)} wrong)"
    )
    assert wrong == [], wrong


def test_the_rules_decide_most_of_the_spanish_set():
    """Coverage, not perfection: the model exists for the rest."""
    results = _rules_results(routed(ES))
    decided = sum(1 for _, d in results if d is not None)
    assert decided / len(results) >= 0.75


def test_clarify_items_say_what_is_missing():
    for i, d in _rules_results([x for x in routed(ALL) if x["intent"] == "clarify"]):
        if d is not None:
            assert d.missing == i.get("missing", ["age"])


@pytest.mark.live_routing
@pytest.mark.skipif(not settings.mistral_api_key, reason="needs Mistral API key")
@pytest.mark.timeout(300)
async def test_rules_plus_model_reach_ninety_percent_on_the_spanish_set():
    hits = 0
    for i in routed(ES):
        d = await r.route(
            i["text"], locale="es", has_account=i["has_account"], facts=facts_for(i), timeout_s=20
        )
        hits += d.intent == i["intent"]
    assert hits / len(routed(ES)) >= 0.9
