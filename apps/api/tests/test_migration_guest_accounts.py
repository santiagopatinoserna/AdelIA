"""0025_guest_accounts goes up, down and up again (decision of 2026-11-06).

Same method as tests/test_migration_chat_session_profile.py: a throwaway
database on the same server, never the shared dev one, where other branches
apply their own revisions.
"""
from __future__ import annotations

import uuid

import pytest

from adelia.config import settings
from tests.pg_gate import PG_AVAILABLE
from tests.test_migration_chat_session_profile import _alembic, _connect

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

REVISION = "0025_guest_accounts"


async def _shape(database: str) -> dict:
    conn = await _connect(database)
    try:
        version = await conn.fetchval("SELECT version_num FROM alembic_version")
        columns = {
            (r["table_name"], r["column_name"])
            for r in await conn.fetch(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE (table_name, column_name) IN (('users', 'is_guest'), "
                "('chat_sessions', 'surface'), ('chat_messages', 'evidence_citations'))")
        }
        tables = {
            r["table_name"]
            for r in await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name IN ('guest_claims', 'demo_seed_embeddings')")
        }
    finally:
        await conn.close()
    return {"version": version, "columns": columns, "tables": tables}


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
        assert up["version"] == REVISION
        assert up["columns"] == {("users", "is_guest"), ("chat_sessions", "surface"),
                                 ("chat_messages", "evidence_citations")}
        assert up["tables"] == {"guest_claims", "demo_seed_embeddings"}

        _alembic(database, "downgrade", "-1")
        assert await _shape(database) == {
            "version": "0024_chat_session_profile", "columns": set(), "tables": set()}

        _alembic(database, "upgrade", REVISION)
        assert await _shape(database) == up
    finally:
        admin = await _connect(settings.postgres_db)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        finally:
            await admin.close()
