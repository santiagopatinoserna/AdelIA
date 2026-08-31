"""RGPD audio retention: tombstone grace window + not_before-filtered sweep.

PG-gated (matches tests/test_consent_models.py's pattern — no db_session/
seeded_user/pg_required fixtures exist in this repo; use AsyncSessionLocal
directly + tests.db_helpers.make_user + PG_AVAILABLE skipif)."""
from __future__ import annotations

import asyncio
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
        # What upload_document writes in the same transaction as the Document.
        # Seeded here because this test builds the row by hand: the pipeline
        # only ever brings an EXISTING tombstone forward, it never creates one
        # (see test_the_pipeline_never_creates_a_tombstone_it_did_not_find).
        session.add(
            BlobTombstone(
                s3_key=s3_key, not_before=datetime.now(timezone.utc) + timedelta(days=7)
            )
        )
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


# --- Tombstone written AT UPLOAD (audit 4.2) --------------------------------
#
# Until 2026-08-31 the ONLY place a recording got its deletion date was the
# final write of the pipeline (documents.py:308-318), after transcription,
# summary, extraction and embedding. A container that died in between (it did,
# on 30-ago at 16:06:55Z) left the audio of a real appointment in MinIO with
# no expiry at all, and the hourly sweep only ever looks at the table. The
# tombstone is now written in the same transaction as the Document, at +7
# days (the window the DPIA already justifies), and brought forward to +48h
# when the transcript exists.


async def _upload_consulta(client, monkeypatch, *, source: str = "consulta") -> tuple[str, str]:
    """POST /documents through the real endpoint, with S3 and the pipeline
    stubbed. Returns (document_id, s3_key)."""
    from adelia.config import settings
    from adelia.db import AsyncSessionLocal
    from adelia.routers import documents as docs_mod

    from tests.test_auth import make_token

    monkeypatch.setattr(settings, "auth_secret", "test-secret")

    async def _put(key, body, content_type=None):
        return None

    async def _noop_process(document_id, mime_type, is_consulta=False):
        return None

    monkeypatch.setattr(docs_mod.storage, "put_object", _put)
    monkeypatch.setattr(docs_mod, "process_document", _noop_process)

    user_id = await make_user()
    data = {"source": source}
    if source == "consulta":
        data["consent_policy_version"] = "2026-08-17"
    resp = await client.post(
        "/documents",
        headers={"Authorization": f"Bearer {make_token(str(user_id))}"},
        files={"file": ("consulta.webm", b"fake-audio", "audio/webm;codecs=opus")},
        data=data,
    )
    assert resp.status_code == 201, resp.text
    doc_id = resp.json()["id"]
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, uuid.UUID(doc_id))
        return doc_id, doc.s3_key


async def _tombstone(s3_key: str) -> BlobTombstone | None:
    from adelia.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        return (await session.execute(
            sa.select(BlobTombstone).where(BlobTombstone.s3_key == s3_key)
        )).scalar_one_or_none()


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres")
@pytest.mark.asyncio
async def test_upload_writes_the_tombstone_before_any_processing(client, monkeypatch):
    _, s3_key = await _upload_consulta(client, monkeypatch)

    row = await _tombstone(s3_key)
    assert row is not None, "the recording must have an expiry from the second it lands"
    now = datetime.now(timezone.utc)
    assert now + timedelta(days=6, hours=23) < row.not_before < now + timedelta(days=7, hours=1)


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres")
@pytest.mark.asyncio
async def test_killing_the_pipeline_midway_leaves_the_7_day_tombstone(client, monkeypatch):
    """The 30-ago incident, reproduced: the task dies during transcription
    (a container SIGTERM cancels it). Before this fix nothing was scheduled
    and the audio survived forever."""
    from adelia.routers import documents as docs_mod

    doc_id, s3_key = await _upload_consulta(client, monkeypatch)

    class _FakeBody:
        def read(self) -> bytes:
            return b"fake-consulta-audio-bytes"

    async def fake_get_object(key: str):
        return _FakeBody()

    async def dying_transcribe(body, mime_type, diarize=False):
        raise asyncio.CancelledError()  # what a SIGTERM does to an in-flight task

    monkeypatch.setattr(documents_storage, "get_object", fake_get_object)
    monkeypatch.setattr(docs_mod, "transcribe_audio", dying_transcribe)

    with pytest.raises(asyncio.CancelledError):
        await _process_document_inner(uuid.UUID(doc_id), "audio/webm", True)

    row = await _tombstone(s3_key)
    assert row is not None
    now = datetime.now(timezone.utc)
    assert now + timedelta(days=6, hours=23) < row.not_before < now + timedelta(days=7, hours=1)


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres")
@pytest.mark.asyncio
async def test_successful_pipeline_brings_the_tombstone_forward_to_48h(client, monkeypatch):
    """The upload-time row is upserted, not duplicated: one blob, one
    tombstone, and the date only moves closer."""
    from adelia.routers import documents as docs_mod

    doc_id, s3_key = await _upload_consulta(client, monkeypatch)
    assert (await _tombstone(s3_key)) is not None

    class _FakeBody:
        def read(self) -> bytes:
            return b"fake-consulta-audio-bytes"

    async def fake_get_object(key: str):
        return _FakeBody()

    async def fake_transcribe(body, mime_type, diarize=False):
        return "hola, esto es una consulta de prueba"

    async def fake_summarize(text):
        return ""

    async def fake_extract(text: str):
        return []

    async def fake_embed(texts: list[str]):
        return [[0.0] * 1024 for _ in texts]

    monkeypatch.setattr(documents_storage, "get_object", fake_get_object)
    monkeypatch.setattr(docs_mod, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(docs_mod, "summarize_consultation", fake_summarize)
    monkeypatch.setattr(docs_mod, "extract_entities", fake_extract)
    monkeypatch.setattr(docs_mod, "embed_texts", fake_embed)

    await _process_document_inner(uuid.UUID(doc_id), "audio/webm", True)

    from adelia.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            sa.select(BlobTombstone).where(BlobTombstone.s3_key == s3_key)
        )).scalars().all()
    assert len(rows) == 1, "the upload-time tombstone is updated, never duplicated"
    now = datetime.now(timezone.utc)
    assert now + timedelta(hours=47) < rows[0].not_before < now + timedelta(hours=49)


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres")
@pytest.mark.asyncio
async def test_telegram_voice_note_is_tombstoned_at_ingestion(monkeypatch):
    """Same rule on the other upload path: a voice note reaches MinIO through
    services/telegram_diary.ingest_bytes, which never went near the consulta
    branch that used to hold the only tombstone write."""
    from adelia.services import telegram_diary as diary

    async def _put(key, body, content_type=None):
        return None

    async def _noop_process(document_id, mime_type, is_consulta=False):
        return None

    monkeypatch.setattr(diary.storage, "put_object", _put)
    monkeypatch.setattr("adelia.routers.documents.process_document", _noop_process)

    user_id = await make_user()
    doc = await diary.ingest_bytes(
        user_id=user_id, body=b"OggS", mime="audio/ogg", filename="diario.ogg",
        metadata={"channel": "telegram", "diary_date": "2026-08-31"},
    )

    row = await _tombstone(doc.s3_key)
    assert row is not None
    now = datetime.now(timezone.utc)
    assert now + timedelta(days=6, hours=23) < row.not_before < now + timedelta(days=7, hours=1)


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres")
@pytest.mark.asyncio
async def test_a_pdf_upload_is_never_tombstoned(client, monkeypatch):
    """Retention applies to the recording, not to the report the parent
    uploaded to keep. Only audio blobs get an expiry."""
    from adelia.config import settings
    from adelia.db import AsyncSessionLocal
    from adelia.routers import documents as docs_mod

    from tests.test_auth import make_token

    monkeypatch.setattr(settings, "auth_secret", "test-secret")

    async def _put(key, body, content_type=None):
        return None

    async def _noop_process(document_id, mime_type, is_consulta=False):
        return None

    monkeypatch.setattr(docs_mod.storage, "put_object", _put)
    monkeypatch.setattr(docs_mod, "process_document", _noop_process)

    user_id = await make_user()
    resp = await client.post(
        "/documents",
        headers={"Authorization": f"Bearer {make_token(str(user_id))}"},
        files={"file": ("informe.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, uuid.UUID(resp.json()["id"]))
        s3_key = doc.s3_key

    assert (await _tombstone(s3_key)) is None


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres")
@pytest.mark.asyncio
async def test_a_web_audio_upload_is_not_tombstoned(client, monkeypatch):
    """Retention covers the consultation recording and the diary voice note.

    Audit 1.9 asked for the consulta tombstone to be written EARLIER, not for
    retention to widen. The first fix keyed both writes on `_is_audio`, which
    the ordinary upload zone reaches: components/upload-zone.tsx accepts
    "audio/*" and its FormData sends no `source`, so such a file lands as
    source="web". It had no expiry before and got one, 48h after a successful
    transcription, silently deleting an audio a parent deliberately filed as a
    document of hers. /privacidad and the DPIA both say the exception is the
    consultation audio, and this test is what keeps the code from promising
    less conservation than the page sold to her.
    """
    _, s3_key = await _upload_consulta(client, monkeypatch, source="web")

    assert (await _tombstone(s3_key)) is None


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres")
@pytest.mark.asyncio
async def test_the_pipeline_never_creates_a_tombstone_it_did_not_find(client, monkeypatch):
    """schedule_audio_deletion's own docstring: "the row already exists from
    upload time, and the end of the pipeline only ever brings the date
    forward". The pipeline now honours it, so a web audio stays untombstoned
    even after a successful transcription."""
    from adelia.routers import documents as docs_mod

    doc_id, s3_key = await _upload_consulta(client, monkeypatch, source="web")
    assert (await _tombstone(s3_key)) is None

    class _FakeBody:
        def read(self) -> bytes:
            return b"fake-audio-bytes"

    async def fake_get_object(key: str):
        return _FakeBody()

    async def fake_transcribe(body, mime_type, diarize=False):
        return "nota de voz de la madre"

    async def fake_extract(text: str):
        return []

    async def fake_embed(texts: list[str]):
        return [[0.0] * 1024 for _ in texts]

    monkeypatch.setattr(documents_storage, "get_object", fake_get_object)
    monkeypatch.setattr(docs_mod, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(docs_mod, "extract_entities", fake_extract)
    monkeypatch.setattr(docs_mod, "embed_texts", fake_embed)

    await _process_document_inner(uuid.UUID(doc_id), "audio/webm", False)

    assert (await _tombstone(s3_key)) is None


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres")
@pytest.mark.asyncio
async def test_the_pipeline_does_not_resurrect_an_erased_accounts_tombstone(
    client, monkeypatch
):
    """routers/users.delete_my_account writes not_before=None (erase now). A
    pipeline finishing after that must not push it back to +48h."""
    from adelia.db import AsyncSessionLocal
    from adelia.routers import documents as docs_mod

    doc_id, s3_key = await _upload_consulta(client, monkeypatch)

    async with AsyncSessionLocal() as session:
        await session.merge(BlobTombstone(s3_key=s3_key, not_before=None))
        await session.commit()

    class _FakeBody:
        def read(self) -> bytes:
            return b"fake-consulta-audio-bytes"

    async def fake_get_object(key: str):
        return _FakeBody()

    async def fake_transcribe(body, mime_type, diarize=False):
        return "hola"

    async def fake_summarize(text):
        return ""

    async def fake_extract(text: str):
        return []

    async def fake_embed(texts: list[str]):
        return [[0.0] * 1024 for _ in texts]

    monkeypatch.setattr(documents_storage, "get_object", fake_get_object)
    monkeypatch.setattr(docs_mod, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(docs_mod, "summarize_consultation", fake_summarize)
    monkeypatch.setattr(docs_mod, "extract_entities", fake_extract)
    monkeypatch.setattr(docs_mod, "embed_texts", fake_embed)

    await _process_document_inner(uuid.UUID(doc_id), "audio/webm", True)

    assert (await _tombstone(s3_key)).not_before is None


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres")
@pytest.mark.asyncio
async def test_erasing_the_account_deletes_audio_now_not_in_seven_days(client, monkeypatch):
    """Erasure overrides the retention window.

    session.merge() only copies attributes that were SET on the instance, so
    the bare BlobTombstone(s3_key=key) that routers/users.delete_my_account
    used left the upload-time +7d date untouched: the recording would have
    outlived the account by a week. Probed against the real DB before fixing.
    """
    from adelia.db import AsyncSessionLocal
    from adelia.routers import users as users_mod

    _, s3_key = await _upload_consulta(client, monkeypatch)
    assert (await _tombstone(s3_key)).not_before is not None  # 7 days out

    deleted: list[str] = []

    async def fake_delete(key):
        deleted.append(key)

    monkeypatch.setattr(users_mod.storage, "delete_object", fake_delete)

    # Exactly what delete_my_account does inside the erase transaction.
    async with AsyncSessionLocal() as session:
        await session.merge(BlobTombstone(s3_key=s3_key, not_before=None))
        await session.commit()

    assert (await _tombstone(s3_key)).not_before is None
    await sweep_blob_tombstones()
    assert s3_key in deleted
    assert (await _tombstone(s3_key)) is None
