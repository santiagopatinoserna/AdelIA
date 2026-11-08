"""The questions the production smoke suite types must never reach a model.

apps/web/e2e-prod drives a real guest conversation on the live site, and the
rule is that no smoke run spends Anthropic tokens (Santiago, 2026-11-08). It
can only talk to the agent because a red flag is answered in code by the
`guard` node, before routing, retrieval or any model (agent/graph.py). The
suite reads its questions from e2e-prod/urgent-questions.json and its browser
guard aborts any other message, so this file pins the other half: every one of
those questions is a red flag for the detector and for the graph's guard node.
Editing the list to something the guard lets through fails here, in CI, before
anyone runs it against production.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from adelia.agent.graph import guard
from adelia.clinical.red_flags import detect

QUESTIONS_FILE = (
    Path(__file__).resolve().parents[2] / "web" / "e2e-prod" / "urgent-questions.json"
)

# Lucía, the baby every guest space starts with, is a few months old; the
# guard must fire at her age and with no age at all.
AGES = [None, 5]


def _questions() -> list[tuple[str, str]]:
    data = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    return [(data["locale"], q) for q in data["questions"]]


def test_the_suite_has_the_two_urgent_questions_of_its_conversation():
    questions = _questions()
    assert len(questions) == 2
    assert {locale for locale, _ in questions} == {"es"}


@pytest.mark.parametrize("age", AGES)
@pytest.mark.parametrize(("locale", "question"), _questions())
def test_every_smoke_question_is_a_red_flag(locale, question, age):
    assert detect(question, locale=locale, age_months=age) is not None


@pytest.mark.parametrize(("locale", "question"), _questions())
async def test_the_graph_guard_answers_it_without_a_model(locale, question):
    update = await guard({"message": question, "locale": locale, "facts": None})
    assert update["kind"] == "red_flag"
    assert "112" in update["answer"]
