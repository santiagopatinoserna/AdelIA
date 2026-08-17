"""POST /consent-events: declined recording kill-switch events.

Two auth strategies, matching repo convention:
- The 422 test (invalid event_type) never reaches the DB (Pydantic rejects
  it before the endpoint runs), so auth is bypassed via app.dependency_overrides
  (see test_documents_upload.py, test_enrichment_router.py).
- The 201 test (declined event created) needs the real DB to verify the insert,
  so it uses a real seeded user + JWT, PG-gated like test_documents_upload.py.
"""
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from adelia.db import AsyncSessionLocal
from adelia.models import ConsentEvent, User
from adelia.main import app

from tests.pg_gate import PG_AVAILABLE
from tests.test_auth import make_token


def _override_auth():
    from adelia.auth import get_current_user_id

    user_id = uuid.uuid4()

    async def fake_user_id():
        return user_id

    app.dependency_overrides[get_current_user_id] = fake_user_id
    return user_id


def _clear_overrides():
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    """Bypasses DB-backed auth for tests that never reach the DB (pure
    validation-error paths)."""
    _override_auth()
    try:
        yield {"Authorization": "Bearer dummy"}
    finally:
        _clear_overrides()


async def test_informed_type_rejected_here(client, auth_headers):
    """'informed' events are created only inside POST /documents atomically.
    This endpoint rejects 'informed' with 422 (Literal constraint)."""
    resp = await client.post(
        "/consent-events",
        headers=auth_headers,
        json={"event_type": "recording_informed_professional", "policy_version": "x", "locale": "es"},
    )
    assert resp.status_code == 422


@pytest.mark.skipif(
    not PG_AVAILABLE,
    reason="needs Postgres running (docker compose up -d), same as test_documents_upload.py",
)
async def test_declined_event_created(client, monkeypatch):
    """POST /consent-events with event_type='recording_declined' creates a
    ConsentEvent row and returns 201 with id + created_at."""
    from adelia.config import settings
    monkeypatch.setattr(settings, "auth_secret", "test-secret")

    user_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        user = User(email=f"consent-{uuid.uuid4()}@adelia.app")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    token = make_token(str(user_id))

    resp = await client.post(
        "/consent-events",
        headers={"Authorization": f"Bearer {token}"},
        json={"event_type": "recording_declined", "policy_version": "2026-08-17", "locale": "es"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert "created_at" in body

    # Verify the event was created in the DB
    async with AsyncSessionLocal() as session:
        event = (
            await session.execute(
                sa.select(ConsentEvent).where(ConsentEvent.user_id == user_id)
            )
        ).scalar()
    assert event is not None
    assert event.event_type == "recording_declined"
    assert event.policy_version == "2026-08-17"
    assert event.locale == "es"
    assert str(event.id) == body["id"]
