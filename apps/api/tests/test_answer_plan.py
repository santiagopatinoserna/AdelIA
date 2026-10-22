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
def test_every_locale_names_the_four_plan_sections_and_the_optional_fifth(locale):
    headings = PLAN_HEADINGS[locale]
    assert set(headings) == {"today", "watch", "doctor", "remember", "mothers"}
    rule = CONTRACTS[locale].language_rule
    for title in headings.values():
        assert f"## {title}" in rule


# ---------------------------------------------------------------------------
# What other mothers say (Kenza, 2026-10-22; Santiago's decision on sources)
#
# One optional section after "No olvides", fed only by the experience tier
# (public blogs and forums, cited by URL, labelled as experience). The rule
# the model reads has to say, in so many words, what the section may never
# carry: a dose, a warning sign, or anything a cited guideline contradicts.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("locale, heading", [
    ("es", "Lo que cuentan otras madres"),
    ("en", "What other mothers say"),
    ("fr", "Ce que racontent d’autres mères"),
])
def test_the_mothers_heading_is_the_agreed_wording(locale, heading):
    assert PLAN_HEADINGS[locale]["mothers"] == heading


@pytest.mark.parametrize("locale, required", [
    ("es", ("Lo que cuentan otras madres", "Después de \"## No olvides\"", "opcional",
            "[ex_N]", "1 a 3 viñetas", "nunca una dosis", "nunca una señal de alarma",
            "nunca algo que contradiga", "omítelo si no hay")),
    ("en", ("What other mothers say", "After \"## Don’t forget\"", "optional", "[ex_N]",
            "1 to 3 bullets", "never a dose", "never a warning sign",
            "never anything that contradicts", "leave it out if nothing")),
    ("fr", ("Ce que racontent d’autres mères", "Après \"## À ne pas oublier\"", "facultative",
            "[ex_N]", "1 à 3 puces", "jamais de dose", "jamais de signe d’alerte",
            "jamais rien qui contredise", "omets-la si rien")),
])
def test_the_mothers_section_rule_says_what_it_may_never_carry(locale, required):
    rule = CONTRACTS[locale].language_rule.lower()
    for clause in required:
        assert clause.lower() in rule, clause


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_the_mothers_section_comes_after_the_four_plan_sections_in_the_rule(locale):
    rule = CONTRACTS[locale].language_rule
    h = PLAN_HEADINGS[locale]
    assert rule.index(f"## {h['remember']}") < rule.index(f"## {h['mothers']}")


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_the_web_catalogue_labels_experience_as_experience(locale):
    messages = json.loads((WEB_MESSAGES / f"{locale}.json").read_text(encoding="utf-8"))
    demo = messages["demo"]
    for key in ("mothersLabel", "experienceBadge"):
        assert isinstance(demo.get(key), str) and demo[key].strip(), key
        assert "—" not in demo[key]


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
