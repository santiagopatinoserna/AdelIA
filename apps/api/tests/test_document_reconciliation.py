"""A document must never sit at "procesando" for ever (audit 4.4).

All heavy work is an in-process task. A deploy, an OOM or a power cut in the
middle kills it, and before this there was no retry anywhere: the audio stayed
in MinIO with no transcript, the row stayed `processed_at IS NULL`, and the
screen said "procesando" until the end of time over an appointment that cannot
be recorded twice.

Two guarantees are asserted here:
  * boot reconciliation picks up what a dead worker left behind, and the
    document ends processed;
  * even when the pipeline fails outright, the document ends "failed" — a
    state the UI can offer a retry from — and never "processing".
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from tests.pg_gate import PG_AVAILABLE

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")


async def _make_stuck_document(*, age: timedelta | None = None, with_debris: bool = True):
    """A document exactly as a killed pipeline leaves it: created a while ago,
    `processed_at IS NULL`, and (optionally) half-written entities/chunks from
    the attempt that died.

    The default age is one second past the cut-off, which makes this row the
    NEWEST eligible one: the dev database is shared with every other suite run
    and already holds hundreds of abandoned rows, and the reconciler is capped
    and ordered newest-first. Without this the assertion would depend on how
    much debris the box happens to hold.
    """
    from adelia.config import settings
    from adelia.db import AsyncSessionLocal
    from adelia.models import Chunk, Document, Entity

    from tests.db_helpers import make_user

    if age is None:
        age = timedelta(minutes=settings.document_stuck_after_minutes, seconds=1)
    user_id = await make_user()
    async with AsyncSessionLocal() as session:
        doc = Document(
            id=uuid4(), user_id=user_id, source="consulta", mime_type="audio/webm",
            s3_key=f"users/{user_id}/{uuid4()}-consulta.webm",
            created_at=datetime.now(timezone.utc) - age,
        )
        session.add(doc)
        await session.flush()
        if with_debris:
            session.add(Entity(
                user_id=user_id, document_id=doc.id, entity_type="observation",
                name="mitad de una extraccion", value={}, raw_quote="a medias",
                status="active", provenance="extracted_from_clinician_doc",
                confidence=0.5,
            ))
            session.add(Chunk(
                document_id=doc.id, user_id=user_id, content="a medias",
                embedding=[0.1] * 1024, chunk_index=0, chunk_metadata={},
            ))
        await session.commit()
        return user_id, doc.id


async def _status_of(doc_id):
    from adelia.db import AsyncSessionLocal
    from adelia.models import Document
    from adelia.schemas import derive_status

    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, doc_id)
        return derive_status(doc.raw_text, doc.processed_at)


async def _counts_for(doc_id):
    import sqlalchemy as sa

    from adelia.db import AsyncSessionLocal
    from adelia.models import Chunk, Entity

    async with AsyncSessionLocal() as session:
        entities = await session.scalar(
            sa.select(sa.func.count()).select_from(Entity).where(Entity.document_id == doc_id)
        )
        chunks = await session.scalar(
            sa.select(sa.func.count()).select_from(Chunk).where(Chunk.document_id == doc_id)
        )
    return entities, chunks


async def test_boot_reconciliation_requeues_a_document_a_dead_worker_left():
    """Kill the pipeline halfway, restart: the document ends processed."""
    from adelia.routers import documents as docs_mod

    _user_id, doc_id = await _make_stuck_document()
    assert await _status_of(doc_id) == "processing"

    async def fake_pipeline(document_id, mime_type, is_consulta=False):
        """Stands in for the real pipeline (no Mistral, no MinIO); writes the
        same final transaction `_process_document_inner` always writes."""
        from adelia.db import AsyncSessionLocal
        from adelia.models import Document

        async with AsyncSessionLocal() as session:
            doc = await session.get(Document, document_id)
            doc.raw_text = "transcripcion recuperada"
            doc.processed_at = datetime.now(timezone.utc)
            await session.commit()

    original = docs_mod.process_document
    docs_mod.process_document = fake_pipeline
    try:
        # Small cap on purpose: the seeded row is the newest eligible one, so
        # a boot that can only afford a handful still reaches it.
        requeued = await docs_mod.requeue_stuck_documents(limit=5)
        assert doc_id in requeued
        # Drain every task this boot spawned before the test's event loop is
        # torn down: a pipeline outliving its loop shows up as asyncpg's
        # "unexpected connection_lost()" noise in an unrelated test.
        await asyncio.wait_for(
            asyncio.gather(*list(docs_mod._BACKGROUND_TASKS), return_exceptions=True),
            timeout=30,
        )
    finally:
        docs_mod.process_document = original

    assert await _status_of(doc_id) == "ready"


async def test_reconciliation_clears_the_debris_of_the_dead_attempt():
    """Otherwise the second run duplicates every entity and every chunk, and
    the chat cites the same quote twice."""
    from adelia.routers import documents as docs_mod

    _user_id, doc_id = await _make_stuck_document()
    assert await _counts_for(doc_id) == (1, 1)

    async def noop(document_id, mime_type, is_consulta=False):
        return None

    original = docs_mod.process_document
    docs_mod.process_document = noop
    try:
        assert doc_id in await docs_mod.requeue_stuck_documents(limit=5)
        await asyncio.gather(*list(docs_mod._BACKGROUND_TASKS), return_exceptions=True)
    finally:
        docs_mod.process_document = original

    assert await _counts_for(doc_id) == (0, 0)


async def test_reconciliation_leaves_a_healthy_in_flight_upload_alone():
    """A document uploaded seconds ago is being processed right now; requeuing
    it underneath its own running task would double the work and the cost."""
    from adelia.routers import documents as docs_mod

    _user_id, fresh_id = await _make_stuck_document(age=timedelta(0), with_debris=False)
    requeued = await docs_mod.requeue_stuck_documents(limit=5)
    assert fresh_id not in requeued


async def test_a_failing_pipeline_ends_failed_not_hung():
    """The other half of the guarantee: when the work itself cannot be done,
    the row still leaves "processing", so the UI can offer a retry instead of
    a spinner that never stops."""
    from adelia.routers import documents as docs_mod

    _user_id, doc_id = await _make_stuck_document(with_debris=False)

    class Boom:
        async def get_object(self, key):
            raise RuntimeError("MinIO unreachable")

    original_storage = docs_mod.storage
    docs_mod.storage = Boom()
    try:
        await docs_mod.process_document(doc_id, "audio/webm", True)
    finally:
        docs_mod.storage = original_storage

    assert await _status_of(doc_id) == "failed"


async def test_reprocess_endpoint_resets_and_requeues(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from adelia.auth import get_current_user_id, require_active_subscription
    from adelia.main import app
    from adelia.routers import documents as docs_mod

    user_id, doc_id = await _make_stuck_document()
    # Pretend the first attempt finished and failed: processed_at set, no text.
    from adelia.db import AsyncSessionLocal
    from adelia.models import Document

    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, doc_id)
        doc.processed_at = datetime.now(timezone.utc)
        await session.commit()
    assert await _status_of(doc_id) == "failed"

    ran: list = []

    async def fake_pipeline(document_id, mime_type, is_consulta=False):
        ran.append((document_id, mime_type, is_consulta))

    monkeypatch.setattr(docs_mod, "process_document", fake_pipeline)
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[require_active_subscription] = lambda: user_id
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(f"/documents/{doc_id}/reprocess")
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
        app.dependency_overrides.pop(require_active_subscription, None)

    assert res.status_code == 202
    assert res.json()["status"] == "processing"
    assert ran == [(doc_id, "audio/webm", True)]
    # The half-written derivatives of the failed attempt are gone.
    assert await _counts_for(doc_id) == (0, 0)


async def test_reprocess_is_an_opaque_404_across_users():
    from httpx import ASGITransport, AsyncClient

    from adelia.auth import get_current_user_id, require_active_subscription
    from adelia.main import app

    from tests.db_helpers import make_user

    _owner, doc_id = await _make_stuck_document(with_debris=False)
    intruder = await make_user()

    app.dependency_overrides[get_current_user_id] = lambda: intruder
    app.dependency_overrides[require_active_subscription] = lambda: intruder
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(f"/documents/{doc_id}/reprocess")
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
        app.dependency_overrides.pop(require_active_subscription, None)

    assert res.status_code == 404


async def test_shutdown_unwinds_a_pipeline_before_the_engine_is_disposed(monkeypatch):
    """A pipeline boot reconciliation spawned must be gone, with its connection
    back in the pool, by the time the lifespan disposes the engine.

    The lifespan used to cancel only its own sweep and reminder tasks. A
    pipeline still mid-query then outlived `engine.dispose()`, checked a new
    connection out of the rebuilt pool and was killed by the loop teardown
    before the session could return it: SQLAlchemy's "garbage collector is
    trying to clean up non-checked-in connection" at the end of the suite,
    blamed on whichever unrelated test happened to be running (the dev
    database holds hundreds of stuck rows, so every TestClient(app) boot
    requeued some).

    The fake pipeline holds a real pooled connection and then sleeps. Before
    the fix it is still alive after the lifespan exits, with the connection
    checked out; after it, it is cancelled and the connection was checked in.
    """
    import sqlalchemy as sa
    from unittest.mock import AsyncMock

    from adelia.config import settings
    from adelia.db import AsyncSessionLocal, engine
    from adelia.main import app, lifespan
    from adelia.routers import documents as docs_mod
    from adelia.routers import users as users_mod

    # Only the shutdown path is under test: no boot sweep, no boot requeue
    # (which would spawn real pipelines of its own), no evidence load, no
    # Telegram reminder loop.
    monkeypatch.setattr(users_mod, "sweep_blob_tombstones", AsyncMock())
    monkeypatch.setattr(docs_mod, "requeue_stuck_documents", AsyncMock(return_value=[]))
    monkeypatch.setattr(settings, "mistral_api_key", "")
    monkeypatch.setattr(settings, "telegram_bot_token", "")

    holding = asyncio.Event()

    async def hold_a_connection(document_id, mime_type, is_consulta=False):
        async with AsyncSessionLocal() as session:
            await session.execute(sa.text("select 1"))
            holding.set()
            await asyncio.sleep(30)

    monkeypatch.setattr(docs_mod, "process_document", hold_a_connection)

    pool = engine.pool
    task = None
    try:
        async with lifespan(app):
            task = docs_mod._spawn_pipeline(uuid4(), "audio/webm", True)
            await asyncio.wait_for(holding.wait(), timeout=10)
            assert pool.checkedout() == 1
        # Judged BEFORE the cleanup below, which would otherwise cancel the
        # task itself and hide the regression.
        assert task.cancelled(), "the lifespan left a pipeline running past engine.dispose()"
        assert pool.checkedout() == 0
        assert task not in docs_mod._BACKGROUND_TASKS
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
