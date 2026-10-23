"""Requests for what only the tools do go to `track` (AGENT_GRAPH step 5).

Briefings and profile fixes are write tools behind a confirmation card;
clinical trials and drug interactions are read tools. None of them is a
plan or a fact question, and a contract answer would not run the tool. The
rules send them to the tool loop whatever the classifier says, or does not
say when it is down (it answered 429 to every call in production on
2026-10-23). Without an account there are no tools: a question.
"""
from __future__ import annotations

import pytest

from adelia.agent.route import route_by_rules
from adelia.enrichment.profile_service import ProfileFacts

AGE = ProfileFacts(None, None, None, None, 6)


@pytest.mark.parametrize("text", [
    "prepárame el briefing para el neurólogo",
    "genera un resumen para la pediatra de mañana",
    "hazme un informe para el especialista",
    "su fecha de nacimiento es el 3 de mayo de 2026",
    "guarda en su perfil que es niña",
    "¿hay ensayos clínicos sobre la dermatitis atópica?",
    "¿hay interacciones entre el ibuprofeno y el antibiótico?",
    "make a briefing for the dermatologist",
    "prépare un résumé pour le pédiatre",
])
def test_tool_requests_go_to_the_tool_loop(text):
    d = route_by_rules(text, has_account=True, facts=AGE)
    assert d is not None and d.intent == "track", d


def test_without_an_account_there_are_no_tools():
    d = route_by_rules("prepárame el briefing para el neurólogo", has_account=False, facts=AGE)
    assert d is not None and d.intent == "question"
