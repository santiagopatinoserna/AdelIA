"""0026_analytics goes up, down and up again (decision of 2026-11-07).

Same method as tests/test_migration_guest_accounts.py: a throwaway database on
the same server, never the shared dev one, where other branches apply their
own revisions. The models must match what the migration creates, or
`services.analytics.ensure_tables` (tests, the shared dev database) and
`alembic upgrade head` (CI, production) would build two different schemas.
"""
from __future__ import annotations

import uuid

import pytest

from adelia.config import settings
from adelia.models import AnalyticsConsent, AnalyticsEvent, AnalyticsSession
from tests.pg_gate import PG_AVAILABLE
from tests.test_migration_chat_session_profile import _alembic, _connect

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

REVISION = "0026_analytics"
TABLES = {
    "analytics_consents": AnalyticsConsent,
    "analytics_sessions": AnalyticsSession,
    "analytics_events": AnalyticsEvent,
}


async def _shape(database: str) -> dict:
    conn = await _connect(database)
    try:
        version = await conn.fetchval("SELECT version_num FROM alembic_version")
        columns: dict[str, set[str]] = {}
        for r in await conn.fetch(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_name = ANY($1::text[])", list(TABLES)):
            columns.setdefault(r["table_name"], set()).add(r["column_name"])
    finally:
        await conn.close()
    return {"version": version, "columns": columns}


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
        assert up["columns"] == {
            name: set(model.__table__.columns.keys()) for name, model in TABLES.items()
        }

        _alembic(database, "downgrade", "-1")
        assert await _shape(database) == {"version": "0025_guest_accounts", "columns": {}}

        _alembic(database, "upgrade", REVISION)
        assert await _shape(database) == up
    finally:
        admin = await _connect(settings.postgres_db)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        finally:
            await admin.close()
