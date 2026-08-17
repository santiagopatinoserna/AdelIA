"""RGPD audio retention: tombstone grace window + not_before-filtered sweep.

PG-gated (matches tests/test_consent_models.py's pattern — no db_session/
seeded_user/pg_required fixtures exist in this repo; use AsyncSessionLocal
directly + tests.db_helpers.make_user + PG_AVAILABLE skipif)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from adelia.models import BlobTombstone, Document
from adelia.routers.documents import _process_document_inner
from adelia.routers.documents import storage as documents_storage
from adelia.routers.users import sweep_blob_tombstones

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres")
@pytest.mark.asyncio
async def test_sweep_skips_future_tombstones(monkeypatch):
    from adelia.db import AsyncSessionLocal

    deleted: list[str] = []

    async def fake_delete(key):
        deleted.append(key)

    monkeypatch.setattr("adelia.routers.users.storage.delete_object", fake_delete)

    now = datetime.now(timezone.utc)
    old_key = f"users/x/old-blob-{uuid.uuid4()}"
    expired_key = f"users/x/expired-{uuid.uuid4()}"
    fresh_key = f"users/x/fresh-audio-{uuid.uuid4()}"

    async with AsyncSessionLocal() as session:
        session.add_all([
            BlobTombstone(s3_key=old_key, not_before=None),
            BlobTombstone(s3_key=expired_key, not_before=now - timedelta(hours=1)),
            BlobTombstone(s3_key=fresh_key, not_before=now + timedelta(hours=48)),
        ])
        await session.commit()

    await sweep_blob_tombstones()

    assert set(deleted) == {old_key, expired_key}

    async with AsyncSessionLocal() as session:
        remaining = (await session.execute(
            sa.select(BlobTombstone.s3_key).where(BlobTombstone.s3_key == fresh_key)
        )).scalar_one_or_none()
        assert remaining == fresh_key  # future tombstone survives the sweep


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres")
@pytest.mark.asyncio
async def test_consulta_pipeline_schedules_audio_deletion(monkeypatch):
    """After a consulta doc finishes processing (transcription succeeds),
    its blob is tombstoned ~48h out and document_metadata records the
    schedule. Mocks follow tests/test_pipeline_resilience.py's style of
    patching adelia.routers.documents module attributes directly (no
    pipeline-mocking test existed to copy verbatim; transcribe/get_object/
    extract/embed are all module-level names in adelia/routers/documents.py)."""
    from adelia.db import AsyncSessionLocal
    from adelia.routers import documents as docs_mod

    class _FakeBody:
        def read(self) -> bytes:
            return b"fake-consulta-audio-bytes"

    async def fake_get_object(key: str):
        return _FakeBody()

    async def fake_transcribe(body, mime_type, diarize=False):
        return "hola, esto es una consulta de prueba"

    async def fake_extract(text: str):
        return []

    async def fake_embed(texts: list[str]):
        return [[0.0] * 1024 for _ in texts]

    monkeypatch.setattr(documents_storage, "get_object", fake_get_object)
    monkeypatch.setattr(docs_mod, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(docs_mod, "extract_entities", fake_extract)
    monkeypatch.setattr(docs_mod, "embed_texts", fake_embed)

    user_id = await make_user()
    s3_key = f"users/{user_id}/{uuid.uuid4()}-consulta.webm"

    async with AsyncSessionLocal() as session:
        doc = Document(
            id=uuid.uuid4(),
            user_id=user_id,
            source="consulta",
            mime_type="audio/webm",
            s3_key=s3_key,
        )
        session.add(doc)
        await session.commit()
        doc_id = doc.id

    await _process_document_inner(doc_id, "audio/webm", True)

    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            sa.select(BlobTombstone).where(BlobTombstone.s3_key == s3_key)
        )).scalar_one()
        assert row.not_before is not None
        now = datetime.now(timezone.utc)
        assert now + timedelta(hours=47) < row.not_before < now + timedelta(hours=49)

        refreshed = await session.get(Document, doc_id)
        assert refreshed.document_metadata["audio_deleted_scheduled"] is True
