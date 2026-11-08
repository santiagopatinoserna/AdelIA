"""scripts/erase_user.py: erase a leftover test guest by id (2026-11-08).

Smoke runs and other agents' tests leave guests whose session is gone, so
DELETE /users/me can no longer reach them. The script erases one by the same
path that endpoint takes (services/account_erasure, then the blob sweep), is a
dry run unless told --yes, prints counts and never content, and refuses any
account that is not a guest, with no flag to force it.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from jose import jwt

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import (
    BlobTombstone, ChatMessage, ChatSession, Chunk, Document, Entity, Observation, Profile, User,
)
from adelia.services import account_erasure

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE

API_DIR = Path(__file__).parents[1]
sys.path.insert(0, str(API_DIR / "scripts"))
import erase_user  # noqa: E402

pg_only = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

RED_FLAG = "Mi bebé ha convulsionado y no reacciona"
OWNED = (Document, Chunk, Entity, Observation, ChatSession, ChatMessage, Profile)


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")


def _bearer(user_id) -> dict[str, str]:
    from datetime import datetime, timedelta, timezone

    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "test-secret", algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


async def _new_guest(client) -> uuid.UUID:
    with patch("adelia.services.guest.fill_seed_embeddings", return_value=0):
        resp = await client.post("/guest", json={"locale": "es"})
    assert resp.status_code == 201, resp.text
    guest = uuid.UUID(resp.json()["user_id"])
    # Her conversation too, so the erasure reaches more than the seed.
    await client.post("/agent/turn", headers=_bearer(guest), json={"message": RED_FLAG})
    return guest


async def _snapshot(user_id: uuid.UUID) -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        out = {"users": int(await session.scalar(
            sa.select(sa.func.count()).select_from(User).where(User.id == user_id)))}
        for model in OWNED:
            out[model.__tablename__] = int(await session.scalar(
                sa.select(sa.func.count()).select_from(model).where(model.user_id == user_id)))
    return out


async def _keys(user_id: uuid.UUID) -> list[str]:
    async with AsyncSessionLocal() as session:
        return list((await session.execute(
            sa.select(Document.s3_key).where(Document.user_id == user_id))).scalars())


async def _run(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    code = await erase_user.run(list(argv), out=out)
    return code, out.getvalue()


async def _drop(*user_ids: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(sa.delete(User).where(User.id.in_(user_ids)))
        await session.commit()


@pg_only
async def test_a_dry_run_counts_rows_per_table_and_changes_nothing(client):
    guest = await _new_guest(client)
    try:
        before = await _snapshot(guest)
        code, printed = await _run("--id", str(guest))

        assert code == 0
        assert await _snapshot(guest) == before
        assert "dry run" in printed.lower()
        assert "--yes" in printed
        for table in ("users", "documents", "profiles", "chat_messages"):
            assert table in printed
        # Counts only: not a word of her record, not even her baby's name.
        assert "Lucía" not in printed
        async with AsyncSessionLocal() as session:
            texts = (await session.execute(
                sa.select(Document.raw_text).where(Document.user_id == guest))).scalars()
            for text in texts:
                assert not text or text[:40] not in printed
    finally:
        await _drop(guest)


@pg_only
async def test_yes_erases_everything_of_that_guest_and_nothing_of_another(client):
    guest, other = await _new_guest(client), await _new_guest(client)
    try:
        other_before = await _snapshot(other)
        keys = await _keys(guest)
        assert keys

        code, printed = await _run("--id", str(guest), "--yes")

        assert code == 0, printed
        assert all(n == 0 for n in (await _snapshot(guest)).values())
        assert await _snapshot(other) == other_before
        # The blob sweep ran for her keys and only hers.
        async with AsyncSessionLocal() as session:
            left = await session.scalar(sa.select(sa.func.count()).select_from(BlobTombstone)
                                        .where(BlobTombstone.s3_key.in_(keys)))
        assert left == 0
        assert await _keys(other)
    finally:
        await _drop(guest, other)


@pg_only
async def test_a_regular_account_is_refused_even_with_yes():
    account = await make_user()
    try:
        before = await _snapshot(account)
        code, printed = await _run("--id", str(account), "--yes")

        assert code != 0
        assert "not a guest" in printed.lower()
        assert await _snapshot(account) == before
    finally:
        await _drop(account)


def test_there_is_no_flag_to_force_a_regular_account():
    for flag in ("--force", "--any", "--include-accounts"):
        with pytest.raises(SystemExit) as refused:
            erase_user.parse_args(["--id", str(uuid.uuid4()), "--yes", flag])
        assert refused.value.code == 2


@pg_only
async def test_an_unknown_id_is_a_plain_message_not_a_traceback():
    code, printed = await _run("--id", str(uuid.uuid4()), "--yes")

    assert code == 1
    assert "no account" in printed.lower()
    assert "Traceback" not in printed


@pg_only
async def test_the_script_and_delete_users_me_take_the_same_path(client):
    """One erasure, two doors: the endpoint and the script both go through
    services/account_erasure, so a fix to one is a fix to the other."""
    calls: list[uuid.UUID] = []
    real = account_erasure.erase_account

    async def _spy(db, user_id):
        calls.append(user_id)
        return await real(db, user_id)

    first, second = await _new_guest(client), await _new_guest(client)
    try:
        with patch.object(account_erasure, "erase_account", _spy), \
                patch("adelia.routers.users._spawn_erasure_sweep"):
            assert (await client.delete("/users/me", headers=_bearer(first))).status_code == 204
            code, _ = await _run("--id", str(second), "--yes")
        assert code == 0
        assert calls == [first, second]
    finally:
        await _drop(first, second)


@pg_only
def test_it_runs_as_a_plain_script_like_inside_the_container():
    """`/app/.venv/bin/python scripts/erase_user.py --id ...` in production:
    no PYTHONPATH. The script puts its own checkout first, so a worktree
    sharing another checkout's virtualenv still runs its own code."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    done = subprocess.run(
        [sys.executable, "scripts/erase_user.py", "--id", str(uuid.uuid4())],
        cwd=API_DIR, env=env, capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 1, done.stderr
    assert "no account" in done.stdout.lower()
    assert "Traceback" not in done.stderr
