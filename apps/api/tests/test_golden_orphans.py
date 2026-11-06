"""count_orphan_citations: a card under an answer that the answer never cites.

The deploy gate failed its first real run in production (2026-11-06) on one
"orphan": A6 is a red flag, answered by the fixed alarm text, and carries the
flag's guideline card (red_flags.citation_for). That card is the basis of a
deterministic rule, not a source the model claims to have used, and the alarm
text has no markers by design. It is not the "looks sourced, is not" shape the
metric exists to catch.
"""
from __future__ import annotations

from adelia.clinical.golden import count_orphan_citations
from adelia.clinical.red_flags import citation_for, detect


def _card(tag: str, **extra) -> dict:
    return {"tag": tag, "source_id": f"src-{tag}", "title": f"Guía {tag}", **extra}


def test_an_uncited_card_is_an_orphan():
    assert count_orphan_citations("Dale pecho a demanda [ev_1].", [_card("ev_1"), _card("ev_2")]) == 1


def test_cited_cards_are_not_orphans():
    assert count_orphan_citations("Uno [ev_1] y dos [ev_2].", [_card("ev_1"), _card("ev_2")]) == 0


def test_the_red_flag_guideline_card_is_not_an_orphan():
    flag = detect("Tiene 2 meses y 38,2 de fiebre")
    assert flag is not None
    alarm = "Esto no puede esperar a una respuesta mía. Llama al 112 o acude a urgencias."
    assert count_orphan_citations(alarm, [citation_for(flag)]) == 0


def test_a_regular_card_beside_the_red_flag_card_still_counts():
    flag = detect("Tiene 2 meses y 38,2 de fiebre")
    assert flag is not None
    alarm = "Esto no puede esperar a una respuesta mía."
    assert count_orphan_citations(alarm, [citation_for(flag), _card("ev_2")]) == 1
