"""The demo baby (audit 4.6). Invented, in memory, in three languages.

Nothing here is a person and nothing here is written anywhere. The fixture is
a module-level constant the demo endpoints read; the public demo therefore
cannot create a user, cannot touch another account's record, and cannot leave
a row behind, because there is no code path from /demo to a write.

Three properties this fixture must keep:

1. It is OBVIOUSLY fictional. Every locale names the baby and says so in the
   record itself, and the page repeats it in a banner. A demo of a health
   product that looks like a real child's file is a liability, not a demo.
2. It ages with the reader. Dates are offsets from today, not literals, so the
   demo is never "a report from eight months ago" and the numbers never stop
   matching the stated age.
3. The card shown on the page and the context handed to the model come from
   the SAME dict, so the answer can never contradict what the visitor is
   looking at.

The clinical numbers are plausible values for a five-month-old and are used
only to make the demo concrete: they are not guidance, and the evidence the
answer cites comes from the real corpus, not from here.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

DEMO_LOCALES = ("es", "en", "fr")
DEFAULT_LOCALE = "es"

# The baby is always this old, whatever day the demo is opened.
AGE_MONTHS = 5
# Day offsets, counted back from today, for each record item.
_REPORT_DAYS_AGO = 26
_LAB_DAYS_AGO = 12
_CONSULT_DAYS_AGO = 5
_DIARY_DAYS_AGO = 1


def _dob(today: date) -> date:
    """A date of birth that keeps the baby at AGE_MONTHS months."""
    return today - timedelta(days=AGE_MONTHS * 30 + 12)


# What stands in for the baby's name when a question goes to the corpus search.
# A first name is not clinical content and it costs relevance: on 2026-10-14 the
# demo's own first suggestion moved from distance 0.154 ("mi bebé") to 0.261
# ("Lucía"), past the 0.19 cut-off, and the demo refused its own example.
_NEUTRAL_SUBJECT = {"es": "mi bebé", "en": "my baby", "fr": "mon bébé"}

_CONTENT: dict[str, dict] = {
    "es": {
        "baby_name": "Lucía",
        "age_label": "5 meses",
        "banner": (
            "Esta es la historia de Lucía, creada para que puedas probar AdelIA. "
            "Sus revisiones y consultas te ayudarán a ver cómo tiene en cuenta "
            "lo que le ha ido pasando. No se guarda nada de lo que escribas aquí."
        ),
        "record_title": "La historia de Lucía",
        "record_note": "Su historia hasta hoy",
        "items": [
            {
                "kind": "report",
                "title": "Informe de la revisión de los 4 meses",
                "meta": "Pediatría · Centro de salud (ejemplo)",
                "lines": [
                    "Peso 6,4 kg · Talla 63 cm · Perímetro craneal 41,5 cm",
                    "Regurgitaciones tras casi todas las tomas, sin pérdida de peso.",
                    "Pauta: tomas más frecuentes y menor volumen, revisión en 2 meses.",
                ],
            },
            {
                "kind": "lab",
                "title": "Analítica de sangre",
                "meta": "Hematología · Laboratorio (ejemplo)",
                "lines": [
                    "Hemoglobina 10,8 g/dL",
                    "Ferritina 18 ng/mL",
                    "Leucocitos 9,2 x10⁹/L",
                ],
            },
            {
                "kind": "consulta",
                "title": "Consulta grabada (12 min)",
                "meta": "Transcripción resumida · el audio se borra a las 48 h",
                "lines": [
                    "La pediatra descarta alergia a la proteína de la leche de vaca.",
                    "Recomienda empezar la alimentación complementaria a los 6 meses.",
                    "Pide repetir la analítica si sigue cansada o come peor.",
                ],
            },
            {
                "kind": "diary",
                "title": "Diario de ayer",
                "meta": "Entrada escrita por Telegram",
                "lines": [
                    "Durmió 5 horas seguidas. Dos regurgitaciones tras la toma de la tarde.",
                ],
            },
        ],
        "suggested": [
            "¿Es normal que mi bebé regurgite después de casi todas las tomas?",
            "Con su edad, la lactancia y lo que indicó su pediatra, ¿está preparada para empezar con otros alimentos?",
            "Está comiendo menos. Comparando sus revisiones, ¿qué debería vigilar y qué le pregunto al pediatra?",
        ],
        "context_intro": "Bebé de la demo (datos ficticios).",
    },
    "en": {
        "baby_name": "Lucía",
        "age_label": "5 months",
        "banner": (
            "Lucía’s story was created so you can try AdelIA. Her check-ups and "
            "appointments show how her history informs the answers. "
            "Nothing you type is saved."
        ),
        "record_title": "Lucía's story",
        "record_note": "Her story so far",
        "items": [
            {
                "kind": "report",
                "title": "Four-month check-up report",
                "meta": "Pediatrics · Health centre (sample)",
                "lines": [
                    "Weight 6.4 kg · Length 63 cm · Head circumference 41.5 cm",
                    "Spits up after almost every feed, no weight loss.",
                    "Plan: smaller, more frequent feeds; review in 2 months.",
                ],
            },
            {
                "kind": "lab",
                "title": "Blood test",
                "meta": "Haematology · Laboratory (sample)",
                "lines": [
                    "Haemoglobin 10.8 g/dL",
                    "Ferritin 18 ng/mL",
                    "White cells 9.2 x10⁹/L",
                ],
            },
            {
                "kind": "consulta",
                "title": "Recorded appointment (12 min)",
                "meta": "Summarised transcript · the audio is deleted within 48 h",
                "lines": [
                    "The pediatrician rules out cow's milk protein allergy.",
                    "Recommends starting complementary feeding at 6 months.",
                    "Asks to repeat the blood test if she stays tired or feeds worse.",
                ],
            },
            {
                "kind": "diary",
                "title": "Yesterday's diary",
                "meta": "Entry written through Telegram",
                "lines": [
                    "Slept 5 hours straight. Spat up twice after the afternoon feed.",
                ],
            },
        ],
        "suggested": [
            "My baby regurgitates after almost every feed. Is infant reflux normal?",
            "Considering her age, breastfeeding and her pediatrician’s advice, is she ready to start other foods?",
            "She is feeding less. Comparing her check-ups, what should I watch for and ask her pediatrician?",
        ],
        "context_intro": "Demo baby (fictional data).",
    },
    "fr": {
        "baby_name": "Lucía",
        "age_label": "5 mois",
        "banner": (
            "L’histoire de Lucía a été créée pour que tu puisses essayer AdelIA. "
            "Ses consultations montrent comment son histoire éclaire les réponses. "
            "Rien de ce que tu écris ici n’est conservé."
        ),
        "record_title": "L’histoire de Lucía",
        "record_note": "Son histoire jusqu’ici",
        "items": [
            {
                "kind": "report",
                "title": "Compte rendu de la visite des 4 mois",
                "meta": "Pédiatrie · Centre de santé (exemple)",
                "lines": [
                    "Poids 6,4 kg · Taille 63 cm · Périmètre crânien 41,5 cm",
                    "Régurgitations après presque chaque tétée, sans perte de poids.",
                    "Conduite : tétées plus fréquentes et moins volumineuses, revoir dans 2 mois.",
                ],
            },
            {
                "kind": "lab",
                "title": "Analyse de sang",
                "meta": "Hématologie · Laboratoire (exemple)",
                "lines": [
                    "Hémoglobine 10,8 g/dL",
                    "Ferritine 18 ng/mL",
                    "Leucocytes 9,2 x10⁹/L",
                ],
            },
            {
                "kind": "consulta",
                "title": "Consultation enregistrée (12 min)",
                "meta": "Transcription résumée · l’audio est effacé sous 48 h",
                "lines": [
                    "La pédiatre écarte une allergie aux protéines de lait de vache.",
                    "Elle conseille de commencer la diversification à 6 mois.",
                    "Elle demande de refaire l’analyse si la fatigue ou l’appétit persistent.",
                ],
            },
            {
                "kind": "diary",
                "title": "Journal d’hier",
                "meta": "Entrée écrite par Telegram",
                "lines": [
                    "A dormi 5 heures d’affilée. Deux régurgitations après la tétée de l’après-midi.",
                ],
            },
        ],
        "suggested": [
            "Mon bébé régurgite après chaque tétée : à partir de quand ça s’améliore ?",
            "Avec son âge, l’allaitement et l’avis de sa pédiatre, est-elle prête à découvrir d’autres aliments ?",
            "Elle mange moins. En comparant ses consultations, que dois-je surveiller et demander au pédiatre ?",
        ],
        "context_intro": "Bébé de la démo (données fictives).",
    },
}


def _resolve(locale: str) -> tuple[str, dict]:
    key = (locale or DEFAULT_LOCALE).split("-")[0].lower()
    if key not in _CONTENT:
        key = DEFAULT_LOCALE
    return key, _CONTENT[key]


def retrieval_query(question: str, locale: str = DEFAULT_LOCALE) -> str:
    """The sentence the corpus search embeds: the question without the baby's name.

    The model still reads the original question, with the name, next to the
    patient record. Only the embedding is neutralised. Case and accent are
    ignored because a visitor who types "lucia" must get the same treatment.
    """
    key, content = _resolve(locale)
    # "Lucía" -> "Luc[ií]a": the unaccented spelling is how most phones type it.
    pattern = re.compile(re.escape(content["baby_name"]).replace("í", "[ií]"), re.IGNORECASE)
    return pattern.sub(_NEUTRAL_SUBJECT[key], question)


def demo_profile(locale: str = DEFAULT_LOCALE, *, today: date | None = None) -> dict:
    """Everything the demo page renders, dated relative to today."""
    key, content = _resolve(locale)
    today = today or date.today()
    offsets = {
        "report": _REPORT_DAYS_AGO,
        "lab": _LAB_DAYS_AGO,
        "consulta": _CONSULT_DAYS_AGO,
        "diary": _DIARY_DAYS_AGO,
    }
    return {
        "locale": key,
        "is_demo": True,
        "baby_name": content["baby_name"],
        "age_months": AGE_MONTHS,
        "age_label": content["age_label"],
        "date_of_birth": _dob(today).isoformat(),
        "banner": content["banner"],
        "record_title": content["record_title"],
        "record_note": content["record_note"],
        "suggested": list(content["suggested"]),
        "items": [
            {
                "kind": item["kind"],
                "title": item["title"],
                "meta": item["meta"],
                "date": (today - timedelta(days=offsets[item["kind"]])).isoformat(),
                "lines": list(item["lines"]),
            }
            for item in content["items"]
        ],
    }


def demo_patient_context(locale: str = DEFAULT_LOCALE, *, today: date | None = None) -> str:
    """The same record, formatted as the numbered [N] block the prompt expects.

    Built from `demo_profile`, not from a second copy of the text, so the
    fragment the model cites as [2] is the card the visitor can see.
    """
    key, content = _resolve(locale)
    profile = demo_profile(key, today=today)
    lines = [
        f"[1] {content['context_intro']} {profile['baby_name']}, "
        f"{profile['age_label']}."
    ]
    for index, item in enumerate(profile["items"], start=2):
        body = " ".join(item["lines"])
        lines.append(f"[{index}] {item['title']} ({item['date']}): {body}")
    return "\n\n".join(lines)
