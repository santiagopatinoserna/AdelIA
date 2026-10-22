"""The answer is an action plan a busy parent can follow (Kenza, 2026-10-22).

A mother wants to know what to do, what to watch and when to go to the
doctor; she does not want to read the studies, only to know the plan rests on
them. The plan headings are a shared contract: the web renders a section as a
plan card only when the model used one of these exact headings, so the
wording lives in one place and the catalogues are checked against it.
"""
import json
from pathlib import Path

import pytest

from adelia.services.answer_contract import CONTRACTS, PLAN_HEADINGS, answer_contract

WEB_MESSAGES = Path(__file__).resolve().parents[2] / "web" / "messages"


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_every_locale_names_the_four_plan_sections(locale):
    headings = PLAN_HEADINGS[locale]
    assert set(headings) == {"today", "watch", "doctor", "remember"}
    rule = CONTRACTS[locale].language_rule
    for title in headings.values():
        assert f"## {title}" in rule


@pytest.mark.parametrize("locale, required", [
    ("es", ("plan de acción", "Omite un apartado si no hay nada respaldado",
            "nunca un apartado vacío", "señales de alarma de las fuentes",
            "la urgencia que indica la fuente", "ni la subas ni la bajes")),
    ("en", ("action plan", "Leave out a section when nothing supports it",
            "never an empty section", "warning signs from the sources",
            "the urgency the source states", "neither raise nor lower it")),
    ("fr", ("plan d’action", "Omets une rubrique si rien ne l’étaye",
            "jamais de rubrique vide", "signes d’alerte des sources",
            "l’urgence indiquée par la source", "sans l’augmenter ni la réduire")),
])
def test_the_plan_keeps_warning_signs_in_their_own_section(locale, required):
    rule = CONTRACTS[locale].language_rule
    for clause in required:
        assert clause in rule


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_the_plan_never_relaxes_the_citation_contract(locale):
    contract = answer_contract(locale)
    assert "NO interpretes ni aconsejes sin respaldo de investigación" in contract
    assert CONTRACTS[locale].refusal in contract


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_the_web_catalogue_uses_the_same_plan_headings(locale):
    messages = json.loads((WEB_MESSAGES / f"{locale}.json").read_text(encoding="utf-8"))
    plan = messages["demo"]["plan"]
    for key, title in PLAN_HEADINGS[locale].items():
        assert plan[key] == title
