"""Per-document deletion (GDPR art. 17 at document granularity). PG-gated.

Closes the gap the DPIA documented: until now the only self-service erasure
was the whole account. Deleting one document must erase the row plus its
derived records (entities/chunks via ON DELETE CASCADE), tombstone the S3
blob for immediate sweep, and stay opaque (404) across users.
"""
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from adelia.auth import get_current_user_id
from adelia.main import app
from adelia.models import BlobTombstone, Chunk, Document, Entity

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE

pytestmark = pytest.mark.skipif(
    not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres"
)


async def _seed_doc_with_children(user_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    from adelia.db import AsyncSessionLocal

    doc_id = uuid.uuid4()
    s3_key = f"users/{user_id}/{uuid.uuid4()}-consulta.webm"
    async with AsyncSessionLocal() as session:
        session.add(
            Document(
                id=doc_id,
                user_id=user_id,
                source="web",
                mime_type="audio/webm",
                s3_key=s3_key,
                raw_text="[Hablante 1] Hola.",
            )
        )
        await session.flush()
        session.add(
            Entity(
                user_id=user_id,
                document_id=doc_id,
                entity_type="medication",
                name="paracetamol",
                provenance="extracted_from_clinician_doc",
                confidence=0.9,
                raw_quote="paracetamol",
            )
        )
        session.add(
            Chunk(
                document_id=doc_id,
                user_id=user_id,
                content="Hola.",
                chunk_index=0,
            )
        )
        await session.commit()
    return doc_id, s3_key


def _client_as(user_id: uuid.UUID) -> AsyncClient:
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _counts(doc_id: uuid.UUID) -> tuple[int, int, int]:
    from adelia.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        docs = (
            await session.execute(
                sa.select(sa.func.count()).select_from(Document).where(Document.id == doc_id)
            )
        ).scalar_one()
        ents = (
            await session.execute(
                sa.select(sa.func.count()).select_from(Entity).where(Entity.document_id == doc_id)
            )
        ).scalar_one()
        chunks = (
            await session.execute(
                sa.select(sa.func.count()).select_from(Chunk).where(Chunk.document_id == doc_id)
            )
        ).scalar_one()
    return docs, ents, chunks


@pytest.mark.asyncio
async def test_delete_document_erases_row_children_and_tombstones_blob(monkeypatch):
    from adelia.db import AsyncSessionLocal
    from adelia.routers import users as users_router

    swept: list[list[str] | None] = []

    async def fake_sweep(keys=None):
        swept.append(keys)

    monkeypatch.setattr(users_router, "sweep_blob_tombstones", fake_sweep)

    user_id = await make_user()
    doc_id, s3_key = await _seed_doc_with_children(user_id)

    try:
        async with _client_as(user_id) as client:
            resp = await client.delete(f"/documents/{doc_id}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 204
    assert await _counts(doc_id) == (0, 0, 0)
    async with AsyncSessionLocal() as session:
        tomb = (
            await session.execute(
                sa.select(BlobTombstone).where(BlobTombstone.s3_key == s3_key)
            )
        ).scalar_one_or_none()
    # Immediate-erasure semantics: no grace window, next sweep deletes it.
    assert tomb is not None and tomb.not_before is None
    # The sweep runs after the 204 (see the test below); wait for it.
    await users_router.drain_erasure_sweeps()
    assert swept, "opportunistic sweep should run after a per-document delete"
    assert swept == [[s3_key]], "a per-document delete sweeps that document's blob only"


@pytest.mark.asyncio
async def test_delete_document_is_opaque_across_users():
    owner = await make_user()
    attacker = await make_user()
    doc_id, _ = await _seed_doc_with_children(owner)

    try:
        async with _client_as(attacker) as client:
            resp = await client.delete(f"/documents/{doc_id}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404
    docs, ents, chunks = await _counts(doc_id)
    assert (docs, ents, chunks) == (1, 1, 1), "nothing may be deleted cross-user"


@pytest.mark.asyncio
async def test_delete_nonexistent_document_404():
    user_id = await make_user()
    try:
        async with _client_as(user_id) as client:
            resp = await client.delete(f"/documents/{uuid.uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


async def _tombstone_exists(s3_key: str) -> bool:
    from adelia.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        found = await session.scalar(
            sa.select(BlobTombstone.s3_key).where(BlobTombstone.s3_key == s3_key)
        )
    return found is not None


@pytest.mark.asyncio
async def test_delete_document_answers_before_blob_storage_does(monkeypatch):
    """The 204 must not wait on object storage, and deleting one PDF sweeps
    that PDF's blob only.

    The request used to await a sweep of EVERY due tombstone in the system,
    other users' too. With storage slow or unreachable each key costs 4 to 9 s
    of botocore retries (measured on the 2026-11-06 night run), so a mother
    deleting one report waited for everybody's backlog. The row is gone at the
    commit; the durable tombstone is what guarantees the blob follows.
    """
    import asyncio
    from datetime import datetime, timezone

    from adelia.db import AsyncSessionLocal
    from adelia.routers import users as users_mod

    user_id = await make_user()
    doc_id = uuid.uuid4()
    her_key = f"users/{user_id}/{uuid.uuid4()}-informe.pdf"
    # Somebody else's tombstone a failed earlier sweep left behind: the boot
    # and hourly sweeps own that backlog, not her request.
    foreign_key = f"users/{uuid.uuid4()}/{uuid.uuid4()}-backlog.pdf"
    async with AsyncSessionLocal() as session:
        # processed_at set: no boot reconciliation may pick this row up.
        session.add(Document(
            id=doc_id, user_id=user_id, source="web", mime_type="application/pdf",
            s3_key=her_key, processed_at=datetime.now(timezone.utc),
        ))
        session.add(BlobTombstone(s3_key=foreign_key, not_before=None))
        await session.commit()

    storage_back = asyncio.Event()
    asked: list[str] = []

    async def unreachable_storage(key: str) -> None:
        asked.append(key)
        await storage_back.wait()

    monkeypatch.setattr(users_mod.storage, "delete_object", unreachable_storage)
    try:
        async with _client_as(user_id) as client:
            resp = await asyncio.wait_for(client.delete(f"/documents/{doc_id}"), timeout=5)
        assert resp.status_code == 204
        assert await _counts(doc_id) == (0, 0, 0)
        # Storage has not answered yet: the tombstone is still the record that
        # her blob is owed a deletion.
        assert await _tombstone_exists(her_key)

        storage_back.set()
        await users_mod.drain_erasure_sweeps()
        assert asked == [her_key]
        assert not await _tombstone_exists(her_key)
        assert await _tombstone_exists(foreign_key), "her delete swept someone else's blob"
    finally:
        app.dependency_overrides.clear()
        storage_back.set()
        drain = getattr(users_mod, "drain_erasure_sweeps", None)
        if drain is not None:
            await drain()
        async with AsyncSessionLocal() as session:
            await session.execute(
                sa.delete(BlobTombstone).where(BlobTombstone.s3_key.in_([her_key, foreign_key]))
            )
            await session.commit()
