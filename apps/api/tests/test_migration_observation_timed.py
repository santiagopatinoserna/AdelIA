"""0029_observation_timed goes up, down and up again (2026-11-24).

Same method as tests/test_migration_ui_dismissals.py: a throwaway database on
the same server, never the shared dev one, where other branches apply their
own revisions. A row written before the column existed was timed (today,
yesterday or a clock), so the default must be true; the model must match.
"""
from __future__ import annotations

import uuid

import pytest

from adelia.config import settings
from adelia.models import Observation
from tests.pg_gate import PG_AVAILABLE
from tests.test_migration_chat_session_profile import _alembic, _connect
from tests.test_migration_usage_counters import _alembic_words

REVISION = "0029_observation_timed"
PREVIOUS = "0028_ui_dismissals"


def test_this_revision_is_the_only_head_and_follows_the_dismissals():
    heads = _alembic_words("heads")
    chain = _alembic_words("history", "-r", f"{PREVIOUS}:{REVISION}")

    assert heads == [REVISION]
    assert [w.rstrip(",") for w in chain[:2]] == [PREVIOUS, REVISION]


async def _shape(database: str) -> dict:
    conn = await _connect(database)
    try:
        version = await conn.fetchval("SELECT version_num FROM alembic_version")
        columns = {
            r["column_name"]: (r["is_nullable"], r["column_default"])
            for r in await conn.fetch(
                "SELECT column_name, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_name = 'observations'")
        }
    finally:
        await conn.close()
    return {"version": version, "columns": columns}


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
        _alembic(database, "upgrade", PREVIOUS)
        conn = await _connect(database)
        try:  # a note written the day before the column came
            user_id = await conn.fetchval(
                "INSERT INTO users (email) VALUES ('mig-timed@adelia.test') RETURNING id")
            await conn.execute(
                "INSERT INTO observations (user_id, kind, text, observed_at, source) "
                "VALUES ($1, 'note', 'antes', now(), 'agent')", user_id)
        finally:
            await conn.close()

        _alembic(database, "upgrade", REVISION)
        up = await _shape(database)
        assert up["version"] == REVISION
        assert set(up["columns"]) == {c.name for c in Observation.__table__.columns}
        assert up["columns"]["timed"] == ("NO", "true")
        conn = await _connect(database)
        try:
            assert await conn.fetchval("SELECT timed FROM observations") is True
        finally:
            await conn.close()

        _alembic(database, "downgrade", "-1")
        down = await _shape(database)
        assert down["version"] == PREVIOUS and "timed" not in down["columns"]

        _alembic(database, "upgrade", REVISION)
        assert await _shape(database) == up
    finally:
        admin = await _connect(settings.postgres_db)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        finally:
            await admin.close()
