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


async def test_rejects_unowned_profile_id(client, auth_headers, monkeypatch):
    """IDOR guard: client-supplied profile_id must be verified against user_id.
    profile_service.get_profile returns None for both 'doesn't exist' and
    'belongs to someone else' — mocking that single return covers both cases.

    No real Postgres needed: get_profile is mocked to never touch the db
    argument, so AsyncSessionLocal opened for the check never issues a query."""
    from adelia.routers import consent as consent_router

    async def fake_get_profile(db, *, profile_id, user_id):
        return None

    monkeypatch.setattr(consent_router.profile_service, "get_profile", fake_get_profile)

    resp = await client.post(
        "/consent-events",
        headers=auth_headers,
        json={
            "event_type": "recording_declined",
            "profile_id": str(uuid.uuid4()),
            "policy_version": "2026-08-17",
            "locale": "es",
        },
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Profile not found"


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


async def _seed_user(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as session:
        user = User(email=email)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


@pytest.mark.skipif(
    not PG_AVAILABLE,
    reason="needs Postgres running (docker compose up -d), same as test_documents_upload.py",
)
async def test_rejects_cross_user_profile_id(client, monkeypatch):
    """Real end-to-end IDOR check: user A declines with user B's profile_id.
    Must 404 and must NOT create a ConsentEvent (ownership check runs before
    the insert, fail fast)."""
    from datetime import date

    from adelia.config import settings
    from adelia.enrichment import profile_service
    from adelia.enrichment.profile_service import ProfileCreate

    monkeypatch.setattr(settings, "auth_secret", "test-secret")

    user_a = await _seed_user(f"a-{uuid.uuid4()}@adelia.app")
    user_b = await _seed_user(f"b-{uuid.uuid4()}@adelia.app")
    async with AsyncSessionLocal() as session:
        profile_b = await profile_service.create_profile(
            session,
            user_id=user_b,
            data=ProfileCreate(
                display_name="Hijo de B",
                relationship="child",
                date_of_birth=date(2020, 1, 1),
                sex="F",
            ),
        )
        await session.commit()
        profile_b_id = profile_b.id

    token_a = make_token(str(user_a))

    resp = await client.post(
        "/consent-events",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "event_type": "recording_declined",
            "profile_id": str(profile_b_id),
            "policy_version": "2026-08-17",
            "locale": "es",
        },
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Profile not found"

    # Verify no ConsentEvent was created for user A
    async with AsyncSessionLocal() as session:
        events = (
            await session.execute(
                sa.select(ConsentEvent).where(ConsentEvent.user_id == user_a)
            )
        ).scalars().all()
    assert events == []


@pytest.mark.skipif(
    not PG_AVAILABLE,
    reason="needs Postgres running (docker compose up -d), same as test_documents_upload.py",
)
async def test_declined_event_with_owned_profile(client, monkeypatch):
    """Happy path: user posts declined event with their own profile_id.
    ConsentEvent created with profile_id persisted."""
    from datetime import date

    from adelia.config import settings
    from adelia.enrichment import profile_service
    from adelia.enrichment.profile_service import ProfileCreate

    monkeypatch.setattr(settings, "auth_secret", "test-secret")

    user_id = await _seed_user(f"profile-{uuid.uuid4()}@adelia.app")
    async with AsyncSessionLocal() as session:
        profile = await profile_service.create_profile(
            session,
            user_id=user_id,
            data=ProfileCreate(
                display_name="Mi hijo",
                relationship="child",
                date_of_birth=date(2020, 1, 1),
                sex="M",
            ),
        )
        await session.commit()
        profile_id = profile.id

    token = make_token(str(user_id))

    resp = await client.post(
        "/consent-events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "event_type": "recording_declined",
            "profile_id": str(profile_id),
            "policy_version": "2026-08-17",
            "locale": "es",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert "created_at" in body

    # Verify the event was created with profile_id persisted
    async with AsyncSessionLocal() as session:
        event = (
            await session.execute(
                sa.select(ConsentEvent).where(ConsentEvent.user_id == user_id)
            )
        ).scalar()
    assert event is not None
    assert event.event_type == "recording_declined"
    assert event.profile_id == profile_id
    assert event.policy_version == "2026-08-17"
    assert event.locale == "es"
    assert str(event.id) == body["id"]
