"""The calibrated cut-off and the pediatric filter, against the real corpus.

The unit tests around the refusal stub retrieval out. These run the actual
pgvector SQL against whatever evidence corpus the database holds, so a change
to the threshold, to the SQL, or to the corpus itself shows up here. Only the
embedding call is stubbed: it is the one step that needs a paid API key, and
a stored vector or a random one is a perfectly good stand-in for it.

Skipped when the corpus is not loaded (an empty CI database), never silently
green: the skip reason says which half was missing. The guard that CI *can*
run without a corpus lives in tests/test_chat_orchestrator.py, next to the
cut-off assertion, on purpose.
"""
from __future__ import annotations

import random
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.services.answer_contract import no_evidence_reply
from adelia.services.chat_orchestrator import answer_question_streaming

from tests.pg_gate import PG_AVAILABLE


pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

PEDIATRIC = "es.specialties ?| array['pediatrics']"


async def _an_evidence_probe() -> tuple[str, list[float]] | None:
    """A stored pediatric chunk PLUS the source it came from.

    The source id is the point. Using a corpus vector as its own query makes
    its own chunk match at distance 0.0 whatever the cut-off is, so a test
    that only asserts `matches` is true cannot fail: it passed at
    EVIDENCE_MAX_DISTANCE=0.0001, a value that would refuse every real
    question. The guard has to be a fragment from a DIFFERENT source, which is
    the distance the calibration actually measured (p50 0.0663, worst
    cross-source 0.1110 on this corpus).

    Deterministic (ORDER BY id): the first pediatric chunk has 8 cross-source
    neighbours inside 0.20, verified on the dev corpus.
    """
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    "SELECT ec.source_id::text AS sid, ec.embedding::text AS emb "
                    "FROM evidence_chunks ec "
                    "JOIN evidence_sources es ON es.id = ec.source_id "
                    f"WHERE ec.embedding IS NOT NULL AND {PEDIATRIC} "
                    "ORDER BY ec.id LIMIT 1"
                )
            )
        ).first()
    if row is None:
        return None
    return row.sid, [float(x) for x in row.emb.strip("[]").split(",")]


async def _an_adult_probe() -> tuple[str, list[float]] | None:
    """A stored chunk of one of the ADULT sources the same table holds.

    evidence_seed.json ships 8 of them (atrial fibrillation, hypertension,
    cholesterol, breast and colorectal cancer screening, endometriosis, adult
    diabetes, SBAR). They are the population the calibration calls "off
    corpus", and until 2026-08-31 the answering path searched them too.
    """
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    "SELECT ec.source_id::text AS sid, ec.embedding::text AS emb "
                    "FROM evidence_chunks ec "
                    "JOIN evidence_sources es ON es.id = ec.source_id "
                    f"WHERE ec.embedding IS NOT NULL AND NOT ({PEDIATRIC}) "
                    "ORDER BY ec.id LIMIT 1"
                )
            )
        ).first()
    if row is None:
        return None
    return row.sid, [float(x) for x in row.emb.strip("[]").split(",")]


def _orthogonal_query() -> list[float]:
    """A deterministic random unit-ish vector: nothing in any corpus is near
    it, which is what "the parent asked about a mortgage" looks like to
    pgvector."""
    rng = random.Random(20260831)
    return [rng.gauss(0.0, 1.0) for _ in range(1024)]


async def _collect(gen):
    return [e async for e in gen]


async def test_unrelated_query_returns_zero_evidence_at_the_calibrated_cutoff():
    """Runs the real `embedding <=> :emb < :max_distance` SQL."""
    from adelia.enrichment.evidence_retrieval import retrieve_evidence

    if await _an_evidence_probe() is None:
        pytest.skip("no evidence corpus loaded in this database")

    async with AsyncSessionLocal() as session:
        matches = await retrieve_evidence(
            session,
            query_embedding=_orthogonal_query(),
            top_k=4,
            max_distance=settings.evidence_max_distance,
        )
    assert matches == []


async def test_corpus_query_still_finds_evidence_at_the_calibrated_cutoff():
    """The cut-off must not have been tightened into uselessness.

    The assertion is about a fragment from ANOTHER source, never the identity
    match: see _an_evidence_probe.
    """
    from adelia.enrichment.evidence_retrieval import retrieve_evidence

    probe = await _an_evidence_probe()
    if probe is None:
        pytest.skip("no evidence corpus loaded in this database")
    source_id, embedding = probe

    async with AsyncSessionLocal() as session:
        matches = await retrieve_evidence(
            session,
            query_embedding=embedding,
            specialties=["pediatrics"],
            top_k=10,
            max_distance=settings.evidence_max_distance,
        )

    others = [m for m in matches if str(m.source_id) != source_id]
    assert others, (
        "no fragment from another source survived the cut-off: it is too tight"
    )
    assert all(m.distance <= settings.evidence_max_distance for m in matches)


# --- The population the calibration measured is the one the code searches ---
#
# The calibration's headline ("with 0.20 none of the 14 off-corpus probes gets
# through") was measured against the pediatric fragments only, while
# retrieve_evidence searched all 258 chunks, those 14 adult sources included.
# Measured on dev before the fix: 12 of the 14 adult probes reached a fragment
# of ANOTHER source at 0.20, the nearest at 0.1324. An app about a baby could
# answer with anticoagulation-in-atrial-fibrillation or cancer-screening text
# labelled "Clinical evidence".


async def test_the_specialty_filter_binds_at_all():
    """`es.specialties ?| array[:spec_list]` built an array OF the parameter,
    so asyncpg raised DataError: expected str, got list. Every call passing
    `specialties` blew up, silently, because both call sites return [] on any
    exception. This test fails on a DataError, not on an assertion."""
    from adelia.enrichment.evidence_retrieval import retrieve_evidence

    probe = await _an_evidence_probe()
    if probe is None:
        pytest.skip("no evidence corpus loaded in this database")
    _, embedding = probe

    async with AsyncSessionLocal() as session:
        matches = await retrieve_evidence(
            session,
            query_embedding=embedding,
            specialties=["pediatrics"],
            top_k=4,
            max_distance=settings.evidence_max_distance,
        )
    assert matches, "the pediatric filter returned nothing for a pediatric probe"


async def test_an_adult_chunk_as_query_retrieves_no_adult_source():
    """The regression the orthogonal-vector test cannot catch.

    The query is a STORED adult vector, not a random one: its own chunk sits
    at distance 0.0, so any leak of the adult corpus shows up immediately.
    With specialties=["pediatrics"] nothing without the tag may come back.
    """
    from adelia.enrichment.evidence_retrieval import retrieve_evidence

    probe = await _an_adult_probe()
    if probe is None:
        pytest.skip("no adult sources loaded in this database")
    _, embedding = probe

    async with AsyncSessionLocal() as session:
        untagged = (
            await session.execute(
                text(
                    "SELECT id::text FROM evidence_sources "
                    "WHERE NOT (specialties ?| array['pediatrics'])"
                )
            )
        ).scalars().all()
        matches = await retrieve_evidence(
            session,
            query_embedding=embedding,
            specialties=["pediatrics"],
            top_k=8,
            max_distance=settings.evidence_max_distance,
        )

    leaked = [m for m in matches if str(m.source_id) in set(untagged)]
    assert leaked == [], (
        "an adult source came back as clinical evidence for a baby: "
        + ", ".join(m.source_title for m in leaked)
    )


@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator._stream_llm_tokens")
@patch("adelia.services.chat_orchestrator.embed_texts", new_callable=AsyncMock)
async def test_an_adult_question_is_refused_end_to_end(
    mock_embed, mock_stream, mock_temporal, mock_retrieve,
):
    """Whole chain, real database, adult vector as the question: the parent
    gets the refusal and the generative model is never called. Before the
    pediatric filter this same probe came back with four "Clinical evidence"
    fragments."""
    probe = await _an_adult_probe()
    if probe is None:
        pytest.skip("no adult sources loaded in this database")
    _, embedding = probe
    mock_embed.return_value = [embedding]

    events = await _collect(
        answer_question_streaming(
            user_id=uuid4(),
            question="¿qué anticoagulante se usa en fibrilación auricular no valvular?",
        )
    )

    mock_stream.assert_not_called()
    assert "".join(e.content for e in events if e.type == "token") == no_evidence_reply("es")


@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator._stream_llm_tokens")
@patch("adelia.services.chat_orchestrator.embed_texts", new_callable=AsyncMock)
async def test_end_to_end_refusal_against_the_real_corpus(
    mock_embed, mock_stream, mock_temporal, mock_retrieve,
):
    """Whole chain, real database: an off-corpus question, a user with no
    documents, and the generative model never reached."""
    if await _an_evidence_probe() is None:
        pytest.skip("no evidence corpus loaded in this database")
    mock_embed.return_value = [_orthogonal_query()]

    events = await _collect(
        answer_question_streaming(
            user_id=uuid4(), question="¿me conviene una hipoteca fija o variable?"
        )
    )

    mock_stream.assert_not_called()
    assert "".join(e.content for e in events if e.type == "token") == no_evidence_reply("es")
    assert [e.type for e in events][-1] == "final"
