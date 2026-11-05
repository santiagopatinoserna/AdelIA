"""One-click data export (GDPR art. 20). PG-gated."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

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


@pytest.mark.asyncio
async def test_export_carries_her_conversations_and_the_child_each_was_about():
    """Art. 20 covers what she wrote: the chat transcripts were missing from the export.

    Each session says which child it was about (chat_sessions.profile_id), so a
    family of two can tell Nora's conversations from Adel's in the file.
    """
    from adelia.db import AsyncSessionLocal
    from adelia.models import ChatMessage, ChatSession

    user_id = await make_user()
    other = await make_user()
    async with AsyncSessionLocal() as session:
        nora = Profile(user_id=user_id, display_name="Nora", relationship="child",
                       is_default=True)
        session.add(nora)
        await session.flush()
        chat = ChatSession(user_id=user_id, title="Tomas", profile_id=nora.id)
        legacy = ChatSession(user_id=user_id, title="Antes")
        hers = ChatSession(user_id=other, title="Ajena")
        session.add_all([chat, legacy, hers])
        await session.flush()
        # One transaction shares one now(): the order is pinned by hand.
        asked = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
        session.add_all([
            ChatMessage(session_id=chat.id, user_id=user_id, role="assistant",
                        content="## Hoy\n- Ofrécele más a menudo [ev_1].",
                        created_at=asked + timedelta(seconds=5)),
            ChatMessage(session_id=chat.id, user_id=user_id, role="user", content="come poco",
                        created_at=asked),
            ChatMessage(session_id=hers.id, user_id=other, role="user", content="ajeno"),
        ])
        await session.commit()
        nora_id = nora.id

    try:
        async with _client_as(user_id) as client:
            resp = await client.get("/users/me/export")
    finally:
        app.dependency_overrides.clear()

    sessions = {s["title"]: s for s in resp.json()["adelia"]["chat_sessions"]}
    assert set(sessions) == {"Tomas", "Antes"}
    assert sessions["Tomas"]["profile_id"] == str(nora_id)
    assert sessions["Antes"]["profile_id"] is None
    assert [(m["role"], m["content"]) for m in sessions["Tomas"]["messages"]] == [
        ("user", "come poco"),
        ("assistant", "## Hoy\n- Ofrécele más a menudo [ev_1]."),
    ]
