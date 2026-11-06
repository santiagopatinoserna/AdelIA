"""GDPR right-to-erasure: DELETE /users/me removes the whole graph."""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import Briefing, Chunk, Document, Entity, ShareLink, User
from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE
from tests.test_auth import make_token


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_delete_me_erases_documents_briefings_shares(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    user_id = await make_user()

    async with AsyncSessionLocal() as session:
        doc = Document(
            user_id=user_id, source="web", mime_type="application/pdf",
            s3_key=f"users/{user_id}/{uuid4()}-x.pdf", raw_text="data",
        )
        session.add(doc)
        await session.flush()
        session.add(Entity(
            user_id=user_id, document_id=doc.id, entity_type="observation",
            name="glucosa", provenance="extracted_from_clinician_doc",
        ))
        session.add(Chunk(
            user_id=user_id, document_id=doc.id, content="texto", chunk_index=0,
        ))
        briefing = Briefing(user_id=user_id, target_specialty="default")
        session.add(briefing)
        await session.flush()
        session.add(ShareLink(
            token=f"tok-{uuid4()}", user_id=user_id, briefing_id=briefing.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        await session.commit()

    token = make_token(str(user_id))
    response = await client.delete(
        "/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 204

    async with AsyncSessionLocal() as session:
        for model in (User, Document, Entity, Chunk, Briefing, ShareLink):
            owner = model.user_id if model is not User else model.id
            count = await session.scalar(
                sa.select(sa.func.count()).select_from(model).where(owner == user_id)
            )
            assert count == 0, f"{model.__tablename__} not erased"


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_delete_me_requires_auth(client):
    response = await client.delete("/users/me")
    assert response.status_code in (401, 403)


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_delete_me_erases_conversations_tagged_with_a_child(client, monkeypatch):
    """chat_sessions.profile_id must not keep a session alive once the account goes."""
    from adelia.models import ChatMessage, ChatSession, Profile

    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    user_id = await make_user()
    async with AsyncSessionLocal() as session:
        nora = Profile(user_id=user_id, display_name="Nora", relationship="child",
                       is_default=True)
        session.add(nora)
        await session.flush()
        chat = ChatSession(user_id=user_id, title="t", profile_id=nora.id)
        session.add(chat)
        await session.flush()
        session.add(ChatMessage(session_id=chat.id, user_id=user_id, role="user", content="x"))
        await session.commit()

    token = make_token(str(user_id))
    response = await client.delete("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 204
    async with AsyncSessionLocal() as session:
        for model in (ChatSession, ChatMessage, Profile):
            count = await session.scalar(
                sa.select(sa.func.count()).select_from(model).where(model.user_id == user_id)
            )
            assert count == 0, f"{model.__tablename__} not erased"


async def _seed_document(user_id) -> str:
    """A processed document (so no boot reconciliation picks it up) whose blob
    the erasure has to tombstone. Returns its s3_key."""
    s3_key = f"users/{user_id}/{uuid4()}-informe.pdf"
    async with AsyncSessionLocal() as session:
        session.add(Document(
            user_id=user_id, source="web", mime_type="application/pdf",
            s3_key=s3_key, processed_at=datetime.now(timezone.utc),
        ))
        await session.commit()
    return s3_key


async def _tombstone_exists(s3_key: str) -> bool:
    from adelia.models import BlobTombstone

    async with AsyncSessionLocal() as session:
        found = await session.scalar(
            sa.select(BlobTombstone.s3_key).where(BlobTombstone.s3_key == s3_key)
        )
    return found is not None


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_delete_me_answers_before_blob_storage_does(client, monkeypatch):
    """The 204 must not wait on object storage, and her erasure sweeps her
    blobs only.

    The CI flake behind e2e/poc-journey step 15: the request awaited a sweep of
    EVERY due tombstone in the system. The e2e job runs no MinIO, so each key
    cost 4 to 9 s of botocore retries, the backlog grew over the suite, and the
    French run, which deletes later, answered 204 after 21.6 s
    (elapsed_ms=21581): the page sat on its "deleting" state past the test's
    20 s. A mother would wait the same way whenever storage is slow or a
    backlog exists. Her account is gone at the commit; the durable tombstone
    is what guarantees the blob follows.
    """
    from adelia.models import BlobTombstone
    from adelia.routers import users as users_mod

    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    user_id = await make_user()
    her_key = await _seed_document(user_id)
    # Somebody else's tombstone a failed earlier sweep left behind: the boot
    # and hourly sweeps own that backlog, not her request.
    foreign_key = f"users/{uuid4()}/{uuid4()}-backlog.pdf"
    async with AsyncSessionLocal() as session:
        session.add(BlobTombstone(s3_key=foreign_key, not_before=None))
        await session.commit()

    storage_back = asyncio.Event()
    asked: list[str] = []

    async def unreachable_storage(key: str) -> None:
        asked.append(key)
        await storage_back.wait()

    monkeypatch.setattr(users_mod.storage, "delete_object", unreachable_storage)
    token = make_token(str(user_id))
    try:
        response = await asyncio.wait_for(
            client.delete("/users/me", headers={"Authorization": f"Bearer {token}"}),
            timeout=5,
        )
        assert response.status_code == 204
        async with AsyncSessionLocal() as session:
            assert await session.get(User, user_id) is None
        # Storage has not answered yet: the tombstone is still the record
        # that her blob is owed a deletion.
        assert await _tombstone_exists(her_key)

        storage_back.set()
        await users_mod.drain_erasure_sweeps()
        assert asked == [her_key]
        assert not await _tombstone_exists(her_key)
    finally:
        storage_back.set()
        await users_mod.drain_erasure_sweeps()
        async with AsyncSessionLocal() as session:
            await session.execute(
                sa.delete(BlobTombstone).where(BlobTombstone.s3_key == foreign_key)
            )
            await session.commit()


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_blob_sweep_holds_no_db_connection_while_storage_works(monkeypatch):
    """House rule: no session held across network I/O. The sweep used to keep
    one open for every delete_object, so a slow storage pinned a pooled
    connection per sweep for as long as botocore kept retrying."""
    from adelia.db import engine
    from adelia.models import BlobTombstone
    from adelia.routers import users as users_mod

    key = f"users/{uuid4()}/{uuid4()}-x.pdf"
    async with AsyncSessionLocal() as session:
        session.add(BlobTombstone(s3_key=key, not_before=None))
        await session.commit()

    checked_out: list[int] = []

    async def record_pool(k: str) -> None:
        checked_out.append(engine.sync_engine.pool.checkedout())

    monkeypatch.setattr(users_mod.storage, "delete_object", record_pool)
    await users_mod.sweep_blob_tombstones(keys=[key])

    assert checked_out == [0]
    assert not await _tombstone_exists(key)
