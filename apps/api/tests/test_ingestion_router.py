"""Ingestion router tests — read-only endpoints fully tested, import endpoints
exercise the parser path with mocked DB session.
"""
from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from adelia.main import app


_APPLE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "ingestion" / "apple_health_sample.xml"
)
_CCD_FIXTURE = Path(__file__).parent / "fixtures" / "ingestion" / "ccd_sample.xml"


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
        # add() is sync — leave as MagicMock
        yield stub

    app.dependency_overrides[get_db] = fake_db


def _clear():
    app.dependency_overrides.clear()


def test_list_guides_returns_5_v01_platforms():
    _override_auth(uuid4())
    try:
        with TestClient(app) as client:
            resp = client.get("/ingestion/guides", headers={"Authorization": "Bearer dummy"})
        assert resp.status_code == 200
        body = resp.json()
        slugs = {g["slug"] for g in body}
        assert {
            "apple-health",
            "mychart",
            "mon-espace-sante-fr",
            "google-health-connect",
            "generic-ccd",
        }.issubset(slugs)
    finally:
        _clear()


def test_get_guide_apple_health_returns_markdown():
    _override_auth(uuid4())
    try:
        with TestClient(app) as client:
            resp = client.get(
                "/ingestion/guides/apple-health",
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["slug"] == "apple-health"
        assert "export" in body["markdown"].lower()
    finally:
        _clear()


def test_get_guide_missing_returns_404():
    _override_auth(uuid4())
    try:
        with TestClient(app) as client:
            resp = client.get(
                "/ingestion/guides/nonexistent",
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 404
    finally:
        _clear()


def test_list_gdpr_templates_returns_3_v01_countries():
    _override_auth(uuid4())
    try:
        with TestClient(app) as client:
            resp = client.get(
                "/ingestion/gdpr-templates", headers={"Authorization": "Bearer dummy"}
            )
        assert resp.status_code == 200
        body = resp.json()
        countries = {t["country"] for t in body}
        assert {"ES", "FR", "US"}.issubset(countries)
    finally:
        _clear()


def test_get_gdpr_template_spain_returns_markdown():
    _override_auth(uuid4())
    try:
        with TestClient(app) as client:
            resp = client.get(
                "/ingestion/gdpr-templates/ES",
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["country"] == "ES"
        assert "AEPD" in body["authority"]
        assert "RGPD" in body["markdown"]
    finally:
        _clear()


def test_get_gdpr_template_unknown_country_returns_404():
    _override_auth(uuid4())
    try:
        with TestClient(app) as client:
            resp = client.get(
                "/ingestion/gdpr-templates/ZZ",
                headers={"Authorization": "Bearer dummy"},
            )
        assert resp.status_code == 404
    finally:
        _clear()


def test_apple_health_import_rejects_non_zip():
    _override_auth(uuid4())
    _override_db()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/ingestion/apple-health/import",
                headers={"Authorization": "Bearer dummy"},
                files={"file": ("fake.txt", b"not a zip", "text/plain")},
            )
        assert resp.status_code == 400
        assert "ZIP" in resp.json()["detail"]
    finally:
        _clear()


def test_apple_health_import_happy_path_parses_records(monkeypatch):
    """Smoke test: zip with export.xml → parser runs, entities added, 201 returned."""
    import io
    import zipfile

    user_id = uuid4()
    _override_auth(user_id)
    _override_db()

    # Build a small in-memory zip containing our sample export.xml
    xml_bytes = _APPLE_FIXTURE.read_bytes()
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("apple_health_export/export.xml", xml_bytes)
    zip_buf.seek(0)

    try:
        with TestClient(app) as client:
            resp = client.post(
                "/ingestion/apple-health/import",
                headers={"Authorization": "Bearer dummy"},
                files={
                    "file": ("export.zip", zip_buf.getvalue(), "application/zip")
                },
            )
        # With the mocked db, the test exercises the parser + entity construction
        # path and reaches the response — PG-bound bulk insert is mocked via flush/commit
        assert resp.status_code == 201
        body = resp.json()
        assert body["source"] == "apple_health"
        assert body["entity_count"] == 9  # 9 supported records in fixture
        assert "weight" in body["sample_names"]
    finally:
        _clear()


def test_ccd_import_rejects_non_xml():
    _override_auth(uuid4())
    _override_db()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/ingestion/ccd/import",
                headers={"Authorization": "Bearer dummy"},
                files={"file": ("fake.txt", b"plain text", "text/plain")},
            )
        assert resp.status_code == 400
    finally:
        _clear()


def test_ccd_import_happy_path_parses_entries():
    _override_auth(uuid4())
    _override_db()

    xml_bytes = _CCD_FIXTURE.read_bytes()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/ingestion/ccd/import",
                headers={"Authorization": "Bearer dummy"},
                files={"file": ("ccd.xml", xml_bytes, "application/xml")},
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["source"] == "ccd_import"
        assert body["entity_count"] == 8  # 8 entries in fixture
    finally:
        _clear()
