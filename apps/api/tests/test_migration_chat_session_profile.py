"""Migration 0024_chat_session_profile goes up, down and up again.

Run against a throwaway database on the same server, never the shared dev
database: other branches apply their own revisions there, and a downgrade on
it would pull a column out from under whoever is reading it. The database is
created from scratch, so the round trip also proves the whole chain still
builds up to this revision.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from adelia.config import settings
from tests.pg_gate import PG_AVAILABLE

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

API_DIR = Path(__file__).resolve().parents[1]
REVISION = "0024_chat_session_profile"


async def _connect(database: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=settings.postgres_host, port=settings.postgres_port,
        user=settings.postgres_user, password=settings.postgres_password, database=database,
    )


def _alembic(database: str, *args: str) -> None:
    # A subprocess, so the database name reaches alembic/env.py through the
    # same settings it always reads, and the app's engine is never re-pointed.
    env = {**os.environ, "POSTGRES_DB": database}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_DIR, env=env, capture_output=True, text=True, timeout=240,
    )
    assert result.returncode == 0, result.stderr[-2000:]


async def _shape(database: str) -> dict:
    conn = await _connect(database)
    try:
        version = await conn.fetchval("SELECT version_num FROM alembic_version")
        column = await conn.fetchrow(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'chat_sessions' AND column_name = 'profile_id'"
        )
        fk = await conn.fetchval(
            "SELECT confdeltype FROM pg_constraint "
            "WHERE conname = 'fk_chat_sessions_profile' AND contype = 'f'"
        )
        index = await conn.fetchval(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_chat_sessions_profile'"
        )
    finally:
        await conn.close()
    return {"version": version, "nullable": column and column["is_nullable"],
            "on_delete": fk, "index": index}


@pytest.mark.timeout(480)
async def test_upgrade_downgrade_upgrade_round_trip():
    database = f"adelia_mig_{uuid.uuid4().hex[:10]}"
    admin = await _connect(settings.postgres_db)
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    try:
        # To this revision, not "head": 0025 (guest accounts) came after it,
        # and the round trip under test is this one's.
        _alembic(database, "upgrade", REVISION)
        up = await _shape(database)
        assert up["version"] == REVISION
        assert up["nullable"] == "YES"
        # CASCADE: a child's conversation is never reassigned to the account,
        # where the single-child fallback of GET /today would read it as her
        # sibling's (same reasoning as observations, 0023).
        assert up["on_delete"] == b"c" or up["on_delete"] == "c"
        assert up["index"].endswith("(user_id, profile_id)")

        _alembic(database, "downgrade", "-1")
        down = await _shape(database)
        assert down == {"version": "0023_observations", "nullable": None,
                        "on_delete": None, "index": None}

        _alembic(database, "upgrade", REVISION)
        assert await _shape(database) == up
    finally:
        admin = await _connect(settings.postgres_db)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        finally:
            await admin.close()
