"""The privacy policy must name every processor it closes the list on (audit 1.12).

`privacy.whereBody` ended with "Ningún dato va más allá de estos cuatro" while
Cloudflare terminated the TLS of adelia.godi.ai and the tunnel crossed its
network, so the health data of minors went through a fifth party the text never
named. A privacy policy with a false sentence turns an ordinary incident into a
notifiable one, and the sentence stayed false because nothing tied the number
to the list. This does: add a processor to PROCESSORS and the count in the
three catalogs has to change in the same commit.

It also pins the medical notice inside the "Un dia con AdelIA" block of the
landing (audit 1.2): the only "does not replace medical advice" used to live in
the footer, far from the fever and paracetamol it qualifies.

These are pure file reads, no database and no network.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MESSAGES_DIR = REPO_ROOT / "apps" / "web" / "messages"
DPIA = REPO_ROOT / "docs" / "legal" / "dpia-grabacion-consulta.md"
LOCALES = ["es", "en", "fr"]

#: Everyone `privacy.whereBody` names as a processor today. Telegram is
#: optional for the user but is still a party the data crosses. Anthropic was
#: added on 2026-11-03, before LLM_PROVIDER=anthropic was switched on in prod.
PROCESSORS = ["Anthropic", "Mistral", "Stripe", "Resend", "Cloudflare", "Telegram"]

#: The closing sentence per locale, with the number as a word.
CLOSING = {
    "es": re.compile(r"Ningún dato va más allá de estos (\w+)\."),
    "en": re.compile(r"Nothing goes further than these (\w+)\."),
    "fr": re.compile(r"Aucune donnée ne va plus loin que ces (\w+)-là\."),
}
NUMBER_WORDS = {
    "es": {4: "cuatro", 5: "cinco", 6: "seis", 7: "siete"},
    "en": {4: "four", 5: "five", 6: "six", 7: "seven"},
    "fr": {4: "quatre", 5: "cinq", 6: "six", 7: "sept"},
}
#: What Cloudflare does to the traffic and why the transfer is lawful, per locale.
CLOUDFLARE_ROLE = {
    "es": ["TLS", "red de distribución", "túnel", "Marco de Privacidad de Datos", "cláusulas contractuales tipo"],
    "en": ["TLS", "content delivery network", "tunnel", "Data Privacy Framework", "standard contractual clauses"],
    "fr": ["TLS", "réseau de diffusion", "tunnel", "Data Privacy Framework", "clauses contractuelles types"],
}
#: What Anthropic does, where, and why the transfer is lawful, per locale.
ANTHROPIC_ROLE = {
    "es": ["Claude", "fuera de la UE", "cláusulas contractuales tipo", "entrenar"],
    "en": ["Claude", "outside the EU", "standard contractual clauses", "train"],
    "fr": ["Claude", "hors de l’UE", "clauses contractuelles types", "entraîner"],
}
#: The sentence /profesionales carried while every model ran in the EU. With the
#: consultation summary and extraction on Claude it is false, so it must be gone.
PROFESSIONALS_EU_ONLY = {
    "es": "se alojan y procesan en la Unión Europea",
    "en": "hosted and processed in the European Union",
    "fr": "hébergées et traitées dans l'Union européenne",
}
#: The phrase the audit asked to bring into the block, per locale.
NOT_A_SUBSTITUTE = {
    "es": "no sustituye el consejo médico",
    "en": "does not replace medical advice",
    "fr": "ne remplace pas l’avis médical",
}


def _catalog(locale: str) -> dict:
    return json.loads((MESSAGES_DIR / f"{locale}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("locale", LOCALES)
def test_where_body_names_every_processor(locale):
    body = _catalog(locale)["privacy"]["whereBody"]
    missing = [name for name in PROCESSORS if name not in body]
    assert not missing, f"privacy.whereBody ({locale}) does not name {missing}"


@pytest.mark.parametrize("locale", LOCALES)
def test_the_closing_count_matches_the_number_of_processors(locale):
    body = _catalog(locale)["privacy"]["whereBody"]
    found = CLOSING[locale].findall(body)
    assert len(found) == 1, f"privacy.whereBody ({locale}) must close the list exactly once"
    expected = NUMBER_WORDS[locale][len(PROCESSORS)]
    assert found[0] == expected, (
        f"privacy.whereBody ({locale}) says '{found[0]}' but {len(PROCESSORS)} processors "
        f"are named ({expected}). Change the sentence in the same commit as the list."
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_cloudflare_is_declared_with_its_real_role_and_transfer_basis(locale):
    body = _catalog(locale)["privacy"]["whereBody"]
    start = body.index("Cloudflare")
    # The Cloudflare passage ends where the optional Telegram one starts.
    passage = body[start : body.index("Telegram", start)]
    missing = [term for term in CLOUDFLARE_ROLE[locale] if term not in passage]
    assert not missing, f"the Cloudflare passage ({locale}) lacks {missing}"


#: The month the policy carries after the Anthropic change, per locale.
UPDATED_MONTH = {"es": "noviembre", "en": "November", "fr": "novembre"}


@pytest.mark.parametrize("locale", LOCALES)
def test_the_policy_date_moves_with_the_policy(locale):
    # The Cloudflare declaration changed the policy on 2026-10-14, the
    # Anthropic one on 2026-11-03, and on 2026-11-08 the AI usage counter, the
    # consented visitor journeys with their cookies section and the clicks on
    # our short links. A policy that changes under an older "last updated"
    # date is itself a misstatement.
    updated = _catalog(locale)["privacy"]["updated"]
    assert re.search(r"\b8\b", updated) and "2026" in updated and UPDATED_MONTH[locale] in updated, (
        f"privacy.updated ({locale}) does not carry the 2026-11-08 change: {updated}"
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_anthropic_is_declared_with_its_role_location_and_transfer_basis(locale):
    body = _catalog(locale)["privacy"]["whereBody"]
    start = body.index("Anthropic")
    # The Anthropic passage ends where the Mistral one starts.
    passage = body[start : body.index("Mistral", start)]
    missing = [term for term in ANTHROPIC_ROLE[locale] if term not in passage]
    assert not missing, f"the Anthropic passage ({locale}) lacks {missing}"


@pytest.mark.parametrize("locale", LOCALES)
def test_the_professionals_page_no_longer_promises_eu_only_processing(locale):
    body = _catalog(locale)["professionals"]["whereBody"]
    assert "Anthropic" in body and "Mistral" in body
    assert PROFESSIONALS_EU_ONLY[locale] not in body


def test_the_dpia_declares_cloudflare_and_dates_the_change():
    text = DPIA.read_text(encoding="utf-8")
    assert "Cloudflare" in text
    # The addition is recorded after the 2026-08-19 sign-off, not folded into it.
    assert "## 7. Actualizaciones posteriores al cierre" in text
    assert text.index("## 7. Actualizaciones posteriores al cierre") > text.index("Firmado:")
    assert "2026-10-14" in text


def test_the_dpia_declares_anthropic_and_dates_the_change():
    text = DPIA.read_text(encoding="utf-8")
    updates = text.split("## 7. Actualizaciones posteriores al cierre")[-1]
    assert "Anthropic" in text.split("## 1. Descripción del tratamiento")[0]
    assert "2026-11-03" in updates and "Anthropic" in updates


@pytest.mark.parametrize("locale", LOCALES)
def test_the_landing_day_block_carries_its_own_medical_notice(locale):
    day = _catalog(locale)["home"]["day"]
    notice = day.get("disclaimer", "")
    assert NOT_A_SUBSTITUTE[locale] in notice
    # It names the emergency number the answer contract uses for ES and FR.
    assert "112" in notice
    # The 11px footnote under the CTA stays what it was: a statement about the data.
    assert notice != day["footnote"]


@pytest.mark.parametrize("locale", LOCALES)
def test_new_legal_prose_has_no_em_dash(locale):
    cat = _catalog(locale)
    for text in (
        cat["privacy"]["whereBody"],
        cat["professionals"]["whereBody"],
        cat["home"]["day"]["disclaimer"],
    ):
        assert "—" not in text
    assert "—" not in DPIA.read_text(encoding="utf-8").split("## 7. Actualizaciones")[-1]


#: What the AI usage counter adds up and what it never keeps (services/usage,
#: integrated 2026-11-08), per locale; and the count of "four numbers" that
#: stopped being the whole of what is counted.
USAGE_COUNTER = {
    "es": (["proveedor de IA", "tokens", "páginas", "segundos de audio",
            "no se guarda de quién es la llamada ni lo que decía"], "cuatro números agregados"),
    "en": (["AI provider", "tokens", "pages", "seconds of audio",
            "we keep neither whose call it was nor what it said"], "four aggregate numbers"),
    "fr": (["fournisseur d’IA", "tokens", "pages", "secondes d’audio",
            "on ne garde ni à qui est l’appel ni ce qu’il disait"], "quatre chiffres agrégés"),
}


@pytest.mark.parametrize("locale", LOCALES)
def test_the_counters_section_declares_the_ai_usage_count(locale):
    privacy = _catalog(locale)["privacy"]
    says, stale = USAGE_COUNTER[locale]
    for phrase in says:
        assert phrase in privacy["countersBody"], (locale, phrase)
    assert stale not in privacy["whereBody"], locale


#: The clicks on our short links of the social networks (/r/<code>,
#: services/short_links, 2026-11-08): counted like a visit, per code, and the
#: counters section says so, and that the count says which post, not who.
SHORT_LINKS = {
    "es": ["adelia.godi.ai/r/", "qué publicación se abrió, no quién la abrió"],
    "en": ["adelia.godi.ai/r/", "which post was opened, not who opened it"],
    "fr": ["adelia.godi.ai/r/", "quelle publication a été ouverte, pas qui l’a ouverte"],
}


@pytest.mark.parametrize("locale", LOCALES)
def test_the_counters_section_declares_the_short_link_clicks(locale):
    body = _catalog(locale)["privacy"]["countersBody"]
    for phrase in SHORT_LINKS[locale]:
        assert phrase in body, (locale, phrase)

