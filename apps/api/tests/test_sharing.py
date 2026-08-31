"""Sharing service tests — token generation, render_pdf (gated), router.

PG-bound tests gated. Router tests use mocked DB.
"""
from __future__ import annotations

from datetime import datetime, UTC, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from adelia.main import app
from adelia.services import sharing as sharing_svc


def _override_auth(user_id: UUID):
    # BOTH dependencies: POST /shares and GET /briefings/{id}/pdf sit behind
    # require_active_subscription (creating a public link to a baby's history
    # and rendering a PDF are what a lapsed account should not get), while
    # listing and revoking stay on get_current_user_id so she can always pull
    # a leaked link back. Same pattern as tests/test_briefings_router.py.
    from adelia.auth import get_current_user_id, require_active_subscription

    async def fake_user_id():
        return user_id

    app.dependency_overrides[get_current_user_id] = fake_user_id
    app.dependency_overrides[require_active_subscription] = fake_user_id


def _override_db():
    from adelia.db import get_db

    async def fake_db():
        stub = MagicMock()
        stub.commit = AsyncMock()
        stub.flush = AsyncMock()
        stub.execute = AsyncMock()
        yield stub

    app.dependency_overrides[get_db] = fake_db


def _clear():
    app.dependency_overrides.clear()


# ----------------------------------------------------------------------------
# Pure token generation
# ----------------------------------------------------------------------------


def test_new_token_is_url_safe():
    tok = sharing_svc._new_token()
    assert len(tok) >= 30  # base64url of 32 bytes ~43 chars
    # Should not contain non-URL chars
    assert all(c.isalnum() or c in "-_" for c in tok)


def test_new_token_is_unique():
    tokens = {sharing_svc._new_token() for _ in range(100)}
    assert len(tokens) == 100  # all distinct


# ----------------------------------------------------------------------------
# Router — POST /shares
# ----------------------------------------------------------------------------


def test_create_share_rejects_unknown_briefing(monkeypatch):
    user_id = uuid4()
    _override_auth(user_id)
    _override_db()

    from adelia.services import briefing_repo

    monkeypatch.setattr(briefing_repo, "get_by_id", AsyncMock(return_value=None))

    try:
        with TestClient(app) as client:
            resp = client.post(
                "/shares",
                headers={"Authorization": "Bearer dummy"},
                json={"briefing_id": str(uuid4()), "ttl_hours": 24},
            )
        assert resp.status_code == 404
    finally:
        _clear()


def test_create_share_rejects_not_ready_briefing(monkeypatch):
    user_id = uuid4()
    _override_auth(user_id)
    _override_db()

    from adelia.services import briefing_repo

    fake_briefing = MagicMock(status="processing")
    monkeypatch.setattr(briefing_repo, "get_by_id", AsyncMock(return_value=fake_briefing))

    try:
        with TestClient(app) as client:
            resp = client.post(
                "/shares",
                headers={"Authorization": "Bearer dummy"},
                json={"briefing_id": str(uuid4()), "ttl_hours": 24},
            )
        assert resp.status_code == 409
    finally:
        _clear()


def test_create_share_happy_path(monkeypatch):
    user_id = uuid4()
    _override_auth(user_id)
    _override_db()

    from adelia.services import briefing_repo

    briefing_id = uuid4()
    fake_briefing = MagicMock(id=briefing_id, status="ready", user_id=user_id)
    monkeypatch.setattr(briefing_repo, "get_by_id", AsyncMock(return_value=fake_briefing))

    fake_link = MagicMock()
    fake_link.token = "abc123token"
    fake_link.briefing_id = briefing_id
    fake_link.expires_at = datetime.now(UTC) + timedelta(hours=24)
    fake_link.revoked = False
    fake_link.access_count = 0
    fake_link.last_accessed_at = None
    fake_link.created_at = datetime.now(UTC)

    monkeypatch.setattr(
        sharing_svc, "create_share_link", AsyncMock(return_value=fake_link)
    )

    try:
        with TestClient(app) as client:
            resp = client.post(
                "/shares",
                headers={"Authorization": "Bearer dummy"},
                json={"briefing_id": str(briefing_id), "ttl_hours": 24},
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["token"] == "abc123token"
        assert "/s/abc123token" in body["share_url"]
    finally:
        _clear()


def test_create_share_validates_ttl_range():
    """TTL must be 1-720 hours."""
    user_id = uuid4()
    _override_auth(user_id)
    _override_db()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/shares",
                headers={"Authorization": "Bearer dummy"},
                json={"briefing_id": str(uuid4()), "ttl_hours": 9999},
            )
        assert resp.status_code == 422
    finally:
        _clear()


# ----------------------------------------------------------------------------
# Router — DELETE /shares/{token}
# ----------------------------------------------------------------------------


def test_revoke_share_not_found_returns_404(monkeypatch):
    user_id = uuid4()
    _override_auth(user_id)
    _override_db()

    monkeypatch.setattr(sharing_svc, "revoke_share", AsyncMock(return_value=False))

    try:
        with TestClient(app) as client:
            resp = client.delete(
                "/shares/nonexistent",
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 404
    finally:
        _clear()


def test_revoke_share_happy_path(monkeypatch):
    user_id = uuid4()
    _override_auth(user_id)
    _override_db()

    monkeypatch.setattr(sharing_svc, "revoke_share", AsyncMock(return_value=True))

    try:
        with TestClient(app) as client:
            resp = client.delete(
                "/shares/sometoken",
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 204
    finally:
        _clear()


# ----------------------------------------------------------------------------
# Public viewer — GET /s/{token}
# ----------------------------------------------------------------------------


def test_public_view_invalid_token_returns_404(monkeypatch):
    """No auth needed. Invalid/expired token → generic 404 HTML."""
    monkeypatch.setattr(
        sharing_svc, "resolve_token", AsyncMock(return_value=None)
    )

    with TestClient(app) as client:
        resp = client.get("/s/bogus_token")
    assert resp.status_code == 404
    assert "invalid" in resp.text.lower() or "expired" in resp.text.lower()


def test_public_view_returns_html(monkeypatch):
    fake_resolved = sharing_svc.ResolvedShare(
        briefing_id=uuid4(),
        briefing_payload=None,
        briefing_html="<html><body><h1>Sample briefing</h1></body></html>",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        view_count=1,
    )
    monkeypatch.setattr(
        sharing_svc, "resolve_token", AsyncMock(return_value=fake_resolved)
    )

    with TestClient(app) as client:
        resp = client.get("/s/sometoken")
    assert resp.status_code == 200
    assert "Sample briefing" in resp.text


# ----------------------------------------------------------------------------
# PDF rendering — gated by WeasyPrint availability
# ----------------------------------------------------------------------------


def test_render_pdf_with_minimal_payload():
    """Smoke test: WeasyPrint renders the briefing template without exception."""
    try:
        from weasyprint import HTML  # noqa: F401
    except (ImportError, OSError) as e:
        pytest.skip(f"WeasyPrint not available in this env: {e}")

    from datetime import datetime, UTC
    from adelia.schemas import (
        AppliedFilter,
        BriefingPayload,
        BriefingSections,
        LLMMeta,
        PatientHeader,
        Specialty,
    )

    payload = BriefingPayload(
        schema_version="1.0",
        generated_at=datetime.now(UTC),
        target_specialty=Specialty.DEFAULT,
        patient=PatientHeader(name="Test", age=42, sex="?"),
        sections=BriefingSections(
            reason_for_consult="Annual checkup",
            active_problems=[],
            medications=[],
            allergies="no_known_allergies",
            immunizations=None,
            procedures=[],
            family_history=None,
            relevant_observations=[],
            open_questions=[],
        ),
        applied_filter=AppliedFilter(specialty="default", rules_version="1.0"),
        llm_meta=LLMMeta(model="test", tokens_used=0, cost_estimate_usd=0.0),
    )

    pdf_bytes = sharing_svc.render_pdf(payload)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500  # reasonable minimum for any PDF
