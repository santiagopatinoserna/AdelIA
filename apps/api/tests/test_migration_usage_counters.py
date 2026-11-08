"""0026_usage_counters goes up, down and up again (2026-11-08).

Same method as tests/test_migration_guest_accounts.py: a throwaway database
on the same server, never the shared dev one, where other branches apply their
own revisions. The revision was 0024 in 6773d0b and is chained behind main's
0025 here; `alembic heads` must still give one head.
"""
from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from adelia.config import settings
from tests.pg_gate import PG_AVAILABLE
from tests.test_migration_chat_session_profile import _alembic, _connect

REVISION = "0026_usage_counters"
API_DIR = Path(__file__).parents[1]

COLUMNS = {
    "day", "surface", "operation", "provider", "model", "calls", "input_tokens",
    "output_tokens", "cache_read_tokens", "cache_write_tokens", "pages", "audio_seconds",
}


def test_there_is_one_head_and_it_is_this_revision():
    out = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"], cwd=API_DIR, capture_output=True,
        text=True, check=True,
    ).stdout.split()

    assert [w for w in out if w.startswith("00")] == [REVISION]


async def _shape(database: str) -> dict:
    conn = await _connect(database)
    try:
        version = await conn.fetchval("SELECT version_num FROM alembic_version")
        columns = {
            r["column_name"]
            for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'usage_counters'")
        }
        key = {
            r["attname"]
            for r in await conn.fetch(
                "SELECT a.attname FROM pg_index i JOIN pg_attribute a "
                "ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid = 'usage_counters'::regclass AND i.indisprimary")
        } if columns else set()
    finally:
        await conn.close()
    return {"version": version, "columns": columns, "key": key}


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")
@pytest.mark.timeout(480)
async def test_upgrade_downgrade_upgrade_round_trip():
    database = f"adelia_mig_{uuid.uuid4().hex[:10]}"
    admin = await _connect(settings.postgres_db)
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    try:
        _alembic(database, "upgrade", REVISION)
        up = await _shape(database)
        assert up == {
            "version": REVISION, "columns": COLUMNS,
            "key": {"day", "surface", "operation", "provider", "model"},
        }

        _alembic(database, "downgrade", "-1")
        assert await _shape(database) == {
            "version": "0025_guest_accounts", "columns": set(), "key": set()}

        _alembic(database, "upgrade", REVISION)
        assert await _shape(database) == up
    finally:
        admin = await _connect(settings.postgres_db)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        finally:
            await admin.close()
