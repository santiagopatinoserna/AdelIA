"""Her original files out of storage and back in, as one tar (offsite backup, 2026-11-24).

Inside the API container, which already holds the database and storage settings:

    /app/.venv/bin/python scripts/blob_archive.py export > blobs.tar
    /app/.venv/bin/python scripts/blob_archive.py verify < blobs.tar
    /app/.venv/bin/python scripts/blob_archive.py import [--bucket NAME --create-bucket] < blobs.tar

The offsite backup (scripts/adelia_backup.py at the repo root) runs `export` next to
its pg_dump. Before it the daily dump covered the rows and nothing copied the files:
one lost disk lost every PDF and photo a mother had sent.

`export` writes exactly the files GET /documents/{id}/file gives back (the rule of
routers/documents._original_is_kept): documents not erased, not a consultation, whose
blob is on no deletion clock. The consultation audio and the Telegram voice notes stay
out on purpose: the DPIA keeps them 48 h after their transcript (7 days if it failed),
and a backup kept 30 days would keep them longer than the privacy policy says.

Layout: one member `objects/<s3 key>` per file, with its sha256, content type and
document id in PAX headers, so `import` checks and stores each file as it streams by;
then `manifest.json`, last, listing every file and every key storage did not have
(`missing`). A file storage lost is listed, not fatal: one lost blob must not stop
the backup of all the others.

Only counts are printed, to stderr, never keys, names or content. stdout carries the
tar and nothing else. Exit codes: 0 done, 1 the archive does not match its manifest,
2 bad arguments.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import sys
import tarfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

# This checkout's package first: a worktree may share another checkout's venv.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FORMAT = 1
OBJECTS = "objects/"
MANIFEST = "manifest.json"
PAX_SHA256 = "ADELIA.sha256"
PAX_TYPE = "ADELIA.content_type"
PAX_DOCUMENT = "ADELIA.document_id"
MISMATCH = 1


class ArchiveMismatch(Exception):
    """The archive and its manifest disagree. The message holds counts, never keys."""


async def kept_originals(only_users: list[uuid.UUID] | None = None) -> list[tuple[str, str, str]]:
    """(s3_key, mime_type, document_id) of every original a mother can get back.

    One short session, closed before any blob is read: no pooled connection waits
    on storage (the pool exhaustion behind the 500s of the upload route).
    """
    import sqlalchemy as sa

    from adelia.db import AsyncSessionLocal
    from adelia.models import BlobTombstone, Document

    on_clock = sa.exists().where(BlobTombstone.s3_key == Document.s3_key)
    query = (
        sa.select(Document.s3_key, Document.mime_type, Document.id)
        .where(Document.deleted_at.is_(None), Document.source != "consulta", ~on_clock)
        .order_by(Document.created_at, Document.id)
    )
    if only_users:
        query = query.where(Document.user_id.in_(only_users))
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(query)).all()
    return [(key, mime, str(doc_id)) for key, mime, doc_id in rows]


def _member(name: str, data: bytes, pax: dict[str, str] | None = None) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o600
    info.mtime = int(time.time())
    if pax:
        info.pax_headers = pax
    return info


async def export(out: IO[bytes], *, only_users: list[uuid.UUID] | None = None,
                 storage: Any = None) -> dict[str, int]:
    from botocore.exceptions import ClientError

    from adelia.storage import S3Storage

    storage = storage or S3Storage()
    originals = await kept_originals(only_users)
    files: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    seen: set[str] = set()
    with tarfile.open(fileobj=out, mode="w|", format=tarfile.PAX_FORMAT) as tar:
        for key, mime, doc_id in originals:
            if key in seen:
                continue
            seen.add(key)
            try:
                body = await storage.get_object(key)
                data = await asyncio.to_thread(body.read)
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") not in ("NoSuchKey", "404"):
                    raise
                missing.append({"key": key, "document_id": doc_id})
                continue
            digest = hashlib.sha256(data).hexdigest()
            pax = {PAX_SHA256: digest, PAX_TYPE: mime, PAX_DOCUMENT: doc_id}
            tar.addfile(_member(OBJECTS + key, data, pax), io.BytesIO(data))
            files.append({"key": key, "document_id": doc_id, "content_type": mime,
                          "bytes": len(data), "sha256": digest})
        manifest = {"format": FORMAT, "created_at": datetime.now(timezone.utc).isoformat(),
                    "files": files, "missing": missing}
        raw = json.dumps(manifest, ensure_ascii=False, indent=1).encode()
        tar.addfile(_member(MANIFEST, raw), io.BytesIO(raw))
    return {"files": len(files), "missing": len(missing),
            "bytes": sum(f["bytes"] for f in files)}


def _read(inp: IO[bytes], on_file=None) -> dict[str, int]:
    """Walk the archive as a stream: check every file against its own sha256, then
    the whole set against the manifest. `on_file(key, data, content_type)` stores it."""
    seen: dict[str, tuple[int, str]] = {}
    manifest: dict[str, Any] | None = None
    with tarfile.open(fileobj=inp, mode="r|") as tar:
        for member in tar:
            handle = tar.extractfile(member) if member.isfile() else None
            if member.name == MANIFEST and handle is not None:
                manifest = json.loads(handle.read())
                continue
            if handle is None or not member.name.startswith(OBJECTS):
                raise ArchiveMismatch("a member that is not a file of the archive")
            data = handle.read()
            digest = hashlib.sha256(data).hexdigest()
            if digest != member.pax_headers.get(PAX_SHA256):
                raise ArchiveMismatch("a file does not match its own checksum")
            key = member.name[len(OBJECTS):]
            if on_file is not None:
                on_file(key, data, member.pax_headers.get(PAX_TYPE) or "application/octet-stream")
            seen[key] = (len(data), digest)
    if manifest is None:
        raise ArchiveMismatch("no manifest: the archive was cut short")
    listed = {f["key"]: (f["bytes"], f["sha256"]) for f in manifest["files"]}
    if listed != seen:
        differ = len(set(listed) ^ set(seen)) + sum(
            1 for k in set(listed) & set(seen) if listed[k] != seen[k])
        raise ArchiveMismatch(f"{differ} files differ from the manifest")
    return {"files": len(seen), "missing": len(manifest.get("missing", [])),
            "bytes": sum(size for size, _ in seen.values())}


def verify(inp: IO[bytes]) -> dict[str, int]:
    """Standard library only: the host script loads this file to check an archive
    without the app installed (scripts/adelia_backup.py)."""
    return _read(inp)


async def restore(inp: IO[bytes], *, storage: Any) -> dict[str, int]:
    """Put every file back under its own key. The tar is read in a worker thread and
    each file is stored before the next is read, so memory holds one file at a time.
    A mismatch found at the end leaves the files before it stored: rerun it."""
    loop = asyncio.get_running_loop()

    def on_file(key: str, data: bytes, content_type: str) -> None:
        put = storage.put_object(key, io.BytesIO(data), content_type=content_type)
        asyncio.run_coroutine_threadsafe(put, loop).result()

    return await asyncio.to_thread(_read, inp, on_file)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export", help="write the archive to stdout")
    exp.add_argument("--user", type=uuid.UUID, action="append", dest="users",
                     help="only this account's files (repeatable)")
    sub.add_parser("verify", help="check an archive read from stdin")
    imp = sub.add_parser("import", help="store the files of an archive read from stdin")
    imp.add_argument("--bucket", help="another bucket than the app's (a restore drill)")
    imp.add_argument("--create-bucket", action="store_true")
    return parser.parse_args(argv)


async def run(argv: list[str], *, stdin: IO[bytes] | None = None,
              stdout: IO[bytes] | None = None, stderr: IO[str] = sys.stderr) -> int:
    args = parse_args(argv)
    source = stdin if stdin is not None else sys.stdin.buffer
    sink = stdout if stdout is not None else sys.stdout.buffer
    try:
        if args.command == "export":
            report = await export(sink, only_users=args.users)
        elif args.command == "verify":
            report = verify(source)
        else:
            from adelia.storage import S3Storage

            storage = S3Storage(args.bucket)
            if args.create_bucket:
                await storage.ensure_bucket()
            report = await restore(source, storage=storage)
    except ArchiveMismatch as exc:
        print(f"blob archive {args.command}: {exc}", file=stderr)
        return MISMATCH
    if args.command == "export":
        sink.flush()
    print(f"blob archive {args.command}: {report['files']} files, {report['bytes']} bytes,"
          f" {report['missing']} missing", file=stderr)
    return 0


async def _main(argv: list[str]) -> int:
    from adelia.db import engine

    try:
        return await run(argv)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
