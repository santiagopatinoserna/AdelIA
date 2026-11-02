"""The age scope filter (docs/HANDOFF_CLAUDE_CODE.md, 4.1).

A message about a child of 3 years or more, with no baby of 0 to 24 months
in it, is refused in code, right after the red flags. Measured on 2026-10-27
with the development corpus loaded, golden B12 ("my 7-year-old") reached a
sleep fragment under the 0.19 cut: the words of the question are the
corpus's, the child is not. These tests pin both sides: the age_band and
wrong_age questions of group B are refused, and nothing a parent of a baby
asks (group A, the routing sets) is.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from adelia.clinical.age_scope import child_outside_scope
from adelia.clinical.golden import GOLDEN_SET, is_refusal, questions
from adelia.services.answer_contract import no_evidence_reply, out_of_scope_age_reply

ROUTING = Path(__file__).parent / "data"

OUTSIDE = [
    "Mi hija de 13 años tiene la regla muy abundante, ¿necesita un suplemento de hierro?",
    "How many hours of sleep does my 7-year-old need, and should he still have a nap?",
    "Mon fils de 10 ans a la diarrhée et vomit depuis hier",
    "Mon enfant de 3 ans peut-il dormir avec un oreiller et une couette ?",
    "¿Cuántas horas tiene que dormir un niño de 5 años?",
    "Mi hijo tiene 4 años y todavía no habla bien",
    "mi niño de tres años no quiere comer",
    "Is it normal for a three-year-old to still wake at night?",
    "My son is 6 years old and has a cough",
    "Il a 4 ans et il tousse la nuit",
    "¿Qué come un niño de 3 a 5 años?",
    "Mi bebé de 3 años no duerme la siesta",
]

INSIDE = [
    "Mi bebé de 7 meses no duerme la siesta",
    "¿A qué edad gatean?",
    "¿Hasta los 4 años debe ir a contramarcha en la silla del coche?",
    "Tengo 35 años y estoy agotada con mi bebé",
    "Mi marido de 40 años ronca muchísimo y despierta a la niña",
    "Hace 3 años tuve a mi primera hija y ahora me cuesta con el segundo",
    "Il y a 3 ans j'ai eu mon premier, maintenant c'est différent",
    "Mi hijo de 4 años tiene celos de su hermana de 2 meses",
    "Mi hijo de 4 años tiene muchos celos del bebé",
    "My 5-year-old keeps waking the baby, what can I do?",
    "Mi hija de 1 año y medio no camina todavía",
    "¿Cuántas horas duerme un niño de 1 a 3 años?",
    "my 18-month-old has a runny nose",
    "Mon bébé de 4 mois régurgite après chaque tétée",
    "¿Puede ir a la guardería con 2 años sin hablar?",
]


@pytest.mark.parametrize("message", OUTSIDE)
def test_a_child_of_three_or_more_is_outside_the_scope(message):
    assert child_outside_scope(message), message


@pytest.mark.parametrize("message", INSIDE)
def test_a_baby_an_adult_or_a_duration_is_not(message):
    assert not child_outside_scope(message), message


def test_the_age_band_and_wrong_age_questions_of_group_b_are_caught():
    """B7, B12, B13 and B15 name a child of 3 or more. B8 (jaundice at 4
    months) is a wrong_age question INSIDE 0-24 months and must not be."""
    caught = {q.id for q in questions("B") if child_outside_scope(q.question)}
    assert caught == {"B7", "B12", "B13", "B15"}


def test_no_group_a_question_is_affected():
    for q in questions("A"):
        assert not child_outside_scope(q.question), q.id


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_no_routing_message_is_affected(locale):
    items = json.loads((ROUTING / f"routing_{locale}.json").read_text(encoding="utf-8"))["items"]
    hit = [item["text"] for item in items if child_outside_scope(item["text"])]
    assert hit == []


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_the_reply_is_a_refusal_the_golden_gate_counts(locale):
    reply = out_of_scope_age_reply(locale)
    assert reply.endswith(no_evidence_reply(locale))
    assert is_refusal(reply, locale)
    assert "24" in reply and "—" not in reply


def test_the_set_still_has_a_b_question_the_filter_does_not_catch_per_kind():
    """The filter must not hollow out group B: every near-miss kind keeps at
    least one question that reaches retrieval and has to be refused there."""
    reaching = {q.kind for q in GOLDEN_SET if q.group == "B" and not child_outside_scope(q.question)}
    assert {"adjacent", "dose", "wrong_age", "mixed"} <= reaching
