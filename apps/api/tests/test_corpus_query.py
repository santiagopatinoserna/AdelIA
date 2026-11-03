"""A French or English question is searched in Spanish, the corpus's language.

Measured in production on 2026-11-03: the home QA's "Mon bébé de 4 mois
régurgite après chaque tétée, ça m'inquiète" had its nearest fragment at 0.219,
past the 0.19 cut-off, while the same sentence in Spanish sat at 0.162. Over
eight golden topics, French was answered 7/8 and English 4/8 against 8/8 in
Spanish (agent/corpus_query.py). These tests pin the translation and, above all,
its fallbacks: a translation that fails must cost recall, never the answer.
"""
from __future__ import annotations

import asyncio

import pytest

from adelia.agent import corpus_query as cq
from adelia.agent import route as r

SPANISH = "Mi bebé de 4 meses regurgita después de cada toma, me preocupa"
FRENCH = "Mon bébé de 4 mois régurgite après chaque tétée, ça m'inquiète"


def _reply(raw: str, calls: list | None = None):
    async def _complete(system, user, *, provider=None):
        if calls is not None:
            calls.append((system, user, provider))
        return raw

    return _complete


@pytest.mark.parametrize("locale", ["es", "es-ES", None, "de", ""])
async def test_spanish_and_unknown_locales_are_embedded_as_written(monkeypatch, locale):
    calls: list = []
    monkeypatch.setattr(r, "_complete_json", _reply('{"es": "otra cosa"}', calls))
    assert await cq.corpus_query(FRENCH, locale) == FRENCH
    assert calls == [], "no translation call for the corpus's own language"


@pytest.mark.parametrize("locale", ["fr", "en", "fr-FR", "EN"])
async def test_french_and_english_are_translated(monkeypatch, locale):
    calls: list = []
    monkeypatch.setattr(r, "_complete_json", _reply(f'{{"es": "{SPANISH}"}}', calls))
    assert await cq.corpus_query(FRENCH, locale) == SPANISH
    (_, user, _), = calls
    assert user == FRENCH


async def test_the_translation_goes_to_the_surfaces_provider(monkeypatch):
    """The question goes to whoever answers it anyway, so no new processor."""
    calls: list = []
    monkeypatch.setattr(r, "_complete_json", _reply(f'{{"es": "{SPANISH}"}}', calls))
    await cq.corpus_query(FRENCH, "fr", provider="anthropic")
    assert calls[0][2] == "anthropic"


async def test_a_fenced_reply_is_read(monkeypatch):
    monkeypatch.setattr(r, "_complete_json", _reply(f'```json\n{{"es": "{SPANISH}"}}\n```'))
    assert await cq.corpus_query(FRENCH, "fr") == SPANISH


@pytest.mark.parametrize("raw", [
    "Mi bebé regurgita",                       # not JSON
    '["Mi bebé regurgita"]',                   # JSON, not an object
    '{"fr": "Mon bébé"}',                      # the wrong key
    '{"es": 42}',                              # not a string
    '{"es": "   "}',                           # empty
    '{"es": "' + "La regurgitación es normal. " * 20 + '"}',  # an answer, not a translation
])
async def test_a_reply_that_is_not_a_translation_falls_back_to_the_original(monkeypatch, raw):
    monkeypatch.setattr(r, "_complete_json", _reply(raw))
    assert await cq.corpus_query(FRENCH, "fr") == FRENCH


async def test_a_provider_error_falls_back_to_the_original(monkeypatch):
    async def _down(system, user, *, provider=None):
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    monkeypatch.setattr(r, "_complete_json", _down)
    assert await cq.corpus_query(FRENCH, "fr") == FRENCH


async def test_a_slow_provider_costs_the_deadline_and_nothing_more(monkeypatch):
    async def _slow(system, user, *, provider=None):
        await asyncio.sleep(5)
        return f'{{"es": "{SPANISH}"}}'

    monkeypatch.setattr(r, "_complete_json", _slow)
    assert await cq.corpus_query(FRENCH, "fr", timeout_s=0.05) == FRENCH


async def test_an_empty_message_is_not_sent(monkeypatch):
    calls: list = []
    monkeypatch.setattr(r, "_complete_json", _reply('{"es": "algo"}', calls))
    assert await cq.corpus_query("   ", "fr") == "   "
    assert calls == []


async def test_the_suite_never_translates_live():
    """conftest disables `route._complete_json`, and corpus_query looks it up
    at call time, so a run with a key in the environment still embeds the
    original instead of spending credit on every French test question."""
    assert await cq.corpus_query(FRENCH, "fr") == FRENCH
