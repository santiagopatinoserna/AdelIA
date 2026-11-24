#!/usr/bin/env python3
"""Offsite backups of AdelIA in a private GitHub repository, encrypted before they leave.

Santiago, 2026-11-24: "utiliza GitHub para eso". The prod compose dumps Postgres every
day into a volume of the same server, and nothing copied the files in MinIO: one lost
disk, a theft or a fire would take the data and its only copy together.

One backup is one release `backup-<UTC stamp>` of a PRIVATE repository, holding
`adelia-<stamp>.tar.age` (in parts when it nears GitHub's 2 GiB per file) and
`SHA256SUMS` of what was uploaded. Inside the encrypted tar: `manifest.json`
(checksums), `db.dump` (pg_dump --format=custom of the whole database) and
`blobs.tar` (apps/api/scripts/blob_archive.py: every original a mother can get back,
never the consultation audio the DPIA deletes after 48 h).

It is encrypted with age to a public key on the server: the server cannot read its own
backups and GitHub only ever holds ciphertext. The private key stays with Santiago (his
Mac and his password manager). Losing it loses every backup.

    backup  daily on the server (infra/backup/adelia-backup.timer): dump, encrypt,
            upload, publish, then delete backups older than ADELIA_BACKUP_KEEP_DAYS
            (never the newest). A failed run deletes its own draft: nothing half done
            is ever published.
    list    the backups on GitHub
    fetch   download one (default the newest), check every checksum, decrypt it
    drill   fetch the newest and restore it into a scratch database, then check that
            every original the database references is in the backup: the proof
    check   exit 1 when the newest backup is older than --max-age-hours (the monitor)

Configuration, from the environment (/etc/adelia-backup.env on the server):
    ADELIA_BACKUP_REPO          owner/name of the private repository (required)
    ADELIA_BACKUP_RECIPIENT     age public key(s), comma separated (backup)
    GITHUB_TOKEN                fine-grained token with Contents read and write on that
                                repository only. Unset, `gh auth token` is asked (a Mac
                                where gh is logged in). Never printed.
    ADELIA_BACKUP_IDENTITY      age private key file (fetch, drill), default
                                ~/.config/adelia-backup/age-identity.txt
    ADELIA_BACKUP_KEEP_DAYS     default 30, what the privacy policy promises
    ADELIA_BACKUP_PG_CONTAINER  default infra-postgres-1
    ADELIA_BACKUP_PG_DB         default the container's own POSTGRES_DB
    ADELIA_BACKUP_BLOB_CMD      default "docker exec -i infra-api-1
                                /app/.venv/bin/python scripts/blob_archive.py"
    ADELIA_BACKUP_WORKDIR       default /var/tmp/adelia-backup (three times the backup
                                size free while it runs)
    ADELIA_BACKUP_TAG_PREFIX    default backup-

Standard library, docker and age only: it runs on the server's own python3.
Exit codes: 0 done, 1 failed, 2 configuration missing or GitHub unreachable for `check`.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BLOB_ARCHIVE = REPO_ROOT / "apps" / "api" / "scripts" / "blob_archive.py"
API = "https://api.github.com"
# GitHub refuses a release file of 2 GiB or more; parts stay well under it.
PART_BYTES = 1900 * 1024 * 1024
# A draft older than this is what a killed run left behind.
DRAFT_GRACE = timedelta(hours=6)
BUNDLE = ("manifest.json", "db.dump", "blobs.tar")
SUMS = "SHA256SUMS"
FORMAT = 1
CHUNK = 1024 * 1024
FAILED, CONFIG = 1, 2
UA = "adelia-backup"


class BackupError(Exception):
    """A step failed. The message is safe to print: no token, no content."""


class ConfigError(BackupError):
    """Something the operator has to set up first."""


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or default


def _require(name: str) -> str:
    value = _env(name)
    if not value:
        raise ConfigError(f"falta {name} (ver docs/BACKUPS.md)")
    return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(stamp: str) -> datetime:
    # Python 3.10, the server's, does not read the trailing Z GitHub sends.
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def github_token() -> str:
    token = _env("GITHUB_TOKEN") or _env("GH_TOKEN")
    if token:
        return token
    if shutil.which("gh"):
        got = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=30)
        if got.returncode == 0 and got.stdout.strip():
            return got.stdout.strip()
    raise ConfigError("falta GITHUB_TOKEN, y gh no tiene sesión en esta máquina")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _next_link(link: str) -> str | None:
    for part in link.split(","):
        url, _, rel = part.partition(";")
        if 'rel="next"' in rel:
            return url.strip().strip("<>")
    return None


class GitHub:
    """The few REST calls a backup needs. The token goes in one header and nowhere
    else: an asset download is redirected to a signed storage URL, which must get no
    Authorization header (storage refuses two credentials, and must not see it)."""

    def __init__(self, repo: str, token: str, api: str = API, timeout: float = 600) -> None:
        self.repo = repo
        self.api = api.rstrip("/")
        self.timeout = timeout
        self._token = token

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": UA,
        }
        headers.update(extra or {})
        return headers

    def _call(self, method: str, url: str, *, data: Any = None, length: int | None = None,
              headers: dict[str, str] | None = None,
              expect: tuple[int, ...] = (200, 201, 204)) -> tuple[Any, str]:
        if not url.startswith("http"):
            url = f"{self.api}{url}"
        extra = dict(headers or {})
        body = data
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode()
            extra["Content-Type"] = "application/json"
        if length is not None:
            extra["Content-Length"] = str(length)
        where = urllib.parse.urlsplit(url).path
        # A file being uploaded cannot be sent twice from here: upload() retries it.
        attempts = 1 if hasattr(body, "read") else 3
        for attempt in range(attempts):
            request = urllib.request.Request(url, data=body, method=method,
                                             headers=self._headers(extra))
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    raw, status, link = resp.read(), resp.status, resp.headers.get("Link", "")
            except urllib.error.HTTPError as exc:
                if exc.code in expect:
                    return None, ""
                if exc.code >= 500 and attempt + 1 < attempts:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise BackupError(f"GitHub {method} {where}: HTTP {exc.code}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt + 1 < attempts:
                    time.sleep(3 * (attempt + 1))
                    continue
                reason = getattr(exc, "reason", exc)
                raise BackupError(f"GitHub {method} {where}: {reason}") from None
            if status not in expect:
                raise BackupError(f"GitHub {method} {where}: HTTP {status}")
            return (json.loads(raw) if raw else None), link
        raise BackupError(f"GitHub {method} {where}: sin respuesta")

    def create_draft(self, tag: str, title: str, notes: str) -> dict[str, Any]:
        release, _ = self._call("POST", f"/repos/{self.repo}/releases", data={
            "tag_name": tag, "name": title, "body": notes, "draft": True})
        return release

    def assets(self, release_id: int) -> list[dict[str, Any]]:
        items, _ = self._call("GET", f"/repos/{self.repo}/releases/{release_id}/assets?per_page=100")
        return items or []

    def upload(self, release: dict[str, Any], path: Path) -> dict[str, Any]:
        base = release["upload_url"].split("{", 1)[0]
        url = f"{base}?name={urllib.parse.quote(path.name)}"
        size = path.stat().st_size
        for attempt in range(3):
            try:
                with path.open("rb") as handle:
                    asset, _ = self._call(
                        "POST", url, data=handle, length=size, expect=(201,),
                        headers={"Content-Type": "application/octet-stream"})
                return asset
            except BackupError:
                if attempt == 2:
                    raise
                # A half-uploaded asset keeps its name: it goes before the next try.
                for asset in self.assets(release["id"]):
                    if asset["name"] == path.name:
                        self._call("DELETE", f"/repos/{self.repo}/releases/assets/{asset['id']}",
                                   expect=(204, 404))
                time.sleep(10 * (attempt + 1))
        raise BackupError("unreachable")

    def publish(self, release_id: int) -> None:
        self._call("PATCH", f"/repos/{self.repo}/releases/{release_id}",
                   data={"draft": False, "make_latest": "true"})

    def releases(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        url: str | None = f"/repos/{self.repo}/releases?per_page=100"
        while url:
            page, link = self._call("GET", url)
            found.extend(page or [])
            url = _next_link(link)
        return found

    def delete(self, release: dict[str, Any]) -> None:
        self._call("DELETE", f"/repos/{self.repo}/releases/{release['id']}", expect=(204, 404))
        # A published release leaves its tag behind; a draft never made one.
        tag = urllib.parse.quote(release["tag_name"], safe="")
        self._call("DELETE", f"/repos/{self.repo}/git/refs/tags/{tag}", expect=(204, 404, 422))

    def download(self, asset: dict[str, Any], dest: Path) -> None:
        request = urllib.request.Request(asset["url"], headers=self._headers(
            {"Accept": "application/octet-stream"}))
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            resp = opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                raise BackupError(f"GitHub GET {asset['name']}: HTTP {exc.code}") from None
            location = exc.headers["Location"]
            resp = urllib.request.urlopen(
                urllib.request.Request(location, headers={"User-Agent": UA}),
                timeout=self.timeout)
        with resp, dest.open("wb") as out:
            shutil.copyfileobj(resp, out, CHUNK)


def select_expired(releases: list[dict[str, Any]], prefix: str, keep_days: int,
                   now: datetime) -> list[dict[str, Any]]:
    """Published backups older than keep_days, except the newest whatever its age
    (a month without backups must not end with none), and drafts a killed run left.
    Releases whose tag lacks the prefix are never touched."""
    mine = [r for r in releases if str(r.get("tag_name", "")).startswith(prefix)]
    published = sorted((r for r in mine if not r.get("draft")),
                       key=lambda r: _parse_time(r["created_at"]), reverse=True)
    cutoff = now - timedelta(days=keep_days)
    expired = [r for r in published[1:] if _parse_time(r["created_at"]) < cutoff]
    drafts = [r for r in mine if r.get("draft")
              and _parse_time(r["created_at"]) < now - DRAFT_GRACE]
    return expired + drafts


def newest(releases: list[dict[str, Any]], prefix: str) -> dict[str, Any] | None:
    published = [r for r in releases
                 if str(r.get("tag_name", "")).startswith(prefix) and not r.get("draft")]
    return max(published, key=lambda r: _parse_time(r["created_at"]), default=None)


def split_file(path: Path, part_bytes: int = PART_BYTES) -> list[Path]:
    if path.stat().st_size <= part_bytes:
        return [path]
    parts: list[Path] = []
    with path.open("rb") as src:
        while True:
            part = path.with_name(f"{path.name}.{len(parts):03d}")
            written = 0
            with part.open("wb") as dst:
                while written < part_bytes:
                    block = src.read(min(CHUNK, part_bytes - written))
                    if not block:
                        break
                    dst.write(block)
                    written += len(block)
            if written == 0:
                part.unlink()
                break
            parts.append(part)
    path.unlink()
    return parts


def parse_sums(text: str) -> list[tuple[str, str]]:
    lines = [line.split(None, 1) for line in text.splitlines() if line.strip()]
    return [(digest, name.strip().lstrip("*")) for digest, name in lines]


def load_blob_archive() -> Any:
    spec = importlib.util.spec_from_file_location("blob_archive", BLOB_ARCHIVE)
    if spec is None or spec.loader is None:
        raise ConfigError(f"no encuentro {BLOB_ARCHIVE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tail(raw: bytes) -> str:
    lines = raw.decode(errors="replace").strip().splitlines()
    return lines[-1][:300] if lines else "sin mensaje"


def _pg(container: str, command: str, *, stdin: Any = None, stdout: Any = None,
        timeout: int = 3600) -> subprocess.CompletedProcess:
    """`command` in the Postgres container, as its own superuser (POSTGRES_USER)."""
    interactive = ["-i"] if stdin is not None else []
    return subprocess.run(["docker", "exec", *interactive, container, "sh", "-c", command],
                          stdin=stdin if stdin is not None else subprocess.DEVNULL,
                          stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout)


def dump_database(container: str, database: str | None, out: Path) -> None:
    target = shlex.quote(database) if database else '"$POSTGRES_DB"'
    with out.open("wb") as handle:
        done = _pg(container, f'exec pg_dump -U "$POSTGRES_USER" -d {target}'
                              " --format=custom --compress=6", stdout=handle)
    if done.returncode != 0:
        raise BackupError(f"pg_dump falló ({done.returncode}): {_tail(done.stderr)}")
    with out.open("rb") as handle:
        if handle.read(5) != b"PGDMP":
            raise BackupError("pg_dump no escribió un volcado")


def export_blobs(blob_cmd: str, out: Path) -> dict[str, int]:
    with out.open("wb") as handle:
        done = subprocess.run([*shlex.split(blob_cmd), "export"], stdin=subprocess.DEVNULL,
                              stdout=handle, stderr=subprocess.PIPE, timeout=6 * 3600)
    if done.returncode != 0:
        raise BackupError(f"la exportación de archivos falló ({done.returncode}):"
                          f" {_tail(done.stderr)}")
    return verify_blobs(out)


def verify_blobs(path: Path) -> dict[str, int]:
    archive = load_blob_archive()
    try:
        with path.open("rb") as handle:
            return archive.verify(handle)
    except (archive.ArchiveMismatch, tarfile.TarError) as exc:
        raise BackupError(f"blobs.tar no cuadra: {exc}") from None


def encrypt(files: list[tuple[str, Path]], recipients: list[str], out: Path) -> None:
    """tar | age, streamed: the clear bundle never exists on disk as one file."""
    command = ["age", "--encrypt", "-o", str(out)]
    for recipient in recipients:
        command += ["-r", recipient]
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise ConfigError("falta age (apt install age / brew install age)") from None
    assert proc.stdin is not None and proc.stderr is not None
    try:
        with tarfile.open(fileobj=proc.stdin, mode="w|") as tar:
            for name, path in files:
                tar.add(str(path), arcname=name, recursive=False)
    except BrokenPipeError:
        pass  # age stopped reading: its exit code and message say why
    finally:
        with contextlib.suppress(BrokenPipeError):
            proc.stdin.close()
    error = proc.stderr.read()
    if proc.wait() != 0:
        raise BackupError(f"age falló: {_tail(error)}")


def decrypt(sources: list[Path], identity: Path, out: Path) -> None:
    if not identity.is_file():
        raise ConfigError(f"no encuentro la clave privada {identity}")
    joined = sources[0]
    if len(sources) > 1:
        joined = out.with_suffix(".age")
        with joined.open("wb") as dst:
            for part in sources:
                with part.open("rb") as src:
                    shutil.copyfileobj(src, dst, CHUNK)
    try:
        done = subprocess.run(["age", "--decrypt", "-i", str(identity), "-o", str(out),
                               str(joined)], capture_output=True, timeout=6 * 3600)
    except FileNotFoundError:
        raise ConfigError("falta age (brew install age)") from None
    if done.returncode != 0:
        raise BackupError(f"no se pudo descifrar: {_tail(done.stderr)}")


def _recipients() -> list[str]:
    raw = _require("ADELIA_BACKUP_RECIPIENT")
    keys = [k.strip() for k in raw.replace(",", " ").split() if k.strip()]
    bad = [k for k in keys if not k.startswith(("age1", "ssh-"))]
    if bad or not keys:
        raise ConfigError("ADELIA_BACKUP_RECIPIENT no parece una clave pública de age (age1...)")
    return keys


def _github() -> GitHub:
    return GitHub(_require("ADELIA_BACKUP_REPO"), github_token(),
                  api=_env("ADELIA_BACKUP_GITHUB_API", API) or API)


def _prefix() -> str:
    return _env("ADELIA_BACKUP_TAG_PREFIX", "backup-") or "backup-"


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


def run_backup(*, dump: Any = dump_database, blobs: Any = export_blobs,
               part_bytes: int = PART_BYTES) -> str:
    """One backup, end to end. Returns the published tag; raises BackupError."""
    recipients = _recipients()
    github = _github()
    prefix = _prefix()
    keep_days = int(_env("ADELIA_BACKUP_KEEP_DAYS", "30") or 30)
    container = _env("ADELIA_BACKUP_PG_CONTAINER", "infra-postgres-1") or "infra-postgres-1"
    blob_cmd = _env("ADELIA_BACKUP_BLOB_CMD") or (
        "docker exec -i infra-api-1 /app/.venv/bin/python scripts/blob_archive.py")
    workdir = Path(_env("ADELIA_BACKUP_WORKDIR", "/var/tmp/adelia-backup") or "")
    workdir.mkdir(parents=True, exist_ok=True)
    os.chmod(workdir, 0o700)

    stamp = _now().strftime("%Y%m%d-%H%M%S")
    tag = f"{prefix}{stamp}"
    scratch = Path(tempfile.mkdtemp(prefix=f"{stamp}-", dir=workdir))
    draft: dict[str, Any] | None = None
    try:
        db, archive = scratch / "db.dump", scratch / "blobs.tar"
        # The database first: every row it holds existed before the files are read,
        # so each original it references is already in storage when they are.
        dump(container, _env("ADELIA_BACKUP_PG_DB"), db)
        counts = blobs(blob_cmd, archive)
        manifest = {
            "format": FORMAT,
            "created_at": _now().isoformat(),
            "db": {"file": "db.dump", "bytes": db.stat().st_size, "sha256": sha256_file(db)},
            "blobs": {"file": "blobs.tar", "bytes": archive.stat().st_size,
                      "sha256": sha256_file(archive), **counts},
        }
        listing = scratch / "manifest.json"
        listing.write_text(json.dumps(manifest, indent=1))
        sealed = scratch / f"adelia-{stamp}.tar.age"
        encrypt([("manifest.json", listing), ("db.dump", db), ("blobs.tar", archive)],
                recipients, sealed)
        db.unlink()
        archive.unlink()
        parts = split_file(sealed, part_bytes)
        sums = scratch / SUMS
        sums.write_text("".join(f"{sha256_file(p)}  {p.name}\n" for p in parts))
        total = sum(p.stat().st_size for p in parts)

        notes = (f"Copia cifrada (age) de AdelIA, {stamp} UTC. {len(parts)} parte(s),"
                 f" {_mb(total)}. Cómo se descifra y se restaura: docs/BACKUPS.md.")
        draft = github.create_draft(tag, f"AdelIA {stamp}", notes)
        for path in [*parts, sums]:
            github.upload(draft, path)
        stored = {a["name"]: a for a in github.assets(draft["id"])}
        for path in [*parts, sums]:
            asset = stored.get(path.name)
            if (asset is None or asset.get("state") != "uploaded"
                    or asset.get("size") != path.stat().st_size):
                raise BackupError(f"GitHub no tiene entera la parte {path.name}")
        github.publish(draft["id"])
        draft = None

        expired = select_expired(github.releases(), prefix, keep_days, _now())
        for release in expired:
            github.delete(release)
        print(f"copia {tag}: {len(parts)} parte(s), {_mb(total)}; archivos {counts['files']}"
              f" ({counts['missing']} ausentes en el almacenamiento); {len(expired)}"
              " copia(s) caducada(s) borrada(s)")
        (workdir / "last-success").write_text(f"{tag}\n")
        return tag
    finally:
        if draft is not None:
            with contextlib.suppress(BackupError):
                github.delete(draft)
        shutil.rmtree(scratch, ignore_errors=True)


def fetch(github: GitHub, prefix: str, tag: str | None, out: Path,
          identity: Path) -> dict[str, Any]:
    """Download, check every checksum, decrypt and unpack into `out`. Returns the
    manifest. Nothing is decrypted before the downloaded parts match SHA256SUMS."""
    releases = github.releases()
    if tag:
        release = next((r for r in releases if r.get("tag_name") == tag), None)
    else:
        release = newest(releases, prefix)
    if release is None:
        raise BackupError("no hay ninguna copia que bajar")
    assets = {a["name"]: a for a in release.get("assets") or github.assets(release["id"])}
    if SUMS not in assets:
        raise BackupError(f"{release['tag_name']} no tiene {SUMS}")
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="fetch-", dir=out))
    try:
        github.download(assets[SUMS], work / SUMS)
        expected = parse_sums((work / SUMS).read_text())
        parts = []
        for digest, name in expected:
            if name not in assets:
                raise BackupError(f"falta la parte {name} en GitHub")
            github.download(assets[name], work / name)
            if sha256_file(work / name) != digest:
                raise BackupError(f"la parte {name} no coincide con {SUMS}")
            parts.append(work / name)
        bundle = work / "bundle.tar"
        decrypt(parts, identity, bundle)
        with tarfile.open(bundle, mode="r") as tar:
            for member in tar:
                if member.name not in BUNDLE or not member.isfile():
                    raise BackupError("la copia trae algo que no es suyo")
                source = tar.extractfile(member)
                assert source is not None
                with source, (out / member.name).open("wb") as dst:
                    shutil.copyfileobj(source, dst, CHUNK)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    manifest = json.loads((out / "manifest.json").read_text())
    for part in ("db", "blobs"):
        entry = manifest[part]
        if sha256_file(out / entry["file"]) != entry["sha256"]:
            raise BackupError(f"{entry['file']} no coincide con el manifiesto")
    verify_blobs(out / "blobs.tar")
    manifest["tag"] = release["tag_name"]
    return manifest


def _psql(container: str, database: str, sql: str) -> list[str]:
    done = _pg(container, f'exec psql -U "$POSTGRES_USER" -d {shlex.quote(database)}'
                          f" -v ON_ERROR_STOP=1 -At -c {shlex.quote(sql)}", timeout=600)
    if done.returncode != 0:
        raise BackupError(f"psql falló: {_tail(done.stderr)}")
    return [line for line in (done.stdout or b"").decode().splitlines() if line]


KEPT_ORIGINALS_SQL = (
    "select d.s3_key from documents d where d.deleted_at is null and d.source <> 'consulta'"
    " and not exists (select 1 from blob_tombstones t where t.s3_key = d.s3_key)"
)


def drill(github: GitHub, prefix: str, identity: Path, container: str,
          tag: str | None = None) -> dict[str, Any]:
    """Restore the newest backup into a scratch database and prove it is whole: the
    dump restores without one error, and every original the restored database
    references is in the archive (or was already lost when the backup ran, listed)."""
    scratch_dir = Path(tempfile.mkdtemp(prefix="adelia-drill-"))
    scratch_db = f"adelia_restore_drill_{_now().strftime('%Y%m%d%H%M%S')}"
    try:
        manifest = fetch(github, prefix, tag, scratch_dir / "backup", identity)
        created = _pg(container, f'exec createdb -U "$POSTGRES_USER" {scratch_db}')
        if created.returncode != 0:
            raise BackupError(f"createdb falló: {_tail(created.stderr)}")
        try:
            with (scratch_dir / "backup" / "db.dump").open("rb") as dump:
                restored = _pg(container, f'exec pg_restore -U "$POSTGRES_USER" -d {scratch_db}'
                                          " --no-owner --no-privileges --exit-on-error",
                               stdin=dump)
            if restored.returncode != 0:
                raise BackupError(f"pg_restore falló: {_tail(restored.stderr)}")
            version = _psql(container, scratch_db, "select version_num from alembic_version")
            counts = dict(zip(("users", "profiles", "documents"), _psql(
                container, scratch_db,
                "select (select count(*) from users), (select count(*) from profiles),"
                " (select count(*) from documents)")[0].split("|")))
            referenced = set(_psql(container, scratch_db, KEPT_ORIGINALS_SQL))
        finally:
            _pg(container, f'exec dropdb -U "$POSTGRES_USER" --if-exists {scratch_db}')
        with tarfile.open(scratch_dir / "backup" / "blobs.tar", mode="r") as tar:
            handle = tar.extractfile("manifest.json")
            assert handle is not None
            inner = json.loads(handle.read())
        archived = {f["key"] for f in inner["files"]}
        lost = {m["key"] for m in inner["missing"]}
        absent = referenced - archived - lost
        if absent:
            raise BackupError(f"{len(absent)} originales de la base no están en la copia")
        return {"tag": manifest["tag"], "alembic": version[0] if version else None,
                **counts, "originals": len(referenced & archived),
                "lost_before_backup": len(referenced & lost)}
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


def _identity() -> Path:
    default = Path.home() / ".config" / "adelia-backup" / "age-identity.txt"
    return Path(_env("ADELIA_BACKUP_IDENTITY", str(default)) or default).expanduser()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup", help="una copia: volcar, cifrar, subir, publicar, podar")
    sub.add_parser("list", help="las copias que hay en GitHub")
    get = sub.add_parser("fetch", help="bajar, comprobar y descifrar una copia")
    get.add_argument("--tag", help="por defecto la más reciente")
    get.add_argument("--out", required=True, type=Path)
    practice = sub.add_parser("drill", help="restaurar la última en una base temporal")
    practice.add_argument("--tag")
    practice.add_argument("--pg-container", default=None)
    fresh = sub.add_parser("check", help="¿la última copia es reciente?")
    fresh.add_argument("--max-age-hours", type=float, default=30)
    args = parser.parse_args(argv)

    try:
        if args.command == "backup":
            run_backup()
        elif args.command == "list":
            for release in sorted(_github().releases(), key=lambda r: r["created_at"]):
                size = sum(a.get("size", 0) for a in release.get("assets", []))
                state = "borrador" if release.get("draft") else "publicada"
                print(f"{release['tag_name']}  {release['created_at']}  {_mb(size)}  {state}")
        elif args.command == "fetch":
            manifest = fetch(_github(), _prefix(), args.tag, args.out, _identity())
            print(f"{manifest['tag']} descifrada en {args.out}: db.dump, blobs.tar"
                  f" ({manifest['blobs']['files']} archivos), manifest.json")
        elif args.command == "drill":
            container = args.pg_container or _env(
                "ADELIA_BACKUP_PG_CONTAINER", "infra-postgres-1") or "infra-postgres-1"
            report = drill(_github(), _prefix(), _identity(), container, args.tag)
            print(f"simulacro OK: {report['tag']} se restaura entera (alembic"
                  f" {report['alembic']}; {report['users']} cuentas, {report['documents']}"
                  f" documentos, {report['originals']} originales presentes,"
                  f" {report['lost_before_backup']} ya perdidos antes de la copia)")
        else:
            try:
                last = newest(_github().releases(), _prefix())
            except ConfigError:
                raise
            except BackupError as exc:
                print(f"no se pudo comprobar: {exc}", file=sys.stderr)
                return CONFIG
            if last is None:
                print("no hay ninguna copia en GitHub")
                return FAILED
            hours = (_now() - _parse_time(last["created_at"])).total_seconds() / 3600
            if hours > args.max_age_hours:
                print(f"la última copia ({last['tag_name']}) tiene {hours:.0f} h")
                return FAILED
            print(f"ok: {last['tag_name']}, hace {hours:.0f} h")
    except ConfigError as exc:
        print(f"configuración: {exc}", file=sys.stderr)
        return CONFIG
    except (BackupError, OSError, subprocess.SubprocessError) as exc:
        print(f"{args.command} falló: {exc}", file=sys.stderr)
        return FAILED
    return 0


if __name__ == "__main__":
    sys.exit(main())
