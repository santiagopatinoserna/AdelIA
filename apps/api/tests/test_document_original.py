"""Her original back: GET /documents/{id}/file. PG and MinIO.

The vault promise (docs/specs/ADELIA_SIMPLE.md, 2026-11-24): what a mother
sends is kept and she can open it again. Until then the blob was written at
upload and read by the pipeline only; no route gave the PDF, the photo or the
voice note back. The consultation audio is the exception the DPIA sets: it is
a means to its transcript, never an archive, so it is never served.
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import pytest
from httpx import ASGITransport, AsyncClient

from adelia.auth import get_current_user_id
from adelia.main import app
from adelia.models import BlobTombstone, Document
from adelia.storage import S3Storage

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE

pytestmark = pytest.mark.skipif(
    not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres"
)

# Not text: every byte value, so a decode or a newline rewrite on the way
# back would show.
PDF = b"%PDF-1.4\n% informe de la analitica\n" + bytes(range(256)) * 8


@pytest.fixture(autouse=True)
def _no_overrides_left():
    yield
    app.dependency_overrides.clear()


def _client_as(user_id: uuid.UUID) -> AsyncClient:
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed(
    user_id: uuid.UUID,
    *,
    name: str = "analitica.pdf",
    mime: str = "application/pdf",
    body: bytes = PDF,
    source: str = "web",
    raw_text: str | None = None,
    expires_in: timedelta | None = None,
    stored: bool = True,
) -> uuid.UUID:
    """A processed document (processed_at set, so a boot never requeues it).
    raw_text None means the pipeline could not read it: status "failed"."""
    from adelia.db import AsyncSessionLocal

    s3_key = f"users/{user_id}/{uuid.uuid4()}-{name}"
    if stored:
        await S3Storage().put_object(s3_key, io.BytesIO(body), content_type=mime)
    doc_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            Document(
                id=doc_id,
                user_id=user_id,
                source=source,
                mime_type=mime,
                s3_key=s3_key,
                raw_text=raw_text,
                processed_at=datetime.now(timezone.utc),
            )
        )
        if expires_in is not None:
            # What the retention code writes for a consultation recording or
            # a Telegram voice note (routers/documents.schedule_audio_deletion).
            session.add(
                BlobTombstone(
                    s3_key=s3_key, not_before=datetime.now(timezone.utc) + expires_in
                )
            )
        await session.commit()
    return doc_id


async def test_her_pdf_comes_back_byte_for_byte_even_when_reading_it_failed():
    user_id = await make_user()
    doc_id = await _seed(user_id)

    async with _client_as(user_id) as client:
        detail = await client.get(f"/documents/{doc_id}")
        resp = await client.get(f"/documents/{doc_id}/file")

    assert detail.json()["status"] == "failed"
    assert detail.json()["original"] is True
    assert resp.status_code == 200
    assert resp.content == PDF
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"].startswith("inline;")
    assert 'filename="analitica.pdf"' in resp.headers["content-disposition"]
    assert resp.headers["cache-control"] == "private, no-store"
    assert resp.headers["x-content-type-options"] == "nosniff"


async def test_a_photo_opens_in_the_browser_and_an_audio_she_filed_downloads():
    user_id = await make_user()
    photo = await _seed(user_id, name="cartilla.jpg", mime="image/jpeg", body=b"\xff\xd8jpeg")
    audio = await _seed(user_id, name="nota.webm", mime="audio/webm", body=b"webm-bytes")

    async with _client_as(user_id) as client:
        shown = await client.get(f"/documents/{photo}/file")
        saved = await client.get(f"/documents/{audio}/file")

    assert shown.status_code == 200
    assert shown.headers["content-disposition"].startswith("inline;")
    # An audio she uploaded herself through the upload zone is a document of
    # hers, not a recording on a retention clock: it comes back, as a file.
    assert saved.status_code == 200
    assert saved.content == b"webm-bytes"
    assert saved.headers["content-disposition"].startswith("attachment;")


async def test_a_name_with_accents_comes_back_whole():
    user_id = await make_user()
    doc_id = await _seed(user_id, name="análisis_lucía.pdf")

    async with _client_as(user_id) as client:
        resp = await client.get(f"/documents/{doc_id}/file")

    header = resp.headers["content-disposition"]
    assert resp.status_code == 200
    assert 'filename="an_lisis_luc_a.pdf"' in header
    utf8_name = header.split("filename*=UTF-8''", 1)[1]
    assert unquote(utf8_name) == "análisis_lucía.pdf"


async def test_the_consultation_audio_is_never_served_while_it_still_exists():
    """The DPIA keeps the recording only until its transcript exists (+48 h).
    The blob is still in MinIO here, and still not hers to download."""
    user_id = await make_user()
    doc_id = await _seed(
        user_id,
        name="consulta.webm",
        mime="audio/webm",
        body=b"visit-audio",
        source="consulta",
        raw_text="[Hablante 1] Todo bien.",
        expires_in=timedelta(hours=48),
    )

    async with _client_as(user_id) as client:
        detail = await client.get(f"/documents/{doc_id}")
        resp = await client.get(f"/documents/{doc_id}/file")

    assert detail.json()["original"] is False
    assert resp.status_code == 404


async def test_a_consultation_from_before_the_upload_tombstone_is_not_served_either():
    """Recordings from before the tombstone was written at upload (audit 1.9)
    can sit in MinIO with no deletion date. The source alone refuses them."""
    user_id = await make_user()
    doc_id = await _seed(
        user_id,
        name="consulta.webm",
        mime="audio/webm",
        body=b"old-visit-audio",
        source="consulta",
        raw_text="[Hablante 1] Todo bien.",
    )

    async with _client_as(user_id) as client:
        resp = await client.get(f"/documents/{doc_id}/file")

    assert resp.status_code == 404


async def test_a_blob_on_a_deletion_clock_is_not_served():
    """A Telegram voice note expires like the consultation audio: same rule,
    read from the tombstone, whatever the source says."""
    user_id = await make_user()
    doc_id = await _seed(
        user_id,
        name="diario.ogg",
        mime="audio/ogg",
        body=b"voice-note",
        source="manual",
        expires_in=timedelta(days=7),
    )

    async with _client_as(user_id) as client:
        detail = await client.get(f"/documents/{doc_id}")
        resp = await client.get(f"/documents/{doc_id}/file")

    assert detail.json()["original"] is False
    assert resp.status_code == 404


async def test_another_parents_file_is_the_same_404_as_none_at_all():
    owner = await make_user()
    stranger = await make_user()
    doc_id = await _seed(owner)

    async with _client_as(stranger) as client:
        theirs = await client.get(f"/documents/{doc_id}/file")
        missing = await client.get(f"/documents/{uuid.uuid4()}/file")

    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()


async def test_a_blob_storage_lost_is_a_404_not_a_500():
    user_id = await make_user()
    doc_id = await _seed(user_id, stored=False)

    async with _client_as(user_id) as client:
        resp = await client.get(f"/documents/{doc_id}/file")

    assert resp.status_code == 404


async def test_the_list_does_not_claim_anything_about_originals():
    """`original` costs a lookup per document, so only the single-document
    route answers it; a list says None rather than a wrong False."""
    user_id = await make_user()
    await _seed(user_id)

    async with _client_as(user_id) as client:
        listed = await client.get("/documents")

    assert listed.status_code == 200
    assert [d["original"] for d in listed.json()] == [None]


# The consultation audio is not hers to download, but it is what a retry needs.
# A failed transcription said "the original is still stored" with no end date
# while the DPIA deletes it 7 days later: the page now gives that date.


async def test_a_failed_consultation_says_until_when_its_audio_waits_for_a_retry():
    user_id = await make_user()
    doc_id = await _seed(
        user_id,
        name="consulta.webm",
        mime="audio/webm",
        body=b"visit-audio",
        source="consulta",
        expires_in=timedelta(days=7),
    )

    async with _client_as(user_id) as client:
        detail = (await client.get(f"/documents/{doc_id}")).json()

    assert detail["status"] == "failed"
    left = datetime.fromisoformat(detail["audio_until"]) - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23) < left <= timedelta(days=7)


async def test_no_date_once_the_audio_is_gone_nor_for_other_documents():
    user_id = await make_user()
    gone = await _seed(
        user_id, name="consulta.webm", mime="audio/webm", source="consulta", stored=False
    )
    pdf = await _seed(user_id)

    async with _client_as(user_id) as client:
        gone_detail = (await client.get(f"/documents/{gone}")).json()
        pdf_detail = (await client.get(f"/documents/{pdf}")).json()

    assert gone_detail["audio_until"] is None
    assert pdf_detail["audio_until"] is None
