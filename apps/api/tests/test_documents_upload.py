"""Consulta upload: form fields (source/profile_id/consent_policy_version/
locale), atomic ConsentEvent, diarize + profile_id propagation.

Two auth strategies, matching repo convention:
- 400-path tests never reach the DB/S3 (validation happens before either),
  so auth is bypassed via app.dependency_overrides (see test_enrichment_router.py,
  test_sharing.py, test_ingestion_router.py).
- The atomic-ConsentEvent test needs the real upload path (S3 put + DB commit)
  to run, so it uses a real seeded user + JWT, same as test_documents.py, and
  is PG-gated like tests/test_consent_models.py.
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
    """Bypasses DB-backed auth for tests that never reach the DB/S3 (pure
    validation-error paths)."""
    _override_auth()
    try:
        yield {"Authorization": "Bearer dummy"}
    finally:
        _clear_overrides()


async def _seed_user(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as session:
        user = User(email=email)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def test_upload_consulta_requires_consent(client, auth_headers):
    resp = await client.post(
        "/documents",
        headers=auth_headers,
        files={"file": ("c.webm", b"audio", "audio/webm;codecs=opus")},
        data={"source": "consulta"},
    )
    assert resp.status_code == 400
    assert "consent" in resp.json()["detail"].lower()


async def test_upload_rejects_unknown_source(client, auth_headers):
    resp = await client.post(
        "/documents",
        headers=auth_headers,
        files={"file": ("c.webm", b"audio", "audio/webm")},
        data={"source": "hacker"},
    )
    assert resp.status_code == 400


async def test_upload_consulta_rejects_oversized_policy_version(client, auth_headers):
    """ConsentEvent.policy_version is String(64) — an oversized value must be
    rejected here with a clean 400 instead of hitting the DB and 500ing."""
    resp = await client.post(
        "/documents",
        headers=auth_headers,
        files={"file": ("c.webm", b"audio", "audio/webm;codecs=opus")},
        data={"source": "consulta", "consent_policy_version": "x" * 65},
    )
    assert resp.status_code == 400
    assert "64" in resp.json()["detail"]


async def test_upload_consulta_rejects_non_audio(client, auth_headers):
    resp = await client.post(
        "/documents",
        headers=auth_headers,
        files={"file": ("c.pdf", b"%PDF-1.4", "application/pdf")},
        data={"source": "consulta", "consent_policy_version": "2026-08-17"},
    )
    assert resp.status_code == 400
    assert "audio" in resp.json()["detail"].lower()


async def test_upload_rejects_profile_not_owned_by_user(client, auth_headers, monkeypatch):
    """IDOR guard: a client-supplied profile_id must be verified against
    user_id before it's ever written to Document/ConsentEvent/Entity/Chunk.
    profile_service.get_profile returns None for both "doesn't exist" and
    "belongs to someone else" (same query, see profile_service.get_profile's
    docstring) — mocking that single return value covers both cases, matching
    adelia.routers.enrichment.get_user_profile's 404 behavior.

    No real Postgres needed: get_profile is mocked to never touch the `db`
    argument it's given, so the AsyncSessionLocal() opened around it never
    issues a query and never actually connects.
    """
    from adelia.routers import documents as documents_router

    async def fake_get_profile(db, *, profile_id, user_id):
        return None

    monkeypatch.setattr(documents_router.profile_service, "get_profile", fake_get_profile)

    resp = await client.post(
        "/documents",
        headers=auth_headers,
        files={"file": ("c.pdf", b"%PDF-1.4", "application/pdf")},
        data={"profile_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Profile not found"


@pytest.mark.skipif(
    not PG_AVAILABLE,
    reason="needs Postgres running (docker compose up -d), same as test_profile_service.py",
)
async def test_upload_rejects_cross_user_profile_id(client, monkeypatch):
    """Real end-to-end IDOR check: user A uploads with user B's profile_id.
    Must 404 and must NOT create a Document (nor, transitively, orphan a blob
    — the ownership check runs before the S3 put)."""
    from datetime import date

    from adelia.config import settings
    from adelia.enrichment import profile_service
    from adelia.enrichment.profile_service import ProfileCreate
    from adelia.models import Document

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
        "/documents",
        headers={"Authorization": f"Bearer {token_a}"},
        files={"file": ("c.pdf", b"%PDF-1.4", "application/pdf")},
        data={"profile_id": str(profile_b_id)},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Profile not found"

    async with AsyncSessionLocal() as session:
        docs = (
            await session.execute(
                sa.select(Document).where(Document.user_id == user_a)
            )
        ).scalars().all()
    assert docs == []


@pytest.mark.skipif(
    not PG_AVAILABLE,
    reason="needs Postgres + MinIO running (docker compose up -d), same as test_documents.py",
)
async def test_upload_consulta_creates_consent_event_atomically(client, monkeypatch):
    from adelia.config import settings
    monkeypatch.setattr(settings, "auth_secret", "test-secret")

    user_id = await _seed_user(f"consulta-{uuid.uuid4()}@adelia.app")
    token = make_token(str(user_id))

    resp = await client.post(
        "/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("c.webm", b"audio", "audio/webm;codecs=opus")},
        data={
            "source": "consulta",
            "consent_policy_version": "2026-08-17",
            "locale": "es",
        },
    )
    assert resp.status_code == 201
    doc_id = resp.json()["id"]

    async with AsyncSessionLocal() as session:
        events = (
            await session.execute(
                sa.select(ConsentEvent).where(
                    ConsentEvent.document_id == uuid.UUID(doc_id)
                )
            )
        ).scalars().all()
    assert len(events) == 1
    assert events[0].event_type == "recording_informed_professional"
    assert events[0].policy_version == "2026-08-17"
