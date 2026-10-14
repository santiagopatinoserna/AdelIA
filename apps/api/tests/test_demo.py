"""The public demo answers without an account and writes nothing (4.6).

The audit's third existential risk is that nobody has checked whether anyone
wants this, and the reason nobody could check is that seeing AdelIA answer one
question required an email, a magic link and a credit card. /demo removes all
three. What it must NOT remove is the safety contract or the spending brakes,
which is most of what is asserted here.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
import sqlalchemy as sa

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.demo.fixture import DEMO_LOCALES, demo_patient_context, demo_profile
from adelia.models import Chunk, Document, FunnelCounter, User

from tests.pg_gate import PG_AVAILABLE


# --- The fixture: no database, three languages, ages with the reader --------


def test_the_demo_baby_exists_in_every_language_the_product_ships():
    for locale in DEMO_LOCALES:
        profile = demo_profile(locale)
        assert profile["is_demo"] is True
        assert profile["baby_name"]
        assert profile["banner"], f"{locale}: the demo must say it is a demo"
        assert len(profile["items"]) >= 3
        assert len(profile["suggested"]) >= 3


def test_an_unknown_locale_falls_back_instead_of_failing():
    assert demo_profile("pt")["locale"] == "es"
    assert demo_profile("fr-CA")["locale"] == "fr"


def test_the_demo_baby_never_gets_older():
    """Dates are offsets from today, so the demo is never "a report from
    eight months ago" and the numbers never stop matching the stated age."""
    profile = demo_profile("es", today=date(2027, 5, 3))

    assert profile["age_months"] == demo_profile("es", today=date(2026, 1, 1))["age_months"]
    assert all(item["date"].startswith("2027") for item in profile["items"])


def test_the_card_and_the_prompt_read_the_same_record():
    """The context handed to the model is built FROM the profile, so the
    answer cannot cite a fragment the visitor is not looking at."""
    profile = demo_profile("es")
    context = demo_patient_context("es")

    for item in profile["items"]:
        assert item["title"] in context


def test_the_french_fixture_follows_french_typography():
    """Same rule the web catalogues are held to (check-i18n-parity.mjs), on
    the one piece of user-facing French that does not live in messages/fr.json.

    U+00A0 before : ; ? ! and the typographic apostrophe ’. A demo whose copy
    reads as machine-translated is a demo that argues against the product.
    """
    profile = demo_profile("fr")
    strings = [profile["banner"], profile["record_title"], profile["record_note"]]
    strings += profile["suggested"]
    for item in profile["items"]:
        strings += [item["title"], item["meta"], *item["lines"]]

    for text in strings:
        assert "'" not in text, f"straight apostrophe in {text!r}"
        for mark in (":", ";", "?", "!"):
            index = text.find(mark)
            assert index <= 0 or text[index - 1] != " ", (
                f"plain space before {mark!r} in {text!r}"
            )


# --- The endpoints ----------------------------------------------------------

pg_only = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")


async def test_the_profile_is_public(client):
    resp = await client.get("/demo/profile?locale=fr")

    assert resp.status_code == 200, resp.text
    assert resp.json()["age_label"] == "5 mois"


async def test_the_demo_can_be_switched_off(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_enabled", False)

    assert (await client.get("/demo/profile")).status_code == 503
    assert (
        await client.post("/demo/ask", json={"question": "hola qué tal"})
    ).status_code == 503


@pg_only
async def test_a_red_flag_never_reaches_the_model_or_the_budget(client):
    """The safety rule of the whole product, on its most public surface: a
    fever in a two-month-old is answered by the code, with its guideline, and
    neither the embedding nor the generation is called."""
    with patch("adelia.routers.demo.embed_texts") as embed, patch(
        "adelia.routers.demo.generate_answer"
    ) as generate:
        resp = await client.post(
            "/demo/ask",
            json={
                "question": "Mi bebé de 2 meses tiene 38,4 de fiebre, ¿le doy paracetamol?",
                "locale": "es",
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "red_flag"
    assert body["evidence_citations"], "a referral still shows its guideline"
    assert body["disclaimer"]
    embed.assert_not_called()
    generate.assert_not_called()


@pg_only
async def test_an_answer_carries_real_corpus_citations(client):
    """The promise of the demo: the [ev_N] cards come from evidence_chunks,
    with the titles and URLs of real guidelines, not from a script."""
    from adelia.enrichment.evidence_retrieval import EvidenceMatch
    import uuid as _uuid

    match = EvidenceMatch(
        chunk_id=_uuid.uuid4(),
        source_id=_uuid.uuid4(),
        source_title="Pediatric Gastroesophageal Reflux Clinical Practice Guidelines",
        organization="NASPGHAN-ESPGHAN",
        publication_year=2018,
        url="https://example.org/naspghan",
        content="Regurgitation is common in infants and usually resolves by 12 months.",
        chunk_index=0,
        distance=0.07,
    )

    async def _retrieve(session, **kwargs):
        return [match]

    async def _generate(system_prompt, user_message, **kwargs):
        # The prompt must carry BOTH namespaces: the demo baby's record and
        # the retrieved evidence.
        assert "Clinical evidence" in user_message
        assert "Lucía" in user_message
        return "La regurgitación es habitual [ev_1]."

    with patch("adelia.routers.demo.embed_texts", return_value=[[0.0] * 1024]), patch(
        "adelia.routers.demo.retrieve_evidence", _retrieve
    ), patch("adelia.routers.demo.generate_answer", _generate):
        resp = await client.post(
            "/demo/ask",
            json={"question": "¿Es normal que regurgite tras cada toma?", "locale": "es"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "answer"
    citation = body["evidence_citations"][0]
    assert citation["organization"] == "NASPGHAN-ESPGHAN"
    assert citation["url"] == "https://example.org/naspghan"
    assert body["disclaimer"]


@pg_only
async def test_nothing_in_the_corpus_means_a_refusal_not_an_invention(client):
    async def _retrieve(session, **kwargs):
        return []

    with patch("adelia.routers.demo.embed_texts", return_value=[[0.0] * 1024]), patch(
        "adelia.routers.demo.retrieve_evidence", _retrieve
    ), patch("adelia.routers.demo.generate_answer") as generate:
        resp = await client.post(
            "/demo/ask",
            json={"question": "¿Qué opinas de la fibrilación auricular?", "locale": "es"},
        )

    assert resp.json()["kind"] == "no_evidence"
    generate.assert_not_called()


@pg_only
async def test_the_demo_writes_nothing_but_its_own_counter(client):
    """No user, no document, no chunk, no chat session. The only row the demo
    can create is an integer in funnel_counters."""
    async def _retrieve(session, **kwargs):
        return []

    async def _counts() -> tuple[int, int, int]:
        async with AsyncSessionLocal() as session:
            return (
                await session.scalar(sa.select(sa.func.count()).select_from(User)),
                await session.scalar(sa.select(sa.func.count()).select_from(Document)),
                await session.scalar(sa.select(sa.func.count()).select_from(Chunk)),
            )

    before = await _counts()
    with patch("adelia.routers.demo.embed_texts", return_value=[[0.0] * 1024]), patch(
        "adelia.routers.demo.retrieve_evidence", _retrieve
    ):
        await client.post("/demo/ask", json={"question": "¿Y la lactancia?"})

    assert await _counts() == before


@pg_only
async def test_the_daily_budget_closes_the_tap(client, monkeypatch):
    """A public endpoint that calls an LLM is a way to spend someone else's
    money. The ceiling lives in Postgres so a restart does not reset it."""
    monkeypatch.setattr(settings, "demo_daily_budget", 1)

    async def _retrieve(session, **kwargs):
        return []

    async with AsyncSessionLocal() as session:
        await session.execute(
            sa.delete(FunnelCounter).where(FunnelCounter.event == "demo_ask")
        )
        await session.commit()

    with patch("adelia.routers.demo.embed_texts", return_value=[[0.0] * 1024]), patch(
        "adelia.routers.demo.retrieve_evidence", _retrieve
    ):
        first = await client.post("/demo/ask", json={"question": "¿Y la lactancia?"})
        second = await client.post("/demo/ask", json={"question": "¿Y el sueño?"})

    assert first.status_code == 200, first.text
    assert second.status_code == 429, second.text

    async with AsyncSessionLocal() as session:
        await session.execute(
            sa.delete(FunnelCounter).where(FunnelCounter.event == "demo_ask")
        )
        await session.commit()


async def test_a_very_long_question_is_refused_before_the_embedding(client):
    with patch("adelia.routers.demo.embed_texts") as embed:
        resp = await client.post(
            "/demo/ask", json={"question": "a" * (settings.demo_max_question_chars + 1)}
        )

    assert resp.status_code == 422
    embed.assert_not_called()


@pg_only
async def test_the_demo_passes_the_relative_margin_from_the_setting(client):
    """The public demo is where the repeated and off-topic cards were measured
    (2026-10-14); its retrieval call has to carry the margin."""
    seen: dict = {}

    async def _retrieve(session, **kwargs):
        seen.update(kwargs)
        return []

    with patch("adelia.routers.demo.embed_texts", return_value=[[0.0] * 1024]), patch(
        "adelia.routers.demo.retrieve_evidence", _retrieve
    ):
        resp = await client.post(
            "/demo/ask",
            json={"question": "¿Cómo debe dormir mi bebé?", "locale": "es"},
        )

    assert resp.status_code == 200, resp.text
    assert seen["relative_margin"] == settings.evidence_relative_margin
    assert seen["max_distance"] == settings.evidence_max_distance
