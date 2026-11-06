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

from adelia.services.answer_contract import (
    CONTRACTS,
    NO_UNASKED_DOCTOR_RULE,
    NO_UNASKED_REFUSALS_RULE,
    PLAN_HEADINGS,
    answer_contract,
)

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


# --- the refusal is only for what she asked (settings.no_unasked_refusals) --------
#
# Measured in prod on 2026-11-06 (demo, Claude, 30 real questions): four good
# plans carried a section the model made up and closed with the coded refusal:
# "Cremas o pomadas para el pañal", "Edad exacta en meses", "Cómo corregirla"
# and, under the croup plan, "Señales de alarma y cuándo acudir a urgencias:
# No tengo evidencia...". She asked none of them. Behind the setting, the
# contract says the refusal is for what she asked and the sources do not cover,
# and an unasked part without a source is left out like an empty plan section.

SHAPES_ = ("plan", "question")


@pytest.mark.parametrize("locale, required", [
    ("es", ("solo para lo que la madre ha preguntado y las fuentes no cubren",
            "que ella no ha pedido", "cremas", "una edad exacta", "cómo corregirlo",
            "omítelo", "como se omite un apartado vacío del plan",
            "nunca quita una señal de alarma que las fuentes sí traen")),
    ("en", ("only for what the parent asked and the sources do not cover",
            "she did not ask for", "creams", "an exact age", "how to correct it",
            "leave it out", "the way an empty plan section is left out",
            "never removes a warning sign the sources do carry")),
    ("fr", ("réservée à ce que le parent a demandé et que les sources ne couvrent pas",
            "qu’il n’a pas demandé", "crèmes", "un âge exact", "comment le corriger",
            "omets-le", "comme on omet une rubrique vide du plan",
            "n’enlève jamais un signe d’alerte que les sources apportent")),
])
def test_the_unasked_refusal_rule_says_the_same_in_each_language(locale, required):
    for clause in required:
        assert clause in NO_UNASKED_REFUSALS_RULE[locale]


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
@pytest.mark.parametrize("shape", SHAPES_)
def test_with_the_setting_off_the_contract_is_what_it_was(monkeypatch, locale, shape):
    from adelia.config import Settings, settings

    assert Settings.model_fields["no_unasked_refusals"].default is False
    monkeypatch.setattr(settings, "no_unasked_refusals", False)
    contract = answer_contract(locale, shape=shape)
    assert all(rule not in contract for rule in NO_UNASKED_REFUSALS_RULE.values())


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
@pytest.mark.parametrize("shape", SHAPES_)
def test_with_the_setting_on_the_rule_is_one_more_line_and_nothing_else(
    monkeypatch, locale, shape
):
    """On, the contract gains the unasked-refusal line and, for a plan only, the
    doctor-section line right after it; nothing else moves."""
    from adelia.config import settings

    monkeypatch.setattr(settings, "no_unasked_refusals", False)
    off = answer_contract(locale, shape=shape)
    monkeypatch.setattr(settings, "no_unasked_refusals", True)
    on = answer_contract(locale, shape=shape)
    line = f"- {NO_UNASKED_REFUSALS_RULE[locale]}\n"
    if shape == "plan":
        line += f"- {NO_UNASKED_DOCTOR_RULE[locale]}\n"
    assert on.count(line) == 1
    assert on.replace(line, "", 1) == off


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_a_short_answer_never_gets_the_doctor_section_line(monkeypatch, locale):
    """A short answer has no plan sections: the clause would only push one in."""
    from adelia.config import settings

    monkeypatch.setattr(settings, "no_unasked_refusals", True)
    assert NO_UNASKED_DOCTOR_RULE[locale] not in answer_contract(locale, shape="question")
    assert NO_UNASKED_DOCTOR_RULE[locale] in answer_contract(locale, shape="plan")


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_the_doctor_section_is_never_an_unasked_one(locale):
    """Measured in prod on 2026-11-06 with the rule on: croup and bronchiolitis
    plans had the urgency fragment ("Ve a urgencias si hace ruido al coger aire
    aunque esté tranquila", Laringitis AEPap; SEUP and AEP for bronchiolitis)
    and still left the signs under Vigila with no action and no doctor section,
    while the same croup question with a dose in it wrote the section. The
    section is never 'unasked', and a sign whose action a source gives never
    stays only under the watch heading."""
    rule = NO_UNASKED_DOCTOR_RULE[locale]
    headings = PLAN_HEADINGS[locale]
    assert headings["doctor"] in rule and headings["watch"] in rule
    assert {"es": "nunca es un apartado que ella no ha pedido",
            "en": "never a section she did not ask for",
            "fr": "n’est jamais une rubrique qu’il n’a pas demandée"}[locale] in rule
    assert {"es": "la urgencia que da la fuente",
            "en": "the urgency the source gives",
            "fr": "l’urgence que donne la source"}[locale] in rule
    assert CONTRACTS[locale].refusal not in rule
    assert "—" not in rule and "–" not in rule


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_with_the_rule_on_a_mixed_question_still_refuses_its_dose(monkeypatch, locale):
    """B9 and B11: she asked the dose, so the dose half keeps the coded refusal."""
    from adelia.config import settings

    monkeypatch.setattr(settings, "no_unasked_refusals", True)
    contract = answer_contract(locale)
    assert "Si solo una parte de la pregunta tiene respaldo en las fuentes" in contract
    assert "una dosis que ningún fragmento menciona" in contract
    assert contract.count(CONTRACTS[locale].refusal) == 2
    assert "Si no tienes ninguna base documental" in contract
    assert CONTRACTS[locale].language_rule in contract
    # The rule sits right after the partial-coverage clause it narrows.
    assert contract.index("Si solo una parte") < contract.index(
        NO_UNASKED_REFUSALS_RULE[locale]
    ) < contract.index("Si no tienes ninguna base documental")
