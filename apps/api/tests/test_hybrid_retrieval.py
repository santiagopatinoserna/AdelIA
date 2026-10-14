"""Hybrid retrieval (vector + full-text, fused by RRF) against the real Postgres.

Three claims, each with a test that can fail:

1. Scoping is not weakened. The lexical query reads the WORDS of whoever's chunk
   contains them, so a lexical search that forgot `user_id` would hand one
   mother's lab results to another. Two users, two profiles, a soft-deleted
   document, and the pediatric filter on the evidence side are all seeded and
   asserted on what comes back, not on the shape of a SQL string.
2. The flag is off by default, and with it off the code issues the SAME SQL it
   issued before hybrid existed (compared to a verbatim copy of the old
   statement) and never touches the lexical index.
3. With it on, the full-text signal reorders what survived the calibrated
   cut-offs and cannot admit anything that did not, so the code-side refusal
   in chat_orchestrator keeps its only input.

Every vector here is synthetic and placed at a chosen cosine distance from the
query, so the tests need no embedding API key.
"""
from __future__ import annotations

import json
import math
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event, text

from adelia.config import Settings, settings
from adelia.services.lexical import LexicalPlan
from adelia.services.scope import Scope

from tests.pg_gate import PG_AVAILABLE

needs_pg = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

DIM = 1024
QUERY = [1.0] + [0.0] * (DIM - 1)


def vec_at(distance: float) -> list[float]:
    """A unit-ish vector whose cosine distance to QUERY is `distance`."""
    cos = 1.0 - distance
    return [cos, math.sqrt(1.0 - cos * cos)] + [0.0] * (DIM - 2)


@pytest.fixture
def hybrid_on(monkeypatch):
    monkeypatch.setattr(settings, "retrieval_hybrid_enabled", True)


@pytest.fixture
def hybrid_off(monkeypatch):
    monkeypatch.setattr(settings, "retrieval_hybrid_enabled", False)


@contextmanager
def recorded_sql():
    """Every statement the driver is handed, as (sql, repr(parameters))."""
    from adelia.db import engine

    log: list[tuple[str, str]] = []

    def _before(conn, cursor, statement, parameters, context, executemany):
        log.append((statement, repr(parameters)))

    event.listen(engine.sync_engine, "before_cursor_execute", _before)
    try:
        yield log
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _before)


def _touching(log, needle: str) -> list[tuple[str, str]]:
    return [entry for entry in log if needle in entry[0]]


# ---------------------------------------------------------------------------
# The flag
# ---------------------------------------------------------------------------


def test_the_flag_is_off_by_default():
    assert Settings.model_fields["retrieval_hybrid_enabled"].default is False


# ---------------------------------------------------------------------------
# Patient chunks (services/retrieval.py)
# ---------------------------------------------------------------------------


async def _make_profile(user_id: UUID, name: str) -> UUID:
    from adelia.db import AsyncSessionLocal
    from adelia.models import Profile

    async with AsyncSessionLocal() as session:
        profile = Profile(user_id=user_id, display_name=name, relationship="child")
        session.add(profile)
        await session.commit()
        return profile.id


async def _seed_chunk(
    *,
    user_id: UUID,
    content: str,
    distance: float,
    profile_id: UUID | None = None,
    deleted: bool = False,
) -> UUID:
    """One document with one chunk at `distance` from QUERY. Returns the chunk id.

    The document is stamped processed: it has chunks, so by definition its
    pipeline finished. Left at `processed_at IS NULL` it would look like
    something a dead worker abandoned, and the boot reconciliation
    (routers/documents.requeue_stuck_documents, tested in
    test_document_reconciliation.py against this same shared database) would
    pick it up and requeue it.
    """
    from adelia.db import AsyncSessionLocal
    from adelia.models import Chunk, Document

    async with AsyncSessionLocal() as session:
        doc = Document(
            id=uuid4(), user_id=user_id, profile_id=profile_id, source="web",
            mime_type="application/pdf", s3_key=f"users/{user_id}/{uuid4()}.pdf",
            raw_text=content, processed_at=datetime.now(timezone.utc),
            deleted_at=datetime.now(timezone.utc) if deleted else None,
        )
        session.add(doc)
        await session.flush()
        chunk = Chunk(
            document_id=doc.id, user_id=user_id, profile_id=profile_id,
            content=content, embedding=vec_at(distance), chunk_index=0,
            chunk_metadata={
                "parent_index": 0, "start_char": 0, "end_char": len(content),
                "entity_ids": [],
            },
        )
        session.add(chunk)
        await session.commit()
        return chunk.id


def _plan(tsquery: str, language: str = "es") -> LexicalPlan:
    config = {"es": "spanish", "en": "english", "fr": "french"}[language]
    return LexicalPlan(language=language, ts_config=config, tsquery=tsquery)


async def _lexical_chunks(scope: Scope, plan: LexicalPlan, pool: int = 50) -> list[str]:
    from adelia.db import AsyncSessionLocal
    from adelia.services.retrieval import lexical_chunk_ranking

    async with AsyncSessionLocal() as session:
        return await lexical_chunk_ranking(session, scope=scope, plan=plan, pool=pool)


@needs_pg
async def test_lexical_ranking_never_crosses_users():
    from tests.db_helpers import make_user

    mother_a, mother_b = await make_user(), await make_user()
    a = await _seed_chunk(user_id=mother_a, content="Ferritina baja: 8 ng/mL.", distance=0.1)
    b = await _seed_chunk(user_id=mother_b, content="Ferritina baja: 9 ng/mL.", distance=0.1)
    plan = _plan("'ferritina'")

    for_a = await _lexical_chunks(Scope(user_id=mother_a), plan)
    for_b = await _lexical_chunks(Scope(user_id=mother_b), plan)

    # Control first: each mother's own chunk IS found, so the assertions below
    # cannot pass merely because the query matched nothing.
    assert str(a) in for_a and str(b) in for_b
    assert str(b) not in for_a, "mother B's chunk leaked into mother A's lexical ranking"
    assert str(a) not in for_b, "mother A's chunk leaked into mother B's lexical ranking"
    assert for_a == [str(a)] and for_b == [str(b)]


@needs_pg
async def test_lexical_ranking_never_crosses_profiles():
    from tests.db_helpers import make_user

    mother = await make_user()
    adel = await _make_profile(mother, "Adel")
    nora = await _make_profile(mother, "Nora")
    text_ = "Hemoglobina 10,2 g/dL en el control."
    chunk_adel = await _seed_chunk(user_id=mother, content=text_, distance=0.1, profile_id=adel)
    chunk_nora = await _seed_chunk(user_id=mother, content=text_, distance=0.1, profile_id=nora)
    chunk_legacy = await _seed_chunk(user_id=mother, content=text_, distance=0.1, profile_id=None)
    plan = _plan("'hemoglobina'")

    scoped_to_adel = await _lexical_chunks(Scope(user_id=mother, profile_id=adel), plan)
    assert str(chunk_nora) not in scoped_to_adel, "Nora's chunk leaked into Adel's ranking"
    assert str(chunk_adel) in scoped_to_adel
    # Rows written before profiles existed stay visible, as in the vector path.
    assert str(chunk_legacy) in scoped_to_adel

    scoped_to_nora = await _lexical_chunks(Scope(user_id=mother, profile_id=nora), plan)
    assert str(chunk_adel) not in scoped_to_nora
    assert {str(chunk_nora), str(chunk_legacy)} <= set(scoped_to_nora)

    whole_account = await _lexical_chunks(Scope(user_id=mother), plan)
    assert {str(chunk_adel), str(chunk_nora), str(chunk_legacy)} <= set(whole_account)


@needs_pg
async def test_lexical_ranking_skips_soft_deleted_documents():
    from tests.db_helpers import make_user

    mother = await make_user()
    live = await _seed_chunk(user_id=mother, content="Fiebre de 38 grados.", distance=0.1)
    erased = await _seed_chunk(
        user_id=mother, content="Fiebre de 39 grados.", distance=0.1, deleted=True
    )
    ranking = await _lexical_chunks(Scope(user_id=mother), _plan("'fiebre'"))
    assert str(live) in ranking
    assert str(erased) not in ranking


@needs_pg
async def test_lexical_ranking_stems_in_the_questions_language():
    from tests.db_helpers import make_user

    mother = await make_user()
    es_chunk = await _seed_chunk(
        user_id=mother, content="Las ferritinas bajas requieren seguimiento.", distance=0.1
    )
    en_chunk = await _seed_chunk(
        user_id=mother, content="Low ferritin levels need follow up.", distance=0.1
    )
    scope = Scope(user_id=mother)

    # Singular "baja" and "ferritina" find the plural Spanish text, which only
    # holds if both sides went through the Spanish stemmer.
    spanish = await _lexical_chunks(scope, _plan("'ferritina' | 'baja'", "es"))
    assert str(es_chunk) in spanish
    # The text is indexed under all three languages, so an English question
    # finds an English document, and "level" finds "levels".
    english = await _lexical_chunks(scope, _plan("'level' | 'need'", "en"))
    assert str(en_chunk) in english


@needs_pg
async def test_hybrid_promotes_a_chunk_both_signals_agree_on(hybrid_on):
    from adelia.services.retrieval import retrieve_relevant_chunks
    from tests.db_helpers import make_user

    mother = await make_user()
    closest = await _seed_chunk(
        user_id=mother, content="Nota general del control de los seis meses.", distance=0.05
    )
    agrees = await _seed_chunk(
        user_id=mother, content="Ferritina baja, se indica hierro.", distance=0.10
    )
    await _seed_chunk(user_id=mother, content="Calendario de vacunas.", distance=0.20)
    kwargs = dict(
        scope=Scope(user_id=mother), query_embedding=QUERY, top_k=1, max_distance=0.5
    )

    vector_only = await retrieve_relevant_chunks(**kwargs)
    hybrid = await retrieve_relevant_chunks(**kwargs, query_text="ferritina", locale="es")

    assert [r.chunk_id for r in vector_only] == [closest]
    assert [r.chunk_id for r in hybrid] == [agrees]
    # The distance a caller sees is still the cosine distance, not a fused score.
    assert hybrid[0].embedding_distance == pytest.approx(0.10, abs=1e-4)


@needs_pg
async def test_hybrid_returns_at_most_top_k_from_a_larger_pool(hybrid_on):
    from adelia.services.retrieval import retrieve_relevant_chunks
    from tests.db_helpers import make_user

    mother = await make_user()
    for i in range(6):
        await _seed_chunk(
            user_id=mother, content=f"Control {i}: ferritina normal.", distance=0.05 + i * 0.01
        )
    results = await retrieve_relevant_chunks(
        scope=Scope(user_id=mother), query_embedding=QUERY, top_k=3, max_distance=0.5,
        query_text="ferritina", locale="es",
    )
    assert len(results) == 3


@needs_pg
async def test_hybrid_cannot_admit_a_chunk_the_cut_off_rejected(hybrid_on):
    """A perfect keyword match that is too far in vector space stays out. The
    cut-offs are the only admission control; the lexical signal reorders."""
    from adelia.services.retrieval import retrieve_relevant_chunks
    from tests.db_helpers import make_user

    mother = await make_user()
    near = await _seed_chunk(user_id=mother, content="Control sin novedad.", distance=0.05)
    far = await _seed_chunk(
        user_id=mother, content="Ferritina ferritina ferritina baja.", distance=0.60
    )
    results = await retrieve_relevant_chunks(
        scope=Scope(user_id=mother), query_embedding=QUERY, top_k=5, max_distance=0.20,
        query_text="ferritina", locale="es",
    )
    assert [r.chunk_id for r in results] == [near]
    assert far not in {r.chunk_id for r in results}


@needs_pg
async def test_hybrid_returns_nothing_when_nothing_passes_the_cut_off(hybrid_on):
    """The refusal path depends on this: lexical matches alone must not make an
    empty retrieval non-empty."""
    from adelia.services.retrieval import retrieve_relevant_chunks
    from tests.db_helpers import make_user

    mother = await make_user()
    await _seed_chunk(user_id=mother, content="Ferritina baja.", distance=0.60)
    results = await retrieve_relevant_chunks(
        scope=Scope(user_id=mother), query_embedding=QUERY, top_k=5, max_distance=0.20,
        query_text="ferritina", locale="es",
    )
    assert results == []


@needs_pg
async def test_hybrid_keeps_users_and_profiles_apart(hybrid_on):
    """The same property as the lexical-only tests, through the whole path: the
    other user's perfect match (distance 0.0, exact keyword) must not appear."""
    from adelia.services.retrieval import retrieve_relevant_chunks
    from tests.db_helpers import make_user

    mother, stranger = await make_user(), await make_user()
    adel = await _make_profile(mother, "Adel")
    nora = await _make_profile(mother, "Nora")
    own = await _seed_chunk(
        user_id=mother, content="Ferritina de Adel: 12.", distance=0.10, profile_id=adel
    )
    siblings = await _seed_chunk(
        user_id=mother, content="Ferritina de Nora: 30.", distance=0.0, profile_id=nora
    )
    strangers = await _seed_chunk(
        user_id=stranger, content="Ferritina de otra familia: 5.", distance=0.0
    )

    results = await retrieve_relevant_chunks(
        scope=Scope(user_id=mother, profile_id=adel), query_embedding=QUERY, top_k=8,
        max_distance=0.5, query_text="ferritina", locale="es",
    )
    returned = {r.chunk_id for r in results}
    assert own in returned
    assert siblings not in returned, "the other child's chunk reached the answer"
    assert strangers not in returned, "another user's chunk reached the answer"
    assert all(r.user_id == mother for r in results)


@needs_pg
async def test_a_failing_lexical_query_falls_back_to_the_vector_order(hybrid_on, monkeypatch):
    """The cross-check is optional. A broken tsquery must not cost the answer its
    retrieval, nor poison the transaction the parent-window queries still use."""
    from adelia.services import retrieval
    from adelia.services.retrieval import retrieve_relevant_chunks
    from tests.db_helpers import make_user

    mother = await make_user()
    first = await _seed_chunk(user_id=mother, content="Peso 7,2 kg.", distance=0.05)
    second = await _seed_chunk(user_id=mother, content="Talla 66 cm.", distance=0.10)
    monkeypatch.setattr(retrieval, "plan_lexical", lambda q, loc: _plan("'unterminated"))

    results = await retrieve_relevant_chunks(
        scope=Scope(user_id=mother), query_embedding=QUERY, top_k=5, max_distance=0.5,
        query_text="peso", locale="es",
    )
    assert [r.chunk_id for r in results] == [first, second]
    # The parent window is built by a query AFTER the failed lexical one.
    assert all(r.parent_content for r in results)


class _Reverse:
    def __init__(self):
        self.calls: list[tuple[str, int]] = []

    async def rerank(self, query, candidates):
        self.calls.append((query, len(candidates)))
        return list(reversed(candidates))


@needs_pg
async def test_a_reranker_plugs_into_the_hybrid_path(hybrid_on):
    from adelia.services.retrieval import retrieve_relevant_chunks
    from tests.db_helpers import make_user

    mother = await make_user()
    for i, distance in enumerate((0.05, 0.10, 0.15)):
        await _seed_chunk(user_id=mother, content=f"Peso {i}.", distance=distance)
    kwargs = dict(
        scope=Scope(user_id=mother), query_embedding=QUERY, top_k=3, max_distance=0.5,
        query_text="peso", locale="es",
    )
    default = await retrieve_relevant_chunks(**kwargs)
    reranker = _Reverse()
    reranked = await retrieve_relevant_chunks(**kwargs, reranker=reranker)

    assert [r.chunk_id for r in reranked] == [r.chunk_id for r in reversed(default)]
    assert reranker.calls == [("peso", 3)]


@needs_pg
async def test_flag_off_runs_the_old_statement_and_no_lexical_query(hybrid_off):
    """Byte-identical with the flag off: same SQL, same parameters, same rows
    as a verbatim copy of the pre-hybrid query, and the full-text index is never
    asked, even though `query_text` and `locale` were supplied."""
    from adelia.db import AsyncSessionLocal
    from adelia.models import Chunk, Document
    from adelia.services.retrieval import retrieve_relevant_chunks
    from tests.db_helpers import make_user

    mother = await make_user()
    await _seed_chunk(user_id=mother, content="Nota general.", distance=0.05)
    await _seed_chunk(user_id=mother, content="Ferritina baja.", distance=0.10)
    scope, cutoff, top_k = Scope(user_id=mother), 0.5, 1

    # The query as it was before hybrid retrieval existed.
    distance_expr = Chunk.embedding.cosine_distance(QUERY)
    legacy = (
        sa.select(
            Chunk.id.label("chunk_id"),
            Chunk.document_id.label("document_id"),
            Chunk.user_id.label("user_id"),
            Chunk.content,
            Chunk.chunk_metadata.label("metadata"),
            distance_expr.label("distance"),
            Document.deleted_at.label("doc_deleted_at"),
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(*scope.where(Chunk), Document.deleted_at.is_(None), distance_expr < cutoff)
        .order_by(distance_expr.asc())
        .limit(top_k)
    )
    with recorded_sql() as old_log:
        async with AsyncSessionLocal() as session:
            old_rows = [row.chunk_id for row in (await session.execute(legacy)).all()]

    with recorded_sql() as new_log:
        new = await retrieve_relevant_chunks(
            scope=scope, query_embedding=QUERY, top_k=top_k, max_distance=cutoff,
            query_text="ferritina", locale="es",
        )

    old_select = _touching(old_log, "FROM chunks JOIN documents")
    new_select = _touching(new_log, "FROM chunks JOIN documents")
    assert len(old_select) == 1 and len(new_select) == 1
    assert new_select == old_select
    assert [r.chunk_id for r in new] == old_rows
    assert not _touching(new_log, "tsv") and not _touching(new_log, "to_tsquery")


@needs_pg
async def test_without_query_text_hybrid_is_the_vector_path(hybrid_on):
    """Callers that retrieve from an embedding alone (briefings, the demo) pass no
    text: with the flag on they still get exactly the vector query."""
    from adelia.services.retrieval import retrieve_relevant_chunks
    from tests.db_helpers import make_user

    mother = await make_user()
    await _seed_chunk(user_id=mother, content="Nota general.", distance=0.05)
    await _seed_chunk(user_id=mother, content="Ferritina baja.", distance=0.10)

    with recorded_sql() as log:
        results = await retrieve_relevant_chunks(
            scope=Scope(user_id=mother), query_embedding=QUERY, top_k=1, max_distance=0.5,
        )
    assert len(results) == 1
    assert not _touching(log, "to_tsquery")


@needs_pg
async def test_an_unsupported_locale_means_no_lexical_query(hybrid_on):
    from adelia.services.retrieval import retrieve_relevant_chunks
    from tests.db_helpers import make_user

    mother = await make_user()
    await _seed_chunk(user_id=mother, content="Ferritina baja.", distance=0.10)
    with recorded_sql() as log:
        await retrieve_relevant_chunks(
            scope=Scope(user_id=mother), query_embedding=QUERY, top_k=1, max_distance=0.5,
            query_text="ferritina", locale="pt",
        )
    assert not _touching(log, "to_tsquery")


# ---------------------------------------------------------------------------
# Clinical evidence (enrichment/evidence_retrieval.py)
# ---------------------------------------------------------------------------

TEST_TITLE_PREFIX = "HYBRID-TEST-"
# A word no real source contains. The lexical query ranks the WHOLE evidence
# table and keeps a pool of the best matches, so a query about "reflujo" would
# compete with the real corpus's own reflux chunks for those slots and the test
# would depend on how big the corpus is. Queries built on this token see only
# the rows seeded here.
MARK = "hybridprobe"


@pytest.fixture
async def corpus():
    """A small seeded evidence corpus, removed again afterwards.

    evidence_chunks is shared with the calibration tests, which pick probes out
    of whatever rows are present, so nothing seeded here may outlive the test.
    Leftovers from a run that crashed before teardown are swept first.
    """
    from adelia.db import AsyncSessionLocal
    from adelia.models import EvidenceChunk, EvidenceSource

    async def _sweep():
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM evidence_sources WHERE title LIKE :p"),
                {"p": f"{TEST_TITLE_PREFIX}%"},
            )
            await session.commit()

    await _sweep()
    spec = {
        "es_reflujo": ("es", ["pediatrics"], 0.05,
                       f"El reflujo {MARK} gastroesofágico del lactante mejora con espesamiento."),
        "es_sueno": ("es", ["pediatrics"], 0.10,
                     "Pautas de sueño seguro para el lactante durante el primer año."),
        "es_adult": ("es", ["cardiology"], 0.02,
                     f"El reflujo {MARK} de la anticoagulación en el adulto mayor."),
        "en_ped": ("en", ["pediatrics"], 0.03,
                   f"Gastroesophageal reflux {MARK} in infants improves with thickened feeds."),
        # Spanish text stored under language 'en': proves the configuration is
        # taken from the ROW, not guessed from the text or from the question.
        "en_bajas": ("en", ["pediatrics"], 0.30, "Las ferritinas bajas requieren seguimiento."),
        "es_bajas": ("es", ["pediatrics"], 0.31, "Las ferritinas bajas requieren seguimiento."),
    }
    ids: dict[str, UUID] = {}
    async with AsyncSessionLocal() as session:
        for key, (language, specialties, distance, content) in spec.items():
            source = EvidenceSource(
                source_type="guideline", title=f"{TEST_TITLE_PREFIX}{key}-{uuid4().hex[:6]}",
                organization="TEST", publication_year=2026, specialties=specialties,
                language=language,
            )
            session.add(source)
            await session.flush()
            chunk = EvidenceChunk(
                source_id=source.id, content=content, chunk_index=0,
                chunk_metadata={"section": key}, embedding=vec_at(distance),
                language=language,
            )
            session.add(chunk)
            await session.flush()
            ids[key] = chunk.id
        await session.commit()
    try:
        yield ids
    finally:
        await _sweep()


async def _lexical_evidence(plan, specialties, pool: int = 500) -> list[str]:
    from adelia.db import AsyncSessionLocal
    from adelia.enrichment.evidence_retrieval import lexical_evidence_ranking

    async with AsyncSessionLocal() as session:
        return await lexical_evidence_ranking(
            session, plan=plan, specialties=specialties, pool=pool
        )


async def _retrieve(**kwargs):
    from adelia.db import AsyncSessionLocal
    from adelia.enrichment.evidence_retrieval import retrieve_evidence

    async with AsyncSessionLocal() as session:
        return await retrieve_evidence(session, query_embedding=QUERY, **kwargs)


@needs_pg
async def test_the_tsvector_is_built_from_each_rows_own_language(corpus):
    from adelia.db import AsyncSessionLocal

    both = [str(corpus["es_bajas"]), str(corpus["en_bajas"])]
    async with AsyncSessionLocal() as session:

        async def _matching(config: str, word: str) -> set[str]:
            rows = await session.execute(
                text(
                    "SELECT id::text FROM evidence_chunks "
                    "WHERE id = ANY(CAST(:ids AS uuid[])) "
                    "AND tsv @@ to_tsquery(CAST(:cfg AS regconfig), :w)"
                ),
                {"ids": both, "cfg": config, "w": word},
            )
            return {r[0] for r in rows}

        # Same sentence in both rows. The Spanish stemmer turns "bajas" into
        # "baj", the English one into "baja": only the row indexed as Spanish
        # answers the Spanish question, and only the row indexed as English
        # answers the English one.
        assert await _matching("spanish", "baja") == {str(corpus["es_bajas"])}
        assert await _matching("english", "bajas") == {str(corpus["en_bajas"])}


@needs_pg
async def test_every_evidence_chunk_carries_its_sources_language():
    """Drift guard for the denormalised column. A writer that skips `language`
    gets the column default ('en') and Spanish text silently indexed as English;
    the lexical half then never finds it."""
    from adelia.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        wrong = (
            await session.execute(
                text(
                    "SELECT count(*) FROM evidence_chunks ec "
                    "JOIN evidence_sources es ON es.id = ec.source_id "
                    "WHERE ec.language IS DISTINCT FROM es.language"
                )
            )
        ).scalar_one()
    assert wrong == 0


@needs_pg
async def test_the_loader_writes_the_sources_language_on_its_chunks(tmp_path, monkeypatch):
    from adelia.db import AsyncSessionLocal
    from adelia.enrichment import evidence_loader

    title = f"{TEST_TITLE_PREFIX}loader-{uuid4().hex[:6]}"
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"sources": [{
        "source_type": "guideline", "title": title, "organization": "TEST",
        "publication_year": 2026, "specialties": ["pediatrics"], "language": "fr",
        "chunks": ["La fièvre chez le nourrisson.", "Les vaccins du nourrisson."],
    }]}))

    async def _embed(texts):
        return [vec_at(0.5) for _ in texts]

    monkeypatch.setattr(evidence_loader, "embed_with_retry", _embed)
    monkeypatch.setattr(evidence_loader, "SOURCE_PACING_S", 0)
    try:
        assert await evidence_loader.load_evidence_file(seed) == (1, 2)
        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT ec.language, ec.tsv @@ to_tsquery('french', 'nourrisson') AS hit "
                        "FROM evidence_chunks ec JOIN evidence_sources es ON es.id = ec.source_id "
                        "WHERE es.title = :t"
                    ),
                    {"t": title},
                )
            ).all()
        assert [(r.language, r.hit) for r in rows] == [("fr", True), ("fr", True)]
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM evidence_sources WHERE title = :t"), {"t": title}
            )
            await session.commit()


@needs_pg
async def test_lexical_evidence_applies_the_pediatric_filter(corpus):
    """Evidence has no user to scope by; its scoping is the specialty filter,
    which keeps adult sources out of an answer about a baby. The lexical query
    carries it identically."""
    plan = _plan(f"'{MARK}'")

    pediatric = await _lexical_evidence(plan, ["pediatrics"])
    assert str(corpus["es_reflujo"]) in pediatric
    assert str(corpus["es_adult"]) not in pediatric, "an adult source reached the pediatric path"

    # Control: without the filter the adult chunk matches, so the assertion
    # above is the filter's doing and not an accident of the corpus.
    unfiltered = await _lexical_evidence(plan, None)
    assert str(corpus["es_adult"]) in unfiltered


@needs_pg
async def test_lexical_evidence_only_matches_rows_in_the_questions_language(corpus):
    # The marker is in the Spanish row AND the English row; only the row whose
    # language matches the question's may come back.
    spanish = await _lexical_evidence(_plan(f"'{MARK}'", "es"), ["pediatrics"])
    assert str(corpus["es_reflujo"]) in spanish
    assert str(corpus["en_ped"]) not in spanish

    english = await _lexical_evidence(_plan(f"'{MARK}'", "en"), ["pediatrics"])
    assert str(corpus["en_ped"]) in english
    assert str(corpus["es_reflujo"]) not in english


@needs_pg
async def test_hybrid_evidence_promotes_the_chunk_both_signals_agree_on(corpus, hybrid_on):
    kwargs = dict(specialties=["pediatrics"], top_k=3, max_distance=0.5)
    vector_only = await _retrieve(**kwargs)
    hybrid = await _retrieve(**kwargs, query_text=MARK, locale="es")

    seeded = {corpus["en_ped"], corpus["es_reflujo"], corpus["es_sueno"]}
    assert [m.chunk_id for m in vector_only if m.chunk_id in seeded] == [
        corpus["en_ped"], corpus["es_reflujo"], corpus["es_sueno"],
    ]
    # The Spanish chunk that the full-text query also found moves to the top;
    # the English one, closest in vector space but invisible to a Spanish
    # lexical query, is pushed down.
    assert [m.chunk_id for m in hybrid if m.chunk_id in seeded][0] == corpus["es_reflujo"]
    assert hybrid[0].distance == pytest.approx(0.05, abs=1e-4)


@needs_pg
async def test_hybrid_evidence_never_returns_an_adult_source(corpus, hybrid_on):
    results = await _retrieve(
        specialties=["pediatrics"], top_k=10, max_distance=0.5,
        query_text=f"{MARK} anticoagulación adulto", locale="es",
    )
    assert corpus["es_adult"] not in {m.chunk_id for m in results}


@needs_pg
async def test_hybrid_evidence_cannot_admit_what_the_cut_off_rejected(corpus, hybrid_on):
    # es_reflujo (0.05) matches the question perfectly but sits outside 0.04.
    # Only en_ped (0.03) is a vector survivor, so only it may come back.
    results = await _retrieve(
        specialties=["pediatrics"], top_k=10, max_distance=0.04,
        query_text=MARK, locale="es",
    )
    returned = {m.chunk_id for m in results}
    assert corpus["en_ped"] in returned
    assert corpus["es_reflujo"] not in returned


@needs_pg
async def test_hybrid_evidence_with_nothing_inside_the_cut_off_is_empty(corpus, hybrid_on):
    results = await _retrieve(
        specialties=["pediatrics"], top_k=10, max_distance=0.001,
        query_text=MARK, locale="es",
    )
    assert results == []


@needs_pg
async def test_a_failing_lexical_evidence_query_falls_back_to_the_vector_order(
    corpus, hybrid_on, monkeypatch
):
    from adelia.enrichment import evidence_retrieval

    monkeypatch.setattr(evidence_retrieval, "plan_lexical", lambda q, loc: _plan("'unterminated"))
    results = await _retrieve(
        specialties=["pediatrics"], top_k=3, max_distance=0.5,
        query_text=MARK, locale="es",
    )
    seeded = {corpus["en_ped"], corpus["es_reflujo"], corpus["es_sueno"]}
    assert [m.chunk_id for m in results if m.chunk_id in seeded] == [
        corpus["en_ped"], corpus["es_reflujo"], corpus["es_sueno"],
    ]


@needs_pg
async def test_a_reranker_plugs_into_the_hybrid_evidence_path(corpus, hybrid_on):
    base = dict(specialties=["pediatrics"], max_distance=0.5, query_text=MARK, locale="es")
    # Everything that survives the cut-off, in fused order (top_k above the pool).
    full = await _retrieve(**base, top_k=50)
    reranker = _Reverse()
    reranked = await _retrieve(**base, top_k=3, reranker=reranker)

    # The reranker saw the whole pool (not just top_k) and the question text,
    # and what it put first is what comes back, trimmed to top_k afterwards.
    assert reranker.calls == [(MARK, len(full))]
    assert [m.chunk_id for m in reranked] == [m.chunk_id for m in reversed(full)][:3]


# The statement evidence_retrieval ran before hybrid existed, verbatim (the
# concatenation mirrors how the module appended the optional clauses).
LEGACY_EVIDENCE_SQL = (
    "\n        SELECT\n"
    "            ec.id AS chunk_id,\n"
    "            ec.source_id,\n"
    "            es.title AS source_title,\n"
    "            es.organization,\n"
    "            es.publication_year,\n"
    "            es.url,\n"
    "            ec.content,\n"
    "            ec.chunk_index,\n"
    "            ec.embedding <=> :emb AS distance\n"
    "        FROM evidence_chunks ec\n"
    "        JOIN evidence_sources es ON es.id = ec.source_id\n"
    "        WHERE ec.embedding <=> :emb < :max_distance\n"
    "    "
    " AND es.specialties ?| :spec_list"
    " ORDER BY distance ASC LIMIT :k"
)


@needs_pg
async def test_flag_off_evidence_runs_the_old_statement_and_no_lexical_query(corpus, hybrid_off):
    from sqlalchemy import String, bindparam
    from sqlalchemy.dialects.postgresql import ARRAY

    from adelia.db import AsyncSessionLocal

    top_k, cutoff = 3, 0.5
    legacy_params = {
        "emb": str(QUERY), "max_distance": cutoff, "spec_list": ["pediatrics"], "k": top_k,
    }
    legacy = text(LEGACY_EVIDENCE_SQL).bindparams(bindparam("spec_list", type_=ARRAY(String)))
    with recorded_sql() as old_log:
        async with AsyncSessionLocal() as session:
            old_ids = [
                r["chunk_id"] for r in (await session.execute(legacy, legacy_params)).mappings()
            ]

    with recorded_sql() as new_log:
        new = await _retrieve(
            specialties=["pediatrics"], top_k=top_k, max_distance=cutoff,
            query_text=MARK, locale="es",
        )

    old_select = _touching(old_log, "FROM evidence_chunks ec")
    new_select = _touching(new_log, "FROM evidence_chunks ec")
    assert len(old_select) == 1 and len(new_select) == 1
    assert new_select == old_select
    assert [m.chunk_id for m in new] == old_ids
    assert not _touching(new_log, "tsv") and not _touching(new_log, "to_tsquery")


@needs_pg
async def test_hybrid_evidence_without_text_or_with_other_locale_is_the_vector_path(
    corpus, hybrid_on
):
    with recorded_sql() as log:
        no_text = await _retrieve(specialties=["pediatrics"], top_k=3, max_distance=0.5)
        other_locale = await _retrieve(
            specialties=["pediatrics"], top_k=3, max_distance=0.5,
            query_text=MARK, locale="pt",
        )
    assert not _touching(log, "to_tsquery")
    assert [m.chunk_id for m in no_text] == [m.chunk_id for m in other_locale]


# ---------------------------------------------------------------------------
# Wiring: the chat passes the question and its locale down
# ---------------------------------------------------------------------------


@patch("adelia.services.chat_orchestrator.retrieve_evidence")
@patch("adelia.services.chat_orchestrator.AsyncSessionLocal")
async def test_the_chat_evidence_helper_forwards_text_and_locale(_session, mock_retrieve):
    from adelia.services.chat_orchestrator import _retrieve_evidence_for_query

    mock_retrieve.return_value = []
    await _retrieve_evidence_for_query(
        [0.1] * DIM, query_text="¿cuánto hierro?", locale="es"
    )
    kwargs = mock_retrieve.call_args.kwargs
    assert kwargs["query_text"] == "¿cuánto hierro?"
    assert kwargs["locale"] == "es"
    # and the calibrated gate is still the one passed down
    assert kwargs["max_distance"] == settings.evidence_max_distance
    assert kwargs["specialties"] == ["pediatrics"]


@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query", return_value=[])
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator._stream_llm_tokens")
async def test_the_chat_hands_the_question_not_the_history_to_the_lexical_side(
    _stream, _temporal, mock_embed, mock_chunks, mock_evidence
):
    from adelia.services.chat_orchestrator import answer_question_streaming

    mock_embed.return_value = [[0.1] * DIM]
    history = [
        {"role": "user", "content": "Tema anterior larguísimo sobre vacunas"},
        {"role": "assistant", "content": "Respuesta anterior"},
    ]
    async for _ in answer_question_streaming(
        user_id=uuid4(), question="¿y la ferritina?", history=history, locale="es"
    ):
        pass

    # The embedding sees the conversation; the keyword search sees the question.
    assert "Tema anterior" in mock_embed.call_args.args[0][0]
    assert mock_chunks.call_args.kwargs["query_text"] == "¿y la ferritina?"
    assert mock_chunks.call_args.kwargs["locale"] == "es"
    assert mock_evidence.call_args.kwargs["query_text"] == "¿y la ferritina?"
    assert mock_evidence.call_args.kwargs["locale"] == "es"
