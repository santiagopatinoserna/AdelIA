"""One-click data export (GDPR art. 20). PG-gated."""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from adelia.auth import get_current_user_id
from adelia.main import app
from adelia.models import ConsentEvent, Document, Entity, Profile

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE

pytestmark = pytest.mark.skipif(
    not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres"
)


def _client_as(user_id: uuid.UUID) -> AsyncClient:
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_world(user_id: uuid.UUID) -> None:
    from adelia.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        profile = Profile(
            user_id=user_id,
            display_name="Bebé Test",
            relationship="child",
            date_of_birth=date(2025, 7, 1),
            sex="F",
            is_default=True,
        )
        session.add(profile)
        await session.flush()
        doc_id = uuid.uuid4()
        session.add(
            Document(
                id=doc_id,
                user_id=user_id,
                source="consulta",
                mime_type="audio/webm",
                s3_key=f"users/{user_id}/{uuid.uuid4()}-c.webm",
                raw_text="[Hablante 1] Percentil 60.",
                document_metadata={"speaker_names": {"1": "Pediatra"}},
            )
        )
        await session.flush()
        session.add(
            Entity(
                user_id=user_id,
                profile_id=profile.id,
                document_id=doc_id,
                entity_type="immunization",
                coding_system="SNOMED",
                code="871878002",
                name="Vacuna hexavalente",
                event_date=date(2026, 8, 1),
                provenance="extracted_from_clinician_doc",
                confidence=0.95,
                raw_quote="hexavalente",
            )
        )
        session.add(
            ConsentEvent(
                user_id=user_id,
                profile_id=profile.id,
                document_id=doc_id,
                event_type="recording_informed_professional",
                policy_version="2026-08-17",
                locale="es",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_export_contains_fhir_bundle_and_raw_layers():
    user_id = await make_user()
    await _seed_world(user_id)

    try:
        async with _client_as(user_id) as client:
            resp = await client.get("/users/me/export")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")
    body = resp.json()
    assert body["format"] == "adelia-export-v1"

    bundle = body["fhir_bundle"]
    assert bundle["resourceType"] == "Bundle" and bundle["type"] == "collection"
    types = [e["resource"]["resourceType"] for e in bundle["entry"]]
    assert "Patient" in types and "Immunization" in types

    imm = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Immunization")
    assert imm["vaccineCode"]["coding"][0]["system"] == "http://snomed.info/sct"
    assert imm["vaccineCode"]["coding"][0]["code"] == "871878002"
    assert imm["occurrenceDateTime"] == "2026-08-01"
    assert imm["patient"]["reference"].startswith("Patient/")

    raw = body["adelia"]
    assert raw["documents"][0]["raw_text"] == "[Hablante 1] Percentil 60."
    assert raw["documents"][0]["speaker_names"] == {"1": "Pediatra"}
    assert raw["consent_events"][0]["event_type"] == "recording_informed_professional"
    assert "s3_key" not in raw["documents"][0]


@pytest.mark.asyncio
async def test_export_is_scoped_to_the_requesting_user():
    owner = await make_user()
    await _seed_world(owner)
    other = await make_user()

    try:
        async with _client_as(other) as client:
            resp = await client.get("/users/me/export")
    finally:
        app.dependency_overrides.clear()

    body = resp.json()
    assert body["adelia"]["documents"] == []
    assert body["adelia"]["entities"] == []
    assert all(
        e["resource"]["resourceType"] != "Immunization" for e in body["fhir_bundle"]["entry"]
    )
