"""Briefings router route-level tests via TestClient + monkeypatch."""
from __future__ import annotations

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from adelia.main import app


def _override_auth(monkeypatch, user_id: UUID):
    """Override the get_current_user_id dependency via FastAPI's app overrides."""
    from adelia.auth import get_current_user_id

    async def fake_user_id():
        return user_id

    app.dependency_overrides[get_current_user_id] = fake_user_id


def _override_db(monkeypatch):
    """Override the get_db dependency so endpoints get a stub session.

    Awaitable methods (.commit, .execute, .flush) are AsyncMocks.
    """
    from adelia.db import get_db

    async def fake_db():
        stub = MagicMock()
        stub.commit = AsyncMock()
        stub.flush = AsyncMock()
        stub.execute = AsyncMock()
        yield stub

    app.dependency_overrides[get_db] = fake_db


def _clear_overrides():
    app.dependency_overrides.clear()


def _make_fake_briefing(**overrides):
    fake = MagicMock()
    fake.id = overrides.get("id", uuid4())
    fake.target_specialty = overrides.get("target_specialty", "endocrinology")
    fake.status = overrides.get("status", "processing")
    fake.is_stale = overrides.get("is_stale", False)
    fake.created_at = overrides.get("created_at", datetime(2026, 5, 13, 10, 0, 0, tzinfo=UTC))
    fake.completed_at = overrides.get("completed_at", None)
    fake.error_message = overrides.get("error_message", None)
    fake.payload = overrides.get("payload", None)
    fake.html_render = overrides.get("html_render", None)
    return fake


def test_post_briefings_returns_202_with_processing_status(monkeypatch):
    user_id = uuid4()
    _override_auth(monkeypatch, user_id)
    _override_db(monkeypatch)

    fake_briefing = _make_fake_briefing(status="processing", target_specialty="endocrinology")

    from adelia.services import briefing_repo
    monkeypatch.setattr(briefing_repo, "create_briefing", AsyncMock(return_value=fake_briefing))
    from adelia.routers import briefings as router_module
    monkeypatch.setattr(router_module, "_enqueue", lambda *a, **kw: None)

    try:
        with TestClient(app) as client:
            resp = client.post(
                "/briefings",
                json={"target_specialty": "endocrinology"},
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "processing"
        assert body["target_specialty"] == "endocrinology"
    finally:
        _clear_overrides()


def test_get_briefings_returns_owned_list(monkeypatch):
    user_id = uuid4()
    _override_auth(monkeypatch, user_id)
    _override_db(monkeypatch)

    fake_a = _make_fake_briefing(target_specialty="default", status="ready")
    fake_b = _make_fake_briefing(target_specialty="cardiology", status="processing")

    from adelia.services import briefing_repo
    monkeypatch.setattr(briefing_repo, "list_for_user", AsyncMock(return_value=[fake_a, fake_b]))

    try:
        with TestClient(app) as client:
            resp = client.get("/briefings", headers={"Authorization": "Bearer dummy"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
    finally:
        _clear_overrides()


def test_get_briefing_by_id_returns_404_for_cross_user(monkeypatch):
    other_user = uuid4()
    _override_auth(monkeypatch, other_user)
    _override_db(monkeypatch)

    from adelia.services import briefing_repo
    monkeypatch.setattr(briefing_repo, "get_by_id", AsyncMock(return_value=None))

    try:
        with TestClient(app) as client:
            resp = client.get(f"/briefings/{uuid4()}", headers={"Authorization": "Bearer dummy"})
        assert resp.status_code == 404
    finally:
        _clear_overrides()


def test_get_briefing_by_id_returns_payload_when_ready(monkeypatch):
    user_id = uuid4()
    _override_auth(monkeypatch, user_id)
    _override_db(monkeypatch)

    fake_briefing = _make_fake_briefing(
        target_specialty="endocrinology",
        status="ready",
        payload={
            "schema_version": "1.0",
            "generated_at": "2026-05-13T10:00:00+00:00",
            "target_specialty": "endocrinology",
            "patient": {"name": "x", "age": 1, "sex": "?"},
            "sections": {
                "reason_for_consult": None,
                "active_problems": [],
                "medications": [],
                "allergies": "no_known_allergies",
                "immunizations": None,
                "procedures": [],
                "family_history": None,
                "relevant_observations": [],
                "open_questions": [],
            },
            "applied_filter": {"specialty": "endocrinology", "rules_version": "1.0"},
            "llm_meta": {"model": "m", "tokens_used": 0, "cost_estimate_usd": 0.0},
        },
        html_render="<html></html>",
    )

    from adelia.services import briefing_repo
    monkeypatch.setattr(briefing_repo, "get_by_id", AsyncMock(return_value=fake_briefing))

    try:
        with TestClient(app) as client:
            resp = client.get(f"/briefings/{fake_briefing.id}", headers={"Authorization": "Bearer dummy"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        assert body["payload"] is not None
        assert body["html_render"] == "<html></html>"
    finally:
        _clear_overrides()


def test_post_regenerate_creates_new_processing_briefing(monkeypatch):
    user_id = uuid4()
    _override_auth(monkeypatch, user_id)
    _override_db(monkeypatch)

    original = _make_fake_briefing(target_specialty="default")
    new_briefing = _make_fake_briefing(target_specialty="default", status="processing")

    from adelia.services import briefing_repo
    monkeypatch.setattr(briefing_repo, "get_by_id", AsyncMock(return_value=original))
    monkeypatch.setattr(briefing_repo, "create_briefing", AsyncMock(return_value=new_briefing))
    from adelia.routers import briefings as router_module
    monkeypatch.setattr(router_module, "_enqueue", lambda *a, **kw: None)

    try:
        with TestClient(app) as client:
            resp = client.post(
                f"/briefings/{original.id}/regenerate",
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "processing"
        assert body["id"] != str(original.id)
    finally:
        _clear_overrides()


def test_post_regenerate_cross_user_returns_404(monkeypatch):
    other = uuid4()
    _override_auth(monkeypatch, other)
    _override_db(monkeypatch)

    from adelia.services import briefing_repo
    monkeypatch.setattr(briefing_repo, "get_by_id", AsyncMock(return_value=None))

    try:
        with TestClient(app) as client:
            resp = client.post(
                f"/briefings/{uuid4()}/regenerate",
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 404
    finally:
        _clear_overrides()


def test_delete_briefing_returns_204(monkeypatch):
    user_id = uuid4()
    _override_auth(monkeypatch, user_id)
    _override_db(monkeypatch)

    from adelia.services import briefing_repo
    monkeypatch.setattr(briefing_repo, "soft_delete", AsyncMock(return_value=True))

    try:
        with TestClient(app) as client:
            resp = client.delete(f"/briefings/{uuid4()}", headers={"Authorization": "Bearer dummy"})
        assert resp.status_code == 204
    finally:
        _clear_overrides()


def test_post_briefing_rejects_invalid_specialty(monkeypatch):
    user_id = uuid4()
    _override_auth(monkeypatch, user_id)
    _override_db(monkeypatch)

    try:
        with TestClient(app) as client:
            resp = client.post(
                "/briefings",
                json={"target_specialty": "psychiatry"},
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 422
    finally:
        _clear_overrides()
