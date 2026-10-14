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

import math
import random
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text

from adelia.clinical.golden import GOLDEN_SET
from adelia.clinical.red_flags import normalize
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


# --- One citation per source, and no filler (public demo, 2026-10-14) -------
#
# The demo showed the same guideline in three of four cards, and a reflux
# guideline as the fourth "evidence" of a question about sudden infant death.
# Two halves, as with the calibration above. The first seeds sources whose
# fragments sit at chosen cosine distances from a fixed query, so it needs no
# key and runs wherever Postgres does. The second embeds the real questions and
# runs them against the real corpus, so it needs both.

DIM = 1024
SEEDED_QUERY = [1.0] + [0.0] * (DIM - 1)
SEEDED_PREFIX = "DEDUP-TEST-"


def _vec_at(distance: float) -> list[float]:
    """A vector whose cosine distance to SEEDED_QUERY is `distance`."""
    cos = 1.0 - distance
    return [cos, math.sqrt(1.0 - cos * cos)] + [0.0] * (DIM - 2)


async def _seed(spec: dict[str, tuple[str, list[float]]]) -> dict[str, dict]:
    """Seed pediatric sources. `spec` maps a key to (title, distances of its fragments).

    Returns, per key, the source id and the ids and texts of its fragments in
    the order given. evidence_chunks is shared with the calibration tests above,
    which take their probes from whatever rows exist, so every caller removes
    what it seeded (see `_sweep`).
    """
    from adelia.models import EvidenceChunk, EvidenceSource

    out: dict[str, dict] = {}
    async with AsyncSessionLocal() as session:
        for key, (title, distances) in spec.items():
            source = EvidenceSource(
                source_type="guideline", title=f"{SEEDED_PREFIX}{title}", organization="TEST",
                publication_year=2026, specialties=["pediatrics"], language="es",
            )
            session.add(source)
            await session.flush()
            chunks = []
            for i, distance in enumerate(distances):
                content = f"{key} fragment {i} at {distance}"
                chunk = EvidenceChunk(
                    source_id=source.id, content=content, chunk_index=i,
                    chunk_metadata={"section": key}, embedding=_vec_at(distance), language="es",
                )
                session.add(chunk)
                await session.flush()
                chunks.append((chunk.id, content))
            out[key] = {"source_id": source.id, "chunks": chunks}
        await session.commit()
    return out


async def _sweep() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM evidence_sources WHERE title LIKE :p"), {"p": f"{SEEDED_PREFIX}%"}
        )
        await session.commit()


@pytest.fixture
async def seeded():
    """Starts and ends with none of this file's seeded rows in the table."""
    await _sweep()
    try:
        yield _seed
    finally:
        await _sweep()


async def _retrieve_seeded(top_k: int = 4):
    from adelia.enrichment.evidence_retrieval import retrieve_evidence

    async with AsyncSessionLocal() as session:
        return await retrieve_evidence(
            session,
            query_embedding=SEEDED_QUERY,
            specialties=["pediatrics"],
            top_k=top_k,
            max_distance=settings.evidence_max_distance,
            relative_margin=settings.evidence_relative_margin,
        )


async def test_a_source_that_owns_the_top_rows_is_cited_once_and_the_slots_are_refilled(seeded):
    """Three of the four nearest rows are one guideline: the other slots go to
    the next distinct sources, and the guideline's own best fragment is the one
    shown."""
    rows = await seeded({
        "sleep": ("AAP", [0.05, 0.06, 0.07]),
        "b": ("B", [0.08]),
        "c": ("C", [0.09]),
        "d": ("D", [0.10]),
        "e": ("E", [0.11]),
    })
    got = await _retrieve_seeded(top_k=4)
    assert [m.source_id for m in got] == [rows[k]["source_id"] for k in ("sleep", "b", "c", "d")]
    assert len({m.source_id for m in got}) == len(got)
    best_id, best_text = rows["sleep"]["chunks"][0]
    assert (got[0].chunk_id, got[0].content) == (best_id, best_text)


async def test_one_good_source_is_one_citation_not_four(seeded):
    """The reflux-for-sleep shape. The other sources are inside the absolute
    cut-off (0.19), which is the only reason they used to be returned; they are
    0.10 and 0.12 behind the best fragment, so the relative margin drops them."""
    rows = await seeded({
        "sleep": ("AAP", [0.05, 0.06, 0.07]),
        "reflux": ("NICE", [0.15]),
        "feeding": ("AEP", [0.17]),
    })
    got = await _retrieve_seeded(top_k=4)
    assert [m.source_id for m in got] == [rows["sleep"]["source_id"]]
    assert all(m.distance < settings.evidence_max_distance for m in got)


async def test_the_margin_never_admits_what_the_cut_off_refused(seeded):
    """A fragment inside the margin but past 0.19 stays out: the margin is a
    second gate, not a replacement for the calibrated one."""
    rows = await seeded({"near": ("N", [0.185]), "past": ("P", [0.195])})
    got = await _retrieve_seeded(top_k=4)
    assert [m.source_id for m in got] == [rows["near"]["source_id"]]


async def test_two_sources_with_the_same_title_are_two_citations(seeded):
    rows = await seeded({"one": ("Misma guía", [0.05]), "two": ("Misma guía", [0.06])})
    got = await _retrieve_seeded(top_k=4)
    assert [m.source_id for m in got] == [rows["one"]["source_id"], rows["two"]["source_id"]]


@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator.embed_texts", new_callable=AsyncMock)
async def test_the_answer_cites_each_source_once_and_quotes_what_the_model_read(
    mock_embed, mock_temporal, mock_retrieve, seeded
):
    """Whole chain, real database: no source id repeats among the cards, and the
    text the model was handed is the text under each card."""
    await seeded({
        "sleep": ("AAP", [0.05, 0.06, 0.07]),
        "b": ("B", [0.08]),
        "c": ("C", [0.09]),
    })
    mock_embed.return_value = [SEEDED_QUERY]
    prompts: list[str] = []

    async def _fake_stream(system, user_msg, history=None):
        prompts.append(user_msg)
        yield "Respuesta [ev_1]."

    with patch("adelia.services.chat_orchestrator._stream_llm_tokens", _fake_stream):
        events = await _collect(
            answer_question_streaming(user_id=uuid4(), question="¿cómo debe dormir mi bebé?")
        )

    final = events[-1]
    assert final.type == "final"
    cards = final.evidence_citations
    assert len(cards) == 3
    assert len({c["source_id"] for c in cards}) == len(cards)
    for card in cards:
        assert card["snippet"] in prompts[0]


# --- The same questions, embedded for real, against the production corpus ----

needs_key = pytest.mark.skipif(
    not settings.mistral_api_key, reason="needs Mistral API key (embeds the question)"
)

#: The questions of the 2026-10-14 measurement, word for word.
DEMO_QUESTIONS = {
    "sleep": "¿Cómo debe dormir mi bebé para reducir el riesgo de muerte súbita?",
    "reflux": "Mi bebé regurgita después de cada toma, ¿hacia cuándo mejora?",
    "daycare": "¿Cuánto tarda un bebé en adaptarse a la guardería?",
    "peanut": "¿Puedo darle cacahuete a mi bebé de 8 meses?",
}

#: Same terms as golden question A13, so the set and this test cannot disagree
#: about what "talks about sleep" means.
SLEEP_TERMS = [
    normalize(t)
    for t in next(q for q in GOLDEN_SET if q.id == "A13").every_citation_mentions.split("|")
]


async def _demo_retrieval(question: str):
    """What POST /demo/ask retrieves for `question`: embedding, then the same call."""
    from adelia.enrichment.evidence_retrieval import retrieve_evidence
    from adelia.workers.embed import embed_texts

    if await _an_evidence_probe() is None:
        pytest.skip("no evidence corpus loaded in this database")
    async with AsyncSessionLocal() as session:
        chunks = (await session.execute(text("SELECT count(*) FROM evidence_chunks"))).scalar_one()
    if chunks < 250:
        pytest.skip(f"the corpus holds {chunks} fragments, these questions need the full 301")
    embedding = (await embed_texts([question]))[0]
    async with AsyncSessionLocal() as session:
        return await retrieve_evidence(
            session,
            query_embedding=embedding,
            specialties=["pediatrics"],
            top_k=4,
            max_distance=settings.evidence_max_distance,
            relative_margin=settings.evidence_relative_margin,
        )


@needs_key
@pytest.mark.parametrize("name", sorted(DEMO_QUESTIONS))
async def test_no_demo_question_cites_one_source_twice(name):
    matches = await _demo_retrieval(DEMO_QUESTIONS[name])
    assert len({m.source_id for m in matches}) == len(matches), (
        f"{name}: " + ", ".join(m.source_title for m in matches)
    )


@needs_key
async def test_the_safe_sleep_question_is_answered_only_with_fragments_that_talk_about_sleep():
    """Content, not the name of the source. Fragment 2 of NICE NG1 is the
    sleeping-position advice for a baby with reflux (always on the back, because
    of sudden infant death), so a reflux GUIDELINE can be a right card here; a
    reflux fragment about feeds is not."""
    matches = await _demo_retrieval(DEMO_QUESTIONS["sleep"])
    assert matches, "the corpus holds the AAP 2022 safe-sleep guideline: it must be found"
    off_topic = [
        f"{m.source_title}: {m.content[:80]!r}"
        for m in matches
        if not any(term in normalize(f"{m.source_title} {m.content}") for term in SLEEP_TERMS)
    ]
    assert off_topic == []
