"""scripts/adelia_backup.py: the offsite backup to a private GitHub repo (2026-11-24).

Standard library on the server, so these tests talk to a fake GitHub served from
this process, never to the real one. What they hold the script to:

- a backup that failed half way leaves nothing published,
- an old backup goes, the newest never does, and other releases are never touched,
- the token never follows a download to the signed storage URL,
- what is downloaded is decrypted only after it matches its checksums, and what is
  decrypted matches the manifest it was sealed with.

The round trip through age needs the `age` binary and skips without it (CI).
"""
from __future__ import annotations

import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "adelia_backup", REPO_ROOT / "scripts" / "adelia_backup.py")
backup = importlib.util.module_from_spec(_spec)
sys.modules["adelia_backup"] = backup
_spec.loader.exec_module(backup)

sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "scripts"))
import blob_archive  # noqa: E402

REPO = "madre/backups"
TOKEN = "fake-token-for-tests"
needs_age = pytest.mark.skipif(shutil.which("age") is None, reason="needs the age binary")


class FakeGitHub:
    """The release endpoints the script calls, in memory. Pages of PAGE releases so
    pagination is exercised with a handful."""

    PAGE = 2

    def __init__(self) -> None:
        self.releases: list[dict] = []
        self.blobs: dict[int, bytes] = {}
        self.redirect_auth: list[str | None] = []
        self.fail_upload_named: str | None = None
        self.next_id = 1
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def add_release(self, tag: str, created_at: datetime, draft: bool = False) -> dict:
        rid = self._id()
        release = {
            "id": rid, "tag_name": tag, "draft": draft, "assets": [],
            "created_at": created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "upload_url": f"{self.base}/uploads/repos/{REPO}/releases/{rid}/assets{{?name,label}}",
        }
        self.releases.append(release)
        return release

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            def _send(self, status, payload=None, headers=None):
                raw = b"" if payload is None else json.dumps(payload).encode()
                self.send_response(status)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _authorized(self) -> bool:
                return self.headers.get("Authorization") == f"Bearer {TOKEN}"

            def do_GET(self):
                url = urlsplit(self.path)
                if url.path.startswith("/blob/"):
                    fake.redirect_auth.append(self.headers.get("Authorization"))
                    data = fake.blobs[int(url.path.rsplit("/", 1)[1])]
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if not self._authorized():
                    return self._send(401)
                if url.path == f"/repos/{REPO}/releases":
                    page = int(parse_qs(url.query).get("page", ["1"])[0])
                    items = fake.releases[(page - 1) * fake.PAGE: page * fake.PAGE]
                    link = {}
                    if page * fake.PAGE < len(fake.releases):
                        link = {"Link": f'<{fake.base}/repos/{REPO}/releases?per_page=100'
                                        f'&page={page + 1}>; rel="next"'}
                    return self._send(200, items, link)
                m = re.fullmatch(rf"/repos/{REPO}/releases/(\d+)/assets", url.path)
                if m:
                    rel = next(r for r in fake.releases if r["id"] == int(m.group(1)))
                    return self._send(200, rel["assets"])
                m = re.fullmatch(rf"/repos/{REPO}/releases/assets/(\d+)", url.path)
                if m:
                    return self._send(302, None, {"Location": f"{fake.base}/blob/{m.group(1)}"})
                return self._send(404)

            def do_POST(self):
                if not self._authorized():
                    return self._send(401)
                url = urlsplit(self.path)
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if url.path == f"/repos/{REPO}/releases":
                    data = json.loads(body)
                    rel = fake.add_release(data["tag_name"], datetime.now(timezone.utc),
                                           draft=data.get("draft", False))
                    return self._send(201, rel)
                m = re.fullmatch(rf"/uploads/repos/{REPO}/releases/(\d+)/assets", url.path)
                if m:
                    name = parse_qs(url.query)["name"][0]
                    if name == fake.fail_upload_named:
                        return self._send(502)
                    rel = next(r for r in fake.releases if r["id"] == int(m.group(1)))
                    aid = fake._id()
                    fake.blobs[aid] = body
                    asset = {"id": aid, "name": name, "size": len(body), "state": "uploaded",
                             "url": f"{fake.base}/repos/{REPO}/releases/assets/{aid}"}
                    rel["assets"].append(asset)
                    return self._send(201, asset)
                return self._send(404)

            def do_PATCH(self):
                m = re.fullmatch(rf"/repos/{REPO}/releases/(\d+)", urlsplit(self.path).path)
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                rel = next(r for r in fake.releases if r["id"] == int(m.group(1)))
                rel["draft"] = body["draft"]
                return self._send(200, rel)

            def do_DELETE(self):
                path = urlsplit(self.path).path
                m = re.fullmatch(rf"/repos/{REPO}/releases/(\d+)", path)
                if m:
                    fake.releases = [r for r in fake.releases if r["id"] != int(m.group(1))]
                return self._send(204)

        return Handler


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    """The operator's own settings (a shell where a drill just ran) must not leak in."""
    import os

    for name in list(os.environ):
        if name.startswith("ADELIA_BACKUP_") or name in ("GITHUB_TOKEN", "GH_TOKEN"):
            monkeypatch.delenv(name)


@pytest.fixture
def github():
    fake = FakeGitHub()
    yield fake
    fake.close()


def _client(fake: FakeGitHub) -> "backup.GitHub":
    return backup.GitHub(REPO, TOKEN, api=fake.base, timeout=10)


def test_the_token_never_follows_a_download_to_storage(github, tmp_path):
    client = _client(github)
    draft = client.create_draft("backup-1", "t", "n")
    part = tmp_path / "adelia.tar.age"
    part.write_bytes(b"ciphertext" * 1000)

    asset = client.upload(draft, part)
    client.download(asset, tmp_path / "back")

    assert (tmp_path / "back").read_bytes() == part.read_bytes()
    assert github.redirect_auth == [None]


def test_every_page_of_releases_is_read(github):
    for i in range(5):
        github.add_release(f"backup-{i}", datetime.now(timezone.utc))

    assert [r["tag_name"] for r in _client(github).releases()] == [
        f"backup-{i}" for i in range(5)]


def test_old_backups_go_the_newest_never_and_nothing_else_is_touched():
    now = datetime(2026, 12, 31, 12, tzinfo=timezone.utc)

    def rel(tag, days, draft=False):
        return {"id": tag, "tag_name": tag, "draft": draft,
                "created_at": (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")}

    releases = [rel("backup-old", 40), rel("backup-recent", 3), rel("backup-edge", 29.9),
                rel("v1.0", 400), rel("backup-killed-run", 1, draft=True),
                rel("backup-running", 0.01, draft=True)]
    expired = {r["tag_name"] for r in backup.select_expired(releases, "backup-", 30, now)}
    assert expired == {"backup-old", "backup-killed-run"}

    # A month without backups must not end with none: the newest stays, however old.
    alone = [rel("backup-last", 90), rel("backup-older", 120)]
    assert [r["tag_name"] for r in backup.select_expired(alone, "backup-", 30, now)] == [
        "backup-older"]


def test_a_file_is_split_under_the_limit_and_comes_back_whole(tmp_path):
    whole = bytes(range(256)) * 41
    sealed = tmp_path / "x.tar.age"
    sealed.write_bytes(whole)

    parts = backup.split_file(sealed, part_bytes=4096)

    assert [p.name for p in parts] == [f"x.tar.age.{i:03d}" for i in range(3)]
    assert all(p.stat().st_size <= 4096 for p in parts)
    assert b"".join(p.read_bytes() for p in parts) == whole


# ---------------------------------------------------------------- full round trip


def _blobs_tar(path: Path, files: dict[str, bytes]) -> None:
    import hashlib

    with tarfile.open(path, mode="w", format=tarfile.PAX_FORMAT) as tar:
        listed = []
        for key, data in files.items():
            digest = hashlib.sha256(data).hexdigest()
            tar.addfile(blob_archive._member(blob_archive.OBJECTS + key, data, {
                blob_archive.PAX_SHA256: digest, blob_archive.PAX_TYPE: "application/pdf"}),
                io.BytesIO(data))
            listed.append({"key": key, "bytes": len(data), "sha256": digest})
        raw = json.dumps({"format": 1, "files": listed, "missing": []}).encode()
        tar.addfile(blob_archive._member(blob_archive.MANIFEST, raw), io.BytesIO(raw))


@pytest.fixture
def configured(github, tmp_path, monkeypatch):
    identity = tmp_path / "identity.txt"
    if shutil.which("age-keygen"):
        subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
        public = subprocess.run(["age-keygen", "-y", str(identity)], check=True,
                                capture_output=True, text=True).stdout.strip()
        monkeypatch.setenv("ADELIA_BACKUP_RECIPIENT", public)
    monkeypatch.setenv("ADELIA_BACKUP_REPO", REPO)
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("ADELIA_BACKUP_GITHUB_API", github.base)
    monkeypatch.setenv("ADELIA_BACKUP_WORKDIR", str(tmp_path / "work"))
    return identity


DB = b"PGDMP" + bytes(range(256)) * 64
FILES = {"users/1/a-analitica.pdf": b"%PDF-1.4 uno", "users/1/b-cartilla.pdf": b"%PDF-1.4 dos"}


def _fake_dump(container, database, out):
    out.write_bytes(DB)


def _fake_blobs(cmd, out):
    _blobs_tar(out, FILES)
    return backup.verify_blobs(out)


@needs_age
def test_a_backup_comes_back_exactly_as_it_was_sealed(github, configured, tmp_path):
    tag = backup.run_backup(dump=_fake_dump, blobs=_fake_blobs, part_bytes=1500)

    published = [r for r in github.releases if not r["draft"]]
    assert [r["tag_name"] for r in published] == [tag]
    names = [a["name"] for a in published[0]["assets"]]
    assert names[-1] == "SHA256SUMS" and len(names) > 2  # split in parts
    # Ciphertext only: nothing of the dump or the files is readable on GitHub.
    assert not any(b"PDF" in github.blobs[a["id"]] or b"PGDMP" in github.blobs[a["id"]]
                   for a in published[0]["assets"])

    manifest = backup.fetch(_client(github), "backup-", None, tmp_path / "out", configured)

    assert manifest["tag"] == tag
    assert (tmp_path / "out" / "db.dump").read_bytes() == DB
    assert manifest["blobs"]["files"] == 2
    with tarfile.open(tmp_path / "out" / "blobs.tar") as tar:
        assert tar.extractfile("objects/users/1/a-analitica.pdf").read() == b"%PDF-1.4 uno"


@needs_age
def test_a_changed_byte_on_github_is_caught_before_decrypting(github, configured, tmp_path):
    backup.run_backup(dump=_fake_dump, blobs=_fake_blobs)
    asset = next(a for a in github.releases[0]["assets"] if a["name"] != "SHA256SUMS")
    tampered = bytearray(github.blobs[asset["id"]])
    tampered[100] ^= 0x01
    github.blobs[asset["id"]] = bytes(tampered)

    with pytest.raises(backup.BackupError, match="no coincide con SHA256SUMS"):
        backup.fetch(_client(github), "backup-", None, tmp_path / "out", configured)
    assert not (tmp_path / "out" / "db.dump").exists()


@needs_age
def test_a_failed_upload_leaves_nothing_published(github, configured, monkeypatch):
    github.fail_upload_named = "SHA256SUMS"
    monkeypatch.setattr(backup.time, "sleep", lambda s: None)

    with pytest.raises(backup.BackupError):
        backup.run_backup(dump=_fake_dump, blobs=_fake_blobs)

    assert github.releases == []


@needs_age
def test_a_dump_that_is_not_a_dump_stops_the_backup(github, configured):
    def broken(container, database, out):
        out.write_bytes(b"")
        raise backup.BackupError("pg_dump falló (1): connection refused")

    with pytest.raises(backup.BackupError, match="pg_dump"):
        backup.run_backup(dump=broken, blobs=_fake_blobs)
    assert github.releases == []


def test_check_says_when_the_newest_backup_is_too_old(github, configured, capsys):
    github.add_release("backup-a", datetime.now(timezone.utc) - timedelta(hours=40))
    assert backup.main(["check", "--max-age-hours", "30"]) == backup.FAILED
    assert "40 h" in capsys.readouterr().out

    github.add_release("backup-b", datetime.now(timezone.utc) - timedelta(hours=2))
    assert backup.main(["check", "--max-age-hours", "30"]) == 0


def test_missing_configuration_is_its_own_exit_code(monkeypatch, capsys):
    monkeypatch.delenv("ADELIA_BACKUP_REPO", raising=False)
    monkeypatch.setenv("ADELIA_BACKUP_RECIPIENT", "age1example")
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)

    assert backup.main(["backup"]) == backup.CONFIG
    err = capsys.readouterr().err
    assert "ADELIA_BACKUP_REPO" in err and TOKEN not in err
