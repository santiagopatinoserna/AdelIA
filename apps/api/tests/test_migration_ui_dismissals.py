"""0028_ui_dismissals goes up, down and up again (2026-11-09).

Same method as tests/test_migration_analytics.py: a throwaway database on the
same server, never the shared dev one, where other branches apply their own
revisions. The model must match what the migration creates, or
`services.dismissals.ensure_table` (tests, the shared dev database) and
`alembic upgrade head` (CI, production) would build two different schemas.
"""
from __future__ import annotations

import uuid

import pytest

from adelia.config import settings
from adelia.models import UiDismissal
from tests.pg_gate import PG_AVAILABLE
from tests.test_migration_chat_session_profile import _alembic, _connect
from tests.test_migration_usage_counters import _alembic_words

REVISION = "0028_ui_dismissals"
PREVIOUS = "0027_analytics"


def test_this_revision_is_the_only_head_and_follows_the_analytics():
    heads = _alembic_words("heads")
    chain = _alembic_words("history", "-r", f"{PREVIOUS}:{REVISION}")

    assert heads == [REVISION]
    assert chain[:2] == [PREVIOUS, REVISION]


async def _shape(database: str) -> dict:
    conn = await _connect(database)
    try:
        version = await conn.fetchval("SELECT version_num FROM alembic_version")
        columns = {
            r["column_name"]
            for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'ui_dismissals'")
        }
        cascade = bytes(await conn.fetchval(
            "SELECT confdeltype FROM pg_constraint "
            "WHERE conrelid = 'ui_dismissals'::regclass AND contype = 'f'")).decode() if columns else None
    finally:
        await conn.close()
    return {"version": version, "columns": columns, "cascade": cascade}


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
        assert up["version"] == REVISION
        assert up["columns"] == {c.name for c in UiDismissal.__table__.columns}
        assert up["cascade"] == "c"  # ON DELETE CASCADE: erasing her account erases this

        _alembic(database, "downgrade", "-1")
        assert await _shape(database) == {"version": PREVIOUS, "columns": set(), "cascade": None}

        _alembic(database, "upgrade", REVISION)
        assert await _shape(database) == up
    finally:
        admin = await _connect(settings.postgres_db)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        finally:
            await admin.close()
