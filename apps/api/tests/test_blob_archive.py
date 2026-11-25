"""scripts/blob_archive.py: her original files out of storage and back (2026-11-24).

The offsite backup copies the database with pg_dump and the files with this
script. It must carry exactly what a mother can get back (the rule of
GET /documents/{id}/file), never the consultation audio the DPIA deletes after
48 h, survive a lost blob, refuse an archive that changed, and put every file
back byte for byte. PG and MinIO.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from adelia.models import BlobTombstone, Document
from adelia.routers.documents import _original_is_kept
from adelia.storage import S3Storage

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE

API_DIR = Path(__file__).parents[1]
sys.path.insert(0, str(API_DIR / "scripts"))
import blob_archive  # noqa: E402

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres and MinIO")

PDF = b"%PDF-1.4\n% informe\n" + bytes(range(256)) * 4
JPEG = b"\xff\xd8\xff" + bytes(range(255, -1, -1)) * 3


async def _doc(user_id, name, mime, *, body=None, source="web", deleted=False,
               expires_in=None) -> tuple[uuid.UUID, str]:
    from adelia.db import AsyncSessionLocal

    key = f"users/{user_id}/{uuid.uuid4()}-{name}"
    if body is not None:
        await S3Storage().put_object(key, io.BytesIO(body), content_type=mime)
    doc_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        session.add(Document(
            id=doc_id, user_id=user_id, source=source, mime_type=mime, s3_key=key,
            raw_text=None, processed_at=now, deleted_at=now if deleted else None,
        ))
        if expires_in is not None:
            session.add(BlobTombstone(s3_key=key, not_before=now + expires_in))
        await session.commit()
    return doc_id, key


async def _family() -> tuple[uuid.UUID, dict[str, tuple[uuid.UUID, str]]]:
    user_id = await make_user()
    docs = {
        "pdf": await _doc(user_id, "analitica.pdf", "application/pdf", body=PDF),
        "photo": await _doc(user_id, "cartilla.jpg", "image/jpeg", body=JPEG),
        "visit": await _doc(user_id, "consulta.webm", "audio/webm", body=b"visit",
                            source="consulta", expires_in=timedelta(hours=48)),
        "voice": await _doc(user_id, "diario.ogg", "audio/ogg", body=b"voice",
                            source="manual", expires_in=timedelta(days=7)),
        "erased": await _doc(user_id, "borrado.pdf", "application/pdf", body=PDF,
                             deleted=True),
        "lost": await _doc(user_id, "perdido.pdf", "application/pdf"),
    }
    return user_id, docs


def _manifest(archive: bytes) -> dict:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r") as tar:
        return json.loads(tar.extractfile(blob_archive.MANIFEST).read())


async def test_the_archive_carries_what_she_can_get_back_and_nothing_else():
    user_id, docs = await _family()
    out = io.BytesIO()

    report = await blob_archive.export(out, only_users=[user_id])

    manifest = _manifest(out.getvalue())
    assert {f["key"] for f in manifest["files"]} == {docs["pdf"][1], docs["photo"][1]}
    # Listed, not fatal: one lost blob must not stop the backup of the rest.
    assert [m["key"] for m in manifest["missing"]] == [docs["lost"][1]]
    assert report == {"files": 2, "missing": 1, "bytes": len(PDF) + len(JPEG)}


async def test_the_rule_is_the_one_get_file_uses():
    """What the backup keeps and what GET /documents/{id}/file serves must never
    drift apart: one says "your original is safe", the other proves it."""
    from adelia.db import AsyncSessionLocal

    user_id, docs = await _family()
    kept = {key for key, _, _ in await blob_archive.kept_originals([user_id])}

    async with AsyncSessionLocal() as db:
        for name, (doc_id, key) in docs.items():
            doc = await db.get(Document, doc_id)
            served = doc.deleted_at is None and await _original_is_kept(db, doc)
            assert (key in kept) == served, name


async def test_every_file_comes_back_byte_for_byte_into_another_bucket():
    user_id, docs = await _family()
    archive = io.BytesIO()
    await blob_archive.export(archive, only_users=[user_id])
    archive.seek(0)
    bucket = f"adelia-restore-test-{uuid.uuid4().hex[:12]}"
    target = S3Storage(bucket)
    await target.ensure_bucket()
    try:
        report = await blob_archive.restore(archive, storage=target)

        assert report["files"] == 2
        for name, expected, mime in (("pdf", PDF, "application/pdf"),
                                     ("photo", JPEG, "image/jpeg")):
            got = target._client.get_object(Bucket=bucket, Key=docs[name][1])
            assert got["Body"].read() == expected
            assert got["ContentType"] == mime
    finally:
        listed = target._client.list_objects_v2(Bucket=bucket).get("Contents", [])
        for obj in listed:
            target._client.delete_object(Bucket=bucket, Key=obj["Key"])
        target._client.delete_bucket(Bucket=bucket)


async def test_a_changed_byte_or_a_cut_archive_is_refused():
    user_id, _ = await _family()
    archive = io.BytesIO()
    await blob_archive.export(archive, only_users=[user_id])
    raw = archive.getvalue()

    flipped = bytearray(raw)
    at = raw.index(PDF[:40]) + 30
    flipped[at] ^= 0xFF
    with pytest.raises(blob_archive.ArchiveMismatch, match="checksum"):
        blob_archive.verify(io.BytesIO(bytes(flipped)))

    # Cut before the manifest: what a full disk or a killed process leaves.
    cut = raw[: raw.index(b"manifest.json") - 512]
    with pytest.raises((blob_archive.ArchiveMismatch, tarfile.ReadError)):
        blob_archive.verify(io.BytesIO(cut))

    assert blob_archive.verify(io.BytesIO(raw))["files"] == 2


async def test_the_command_line_keeps_stdout_a_clean_tar_and_prints_only_counts():
    """The backup pipes stdout straight into the encrypted bundle: one log line
    there would corrupt it. And stderr lands in the server journal: counts only."""
    user_id, docs = await _family()
    script = API_DIR / "scripts" / "blob_archive.py"
    env = {**os.environ, "PYTHONPATH": str(API_DIR)}

    exported = subprocess.run(
        [sys.executable, str(script), "export", "--user", str(user_id)],
        capture_output=True, env=env, timeout=60, check=True,
    )
    checked = subprocess.run(
        [sys.executable, str(script), "verify"],
        input=exported.stdout, capture_output=True, env=env, timeout=60,
    )

    assert _manifest(exported.stdout)["files"][0]["key"] == docs["pdf"][1]
    assert checked.returncode == 0
    for line in (exported.stderr + checked.stderr).decode().splitlines():
        assert "analitica" not in line and str(user_id) not in line, line
    assert b"2 files" in checked.stderr
