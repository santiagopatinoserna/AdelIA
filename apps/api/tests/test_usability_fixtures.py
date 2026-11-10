"""The answers the usability battery reads are the API's own, word for word.

apps/web/e2e-prod/usability runs against production and never makes a model
answer, so the plan and the two-question clarify card it measures (reading
order, «Cuándo ir al médico» on screen, a card used with one thumb) are answered
inside the browser from e2e-prod/usability/fixtures.json. A stub that drifted
from the contract would measure a card or a plan nobody sees any more: this
file pins the clarify questions, their buttons and the free-text line to
`clarify_question` / `clarify_free_text`, and the plan's headings to
PLAN_HEADINGS, in the three languages. It also pins that the stubbed messages
are not red flags: the guard would answer them before any clarify or plan.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from adelia.clinical.red_flags import detect
from adelia.services.answer_contract import (
    PLAN_HEADINGS,
    clarify_free_text,
    clarify_question,
)

FIXTURES = (
    Path(__file__).resolve().parents[2] / "web" / "e2e-prod" / "usability" / "fixtures.json"
)
LOCALES = ["es", "en", "fr"]


def _fixtures() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


@pytest.mark.parametrize("locale", LOCALES)
def test_the_clarify_card_is_the_api_round_for_a_worry_about_the_nursery(locale):
    card = _fixtures()["clarify"][locale]["card"]
    assert card["type"] == "clarify"
    payload = card["payload"]
    fields = [q["field"] for q in payload["questions"]]
    assert fields == ["nursery_time", "general_state"]
    for q in payload["questions"]:
        expected = clarify_question(q["field"], locale)
        assert {k: q[k] for k in ("question", "options", "skip")} == expected
    # The first question also sits at the top level, the shape the demo reads.
    first = payload["questions"][0]
    assert {k: payload[k] for k in ("field", "question", "options", "skip")} == first
    assert payload["free"] == clarify_free_text(locale)
    assert payload["message"] == _fixtures()["clarify"][locale]["message"]
    assert card["id"] == "clarify-nursery_time-general_state"


@pytest.mark.parametrize("locale", LOCALES)
def test_the_plan_uses_the_contract_headings_in_order(locale):
    text = _fixtures()["plan"][locale]["answer"]
    headings = [line[3:].strip() for line in text.splitlines() if line.startswith("## ")]
    h = PLAN_HEADINGS[locale]
    assert headings == [h["today"], h["watch"], h["doctor"], h["remember"], h["mothers"]]
    # An opening sentence before "Hoy": what the reading-order check looks for.
    assert not text.lstrip().startswith("#")


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("kind", ["plan", "clarify"])
def test_the_stubbed_messages_are_not_red_flags(locale, kind):
    message = _fixtures()[kind][locale]["message"]
    assert detect(message, locale=locale, age_months=5) is None
