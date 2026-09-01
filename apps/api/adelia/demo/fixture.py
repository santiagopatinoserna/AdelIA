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


_CONTENT: dict[str, dict] = {
    "es": {
        "baby_name": "Lucía",
        "age_label": "5 meses",
        "banner": (
            "Demo pública. Lucía es un bebé inventado y su historial también: "
            "sirve para enseñar cómo responde AdelIA. No se guarda nada de lo que "
            "escribas aquí."
        ),
        "record_title": "El historial de Lucía",
        "record_note": "Datos ficticios de ejemplo",
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
            "¿Es normal que Lucía regurgite después de casi todas las tomas?",
            "¿Cuándo conviene empezar la alimentación complementaria?",
            "Su hemoglobina es 10,8 g/dL. ¿Qué significa a los 5 meses?",
        ],
        "context_intro": "Bebé de la demo (datos ficticios).",
    },
    "en": {
        "baby_name": "Lucía",
        "age_label": "5 months",
        "banner": (
            "Public demo. Lucía is a made-up baby and so is her record: it is here "
            "to show how AdelIA answers. Nothing you type is saved."
        ),
        "record_title": "Lucía's record",
        "record_note": "Fictional sample data",
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
            "Is it normal for Lucía to spit up after almost every feed?",
            "When should complementary feeding start?",
            "Her haemoglobin is 10.8 g/dL. What does that mean at 5 months?",
        ],
        "context_intro": "Demo baby (fictional data).",
    },
    "fr": {
        "baby_name": "Lucía",
        "age_label": "5 mois",
        "banner": (
            "Démo publique. Lucía est un bébé inventé, et son dossier aussi : il sert "
            "à montrer comment AdelIA répond. Rien de ce que tu écris ici n’est "
            "conservé."
        ),
        "record_title": "Le dossier de Lucía",
        "record_note": "Données fictives d’exemple",
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
            "Est-ce normal que Lucía régurgite après presque chaque tétée ?",
            "Quand faut-il commencer la diversification alimentaire ?",
            "Son hémoglobine est à 10,8 g/dL. Qu’est-ce que ça veut dire à 5 mois ?",
        ],
        "context_intro": "Bébé de la démo (données fictives).",
    },
}


def _resolve(locale: str) -> tuple[str, dict]:
    key = (locale or DEFAULT_LOCALE).split("-")[0].lower()
    if key not in _CONTENT:
        key = DEFAULT_LOCALE
    return key, _CONTENT[key]


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
