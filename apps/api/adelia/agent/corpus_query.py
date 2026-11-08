"""The evidence corpus is searched in Spanish, whatever language the parent writes in.

Measured in production on 2026-11-03 (mistral-embed, cut-off 0.19). The corpus
is 1029 Spanish chunks plus the 18 English chunks of the adult seed; its French
and English sources are summarised in Spanish. A question asked in another
language lands 0.02 to 0.08 farther from the same fragments than its Spanish
twin. Over eight golden topics asked three ways, Spanish was answered 8/8,
French 7/8 and English 4/8. The home QA's "Mon bébé de 4 mois régurgite après
chaque tétée, ça m'inquiète" sat at 0.219, where the Spanish sentence sat at
0.162, so the demo said it had no sources on the commonest worry of the first
months. The cut-off was calibrated on Spanish questions
(docs/CALIBRACION_UMBRAL_EVIDENCIA.md), so a Spanish rendering is what it
describes. Loosening it per language would first need an out-of-corpus
calibration in each language.

So a French or English question is translated before it is embedded, and only
for the corpus:

* her own documents are searched with what she wrote, in her language;
* the model answers the original question, in her locale;
* the red-flag guard has already run on the original text, before this.

The translation is one call to the small model `route` already uses, through
the same provider plumbing (`route._complete_json`, looked up at call time so
the suite's guard in conftest reaches it). The question goes to the provider
that answers it anyway, so no new processor sees it. The call is best-effort
under a deadline: no key, a timeout, an invalid reply or a reply that does not
look like a translation all fall back to the original text, which is what every
surface embedded before this module existed.
"""
from __future__ import annotations

import asyncio
import json
import logging

from adelia.agent import route
from adelia.services import usage

logger = logging.getLogger(__name__)

CORPUS_LANGUAGE = "es"
#: Locales whose questions are translated. Spanish is the corpus's own; any
#: other value is embedded as written.
TRANSLATED_LOCALES: tuple[str, ...] = ("en", "fr")
#: Longer than route's 2 s: the reply is a sentence, not a one-word decision.
TRANSLATE_TIMEOUT_S = 3.0

_SYSTEM_PROMPT = """You translate a parent's message about a baby into Spanish (Spain), so it can be
searched in a Spanish pediatric library.

Translate faithfully. Keep every symptom, age, number, duration and unit. Do not answer the
message, explain, summarise, correct or add anything. If the message is already in Spanish,
return it unchanged.

Reply with JSON only: {"es": "<the Spanish text>"}"""


def needs_translation(locale: str | None) -> bool:
    return (locale or CORPUS_LANGUAGE).split("-")[0].lower() in TRANSLATED_LOCALES


def _looks_like_translation(source: str, candidate: str) -> bool:
    """A reply several times longer than the message answered it instead."""
    return bool(candidate) and len(candidate) <= 2 * len(source) + 80


async def corpus_query(
    text: str,
    locale: str | None,
    *,
    provider: str | None = None,
    timeout_s: float = TRANSLATE_TIMEOUT_S,
) -> str:
    """`text` in the corpus's language, or `text` itself. Never raises.

    `provider` is the surface's generation provider (the demo passes
    `demo_llm_provider`), so the question is translated by whoever answers it.
    Nothing here logs the message.
    """
    source = text.strip()
    if not source or not needs_translation(locale):
        return text
    try:
        with usage.json_purpose("translate"):
            raw = await asyncio.wait_for(
                route._complete_json(_SYSTEM_PROMPT, source, provider=provider), timeout=timeout_s
            )
    except asyncio.TimeoutError:
        logger.info("corpus_query: translation exceeded %.1fs, embedding the original", timeout_s)
        return text
    except Exception as exc:  # noqa: BLE001 - a failed translation costs recall, not the answer
        logger.info("corpus_query: translation unavailable (%s), embedding the original",
                    type(exc).__name__)
        return text
    try:
        candidate = json.loads(route._fence_free(raw)).get(CORPUS_LANGUAGE)
    except (ValueError, TypeError, AttributeError):
        candidate = None
    if not isinstance(candidate, str) or not _looks_like_translation(source, candidate.strip()):
        logger.info("corpus_query: reply was not a translation, embedding the original")
        return text
    return candidate.strip()
