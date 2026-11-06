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


# --- a plan she can read with the baby in her arms (settings.plan_brevity) --------
#
# Measured on 29 prod plans of 2026-11-06 (subject-prod, warnsigns-prod and the
# "on" answers of warning-signs-warnpara-{1,2}): median 365 words. The doctor
# section is the largest share (26 %, median 85 words) and is the growth we
# wanted, so it is exempt. The rest is where the rule bites: an opening of two
# sentences and 42 words, 16 loose "Evita / No le des" paragraphs under Hoy (466
# words), Hoy up to 7 bullets, and No olvides bullets of two sentences in 33 of 62.

def _brevity_line(locale):
    from adelia.services.answer_contract import PLAN_BREVITY_RULE

    return f"- {PLAN_BREVITY_RULE[locale]}\n"


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
@pytest.mark.parametrize("shape", SHAPES_)
@pytest.mark.parametrize("unasked", [False, True])
def test_with_plan_brevity_off_the_contract_is_what_it_was(monkeypatch, locale, shape, unasked):
    from adelia.config import Settings, settings
    from adelia.services.answer_contract import PLAN_BREVITY_RULE

    assert Settings.model_fields["plan_brevity"].default is False
    monkeypatch.setattr(settings, "no_unasked_refusals", unasked)
    monkeypatch.setattr(settings, "plan_brevity", False)
    contract = answer_contract(locale, shape=shape)
    assert all(rule not in contract for rule in PLAN_BREVITY_RULE.values())


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
@pytest.mark.parametrize("unasked", [False, True])
def test_with_plan_brevity_on_a_plan_gains_one_line_after_the_format_rule(
    monkeypatch, locale, unasked
):
    """On, a plan's contract is the off contract plus one line, right after the
    format clause it narrows; nothing else moves, whatever the other setting."""
    from adelia.config import settings

    monkeypatch.setattr(settings, "no_unasked_refusals", unasked)
    monkeypatch.setattr(settings, "plan_brevity", False)
    off = answer_contract(locale, shape="plan")
    monkeypatch.setattr(settings, "plan_brevity", True)
    on = answer_contract(locale, shape="plan")
    line = _brevity_line(locale)
    assert on.count(line) == 1
    assert on.replace(line, "", 1) == off
    assert f"- {CONTRACTS[locale].language_rule}\n{line}" in on


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
@pytest.mark.parametrize("unasked", [False, True])
def test_a_short_answer_never_gets_the_brevity_rule(monkeypatch, locale, unasked):
    """A short answer has no sections to count: the rule would only push a plan in."""
    from adelia.config import settings

    monkeypatch.setattr(settings, "no_unasked_refusals", unasked)
    monkeypatch.setattr(settings, "plan_brevity", False)
    off = answer_contract(locale, shape="question")
    monkeypatch.setattr(settings, "plan_brevity", True)
    assert answer_contract(locale, shape="question") == off


def _sentences(rule):
    return [s for s in rule.replace(";", ".").split(". ") if s.strip()]


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_the_brevity_rule_never_limits_the_doctor_section(locale):
    """Every sentence that carries a number is about another section, and the
    sentence that names the doctor heading lifts every count and asks for all the
    sources' signs, grouped by the urgency the source gives."""
    from adelia.services.answer_contract import PLAN_BREVITY_RULE

    rule = PLAN_BREVITY_RULE[locale]
    doctor = PLAN_HEADINGS[locale]["doctor"]
    named = [s for s in _sentences(rule) if doctor in s]
    assert named, "the rule names the doctor section"
    for sentence in named:
        assert not any(ch.isdigit() for ch in sentence), sentence
    exempt = {"es": ("no tiene límite de viñetas ni de palabras", "todas las señales",
                     "sin quitar ninguna", "agrupadas por la urgencia que da cada fuente"),
              "en": ("has no limit on bullets or words", "every sign",
                     "leaving none out", "grouped by the urgency each source gives"),
              "fr": ("n’a pas de limite de puces ni de mots", "tous les signes",
                     "sans en enlever aucun", "regroupés selon l’urgence que donne chaque source"),
              }[locale]
    joined = " ".join(named)
    for clause in exempt:
        assert clause in joined, clause


@pytest.mark.parametrize("locale, today, watch, remember, opening", [
    ("es", "como máximo 3 viñetas de acción", "como máximo 3 viñetas",
     "como máximo 2 viñetas", "menos de 25 palabras"),
    ("en", "at most 3 action bullets", "at most 3 bullets", "at most 2 bullets",
     "fewer than 25 words"),
    ("fr", "au maximum 3 puces d’action", "au maximum 3 puces", "au maximum 2 puces",
     "moins de 25 mots"),
])
def test_the_brevity_rule_counts_only_the_other_sections(locale, today, watch, remember,
                                                        opening):
    from adelia.services.answer_contract import PLAN_BREVITY_RULE

    rule = PLAN_BREVITY_RULE[locale]
    h = PLAN_HEADINGS[locale]
    sentences = [s.strip() for s in _sentences(rule)]
    quote = {"es": "«{}»", "en": "“{}”", "fr": "« {} »"}[locale]

    assert any(opening in s for s in sentences)
    for key, limit in (("today", today), ("watch", watch), ("remember", remember)):
        opens = [s for s in sentences if s.startswith(quote.format(h[key]))]
        assert len(opens) == 1 and limit in opens[0], key
    # The mothers' section keeps its own rule (1 to 3 bullets); this one leaves it alone.
    assert h["mothers"] not in rule


@pytest.mark.parametrize("locale, required", [
    ("es", ("nunca quita una señal de alarma, una precaución ni una condición",
            "«No le des» o «Evita»", "una sola frase corta",
            "no hay párrafos sueltos", "no repitas ahí una señal",
            "la frase de rechazo exacta", "nunca se omite")),
    ("en", ("never removes a warning sign, a precaution or a condition",
            "“Do not give” or “Avoid”", "one short sentence",
            "no loose paragraphs", "do not repeat there a sign",
            "the exact refusal sentence", "nothing is left out")),
    ("fr", ("n’enlève jamais un signe d’alerte, une précaution ou une condition",
            "« Ne lui donnez pas » ou « Évitez »", "une seule phrase courte",
            "pas de paragraphe isolé", "n’y répète pas un signe",
            "la phrase de refus exacte", "rien n’est omis")),
])
def test_the_brevity_rule_moves_safety_never_drops_it(locale, required):
    """Where the words went (loose "Evita" paragraphs, a second sentence of
    explanation) is where the rule cuts; a precaution becomes one Hoy bullet, a
    sign goes to the doctor section, and the coded refusal paragraph of a
    half-covered question (B9, B11) is the one paragraph it keeps."""
    from adelia.services.answer_contract import PLAN_BREVITY_RULE

    for clause in required:
        assert clause in PLAN_BREVITY_RULE[locale], clause


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
def test_the_brevity_rule_has_no_long_dashes_and_no_refusal(locale):
    from adelia.services.answer_contract import PLAN_BREVITY_RULE

    rule = PLAN_BREVITY_RULE[locale]
    assert "—" not in rule and "–" not in rule
    assert CONTRACTS[locale].refusal not in rule
    assert set(PLAN_BREVITY_RULE) == {"es", "en", "fr"}
