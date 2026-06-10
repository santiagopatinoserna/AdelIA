"""Tests for v0.2 enrichment router. Read-only endpoints fully tested,
DB endpoints (profiles) use mocked DB session, network endpoints (trials)
use monkeypatched httpx.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from adelia.main import app


_GENOMICS_FIXTURE = Path(__file__).parent / "fixtures" / "genomics_sample.txt"


def _override_auth(user_id: UUID):
    from adelia.auth import get_current_user_id

    async def fake_user_id():
        return user_id

    app.dependency_overrides[get_current_user_id] = fake_user_id


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
# L1 normalize
# ----------------------------------------------------------------------------


def test_normalize_endpoint_diabetes():
    _override_auth(uuid4())
    try:
        with TestClient(app) as client:
            resp = client.get(
                "/enrichment/code-normalize",
                params={"query": "diabetes tipo 2"},
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["icd10"] == "E11.9"
        assert body["snomed"] == "44054006"
    finally:
        _clear()


def test_normalize_endpoint_unknown():
    _override_auth(uuid4())
    try:
        with TestClient(app) as client:
            resp = client.get(
                "/enrichment/code-normalize",
                params={"query": "xyz_completely_unknown"},
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["icd10"] is None
        assert body["match_score"] == 0
    finally:
        _clear()


# ----------------------------------------------------------------------------
# L2 lab-evaluate
# ----------------------------------------------------------------------------


def test_lab_evaluate_bulk():
    _override_auth(uuid4())
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/enrichment/lab-evaluate",
                json={
                    "observations": [
                        {"name": "HbA1c", "value": 6.0},
                        {"name": "glucose", "value": 110},
                    ]
                },
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        # HbA1c 6.0 → prediabetes zone
        hba1c = next(r for r in body if r["name"] == "HbA1c")
        assert hba1c["zone_label"] == "prediabetes"
    finally:
        _clear()


# ----------------------------------------------------------------------------
# L3 drug-interactions
# ----------------------------------------------------------------------------


def test_drug_interactions_endpoint():
    _override_auth(uuid4())
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/enrichment/drug-interactions",
                json={"medications": ["warfarin", "ibuprofen", "metformin"]},
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert any(
            i["severity"] == "major"
            and {i["drug_a"], i["drug_b"]} == {"ibuprofen", "warfarin"}
            for i in body
        )
    finally:
        _clear()


# ----------------------------------------------------------------------------
# L5 trials
# ----------------------------------------------------------------------------


def test_trials_endpoint_handles_network_error(monkeypatch):
    """Network down → empty list, not 500."""
    _override_auth(uuid4())
    from adelia.enrichment import trial_matcher

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *args, **kwargs):
            import httpx

            raise httpx.ConnectError("net down")

    monkeypatch.setattr(trial_matcher.httpx, "AsyncClient", FakeClient)

    try:
        with TestClient(app) as client:
            resp = client.get(
                "/enrichment/trials",
                params={"condition": "diabetes"},
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 200
        assert resp.json() == []
    finally:
        _clear()


# ----------------------------------------------------------------------------
# L6 genomics
# ----------------------------------------------------------------------------


async def test_genomics_upload_matches_variants(client):
    from tests.db_helpers import make_user

    user_id = await make_user()
    _override_auth(user_id)
    try:
        with _GENOMICS_FIXTURE.open("rb") as f:
            resp = await client.post(
                "/enrichment/genomics/upload",
                headers={"Authorization": "Bearer dummy"},
                files={"file": ("genome.txt", f.read(), "text/plain")},
            )
        assert resp.status_code == 200
        body = resp.json()
        # Fixture has several PGx hits — at least CYP2C19
        cyp = next((h for h in body if h["gene"] == "CYP2C19"), None)
        assert cyp is not None
        assert cyp["category"] == "pharmacogenomics"
    finally:
        _clear()


def test_genomics_upload_rejects_non_text():
    _override_auth(uuid4())
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/enrichment/genomics/upload",
                headers={"Authorization": "Bearer dummy"},
                files={"file": ("binary.bin", b"\x00\xff\x00\xff", "image/png")},
            )
        assert resp.status_code == 400
    finally:
        _clear()


# ----------------------------------------------------------------------------
# L7 profiles (mocked DB)
# ----------------------------------------------------------------------------


def test_profiles_endpoints_use_dependency_overrides(monkeypatch):
    """Verify endpoints are wired (full PG paths gated). Tests router wiring,
    not DB logic — profile_service tests cover DB logic separately."""
    user_id = uuid4()
    _override_auth(user_id)
    _override_db()

    from adelia.enrichment import profile_service

    fake_profile = MagicMock()
    fake_profile.id = uuid4()
    fake_profile.display_name = "Test User"
    fake_profile.relationship = "self"
    fake_profile.date_of_birth = None
    fake_profile.sex = None
    fake_profile.is_default = True
    fake_profile.created_at = None

    monkeypatch.setattr(
        profile_service, "ensure_default_profile", AsyncMock(return_value=fake_profile)
    )
    monkeypatch.setattr(
        profile_service, "list_profiles", AsyncMock(return_value=[fake_profile])
    )

    try:
        with TestClient(app) as client:
            resp = client.get(
                "/enrichment/profiles",
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["display_name"] == "Test User"
        assert body[0]["is_default"] is True
    finally:
        _clear()


def test_profile_create_validates_relationship():
    _override_auth(uuid4())
    _override_db()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/enrichment/profiles",
                headers={"Authorization": "Bearer dummy"},
                json={
                    "display_name": "Test",
                    "relationship": "alien",  # invalid
                },
            )
        assert resp.status_code == 422
    finally:
        _clear()


# ----------------------------------------------------------------------------
# Coverage stats
# ----------------------------------------------------------------------------


def test_coverage_endpoint_returns_summary():
    _override_auth(uuid4())
    try:
        with TestClient(app) as client:
            resp = client.get(
                "/enrichment/coverage",
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["normalization"]["total"] >= 40
        assert body["lab_ranges_count"] >= 25
        assert body["drugs"]["interactions_total"] >= 25
        assert body["variants"]["variants_total"] >= 15
    finally:
        _clear()
