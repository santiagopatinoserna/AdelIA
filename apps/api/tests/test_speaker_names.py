"""Speaker naming for diarized consultation transcripts. PG-gated.

Diarization can't know WHO speaker_1 is; the mom does. She names them once
(Pediatra / Yo) and the names persist in document_metadata and come back in
DocumentOut so every later read shows a conversation, not numbered voices.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from adelia.auth import get_current_user_id
from adelia.main import app
from adelia.models import Document

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE

pytestmark = pytest.mark.skipif(
    not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres"
)


async def _seed_consulta(user_id: uuid.UUID) -> uuid.UUID:
    from adelia.db import AsyncSessionLocal

    doc_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        session.add(
            Document(
                id=doc_id,
                user_id=user_id,
                source="consulta",
                mime_type="audio/webm",
                s3_key=f"users/{user_id}/{uuid.uuid4()}-c.webm",
                raw_text="[Hablante 1] Hola. [Hablante 2] Buenas.",
            )
        )
        await session.commit()
    return doc_id


def _client_as(user_id: uuid.UUID) -> AsyncClient:
    # PATCH /documents/{id}/speakers is one of the two document routes still
    # behind the paywall, so the gate has to be overridden too: it no longer
    # depends on get_current_user_id (adelia/auth.py loads the row once and
    # both dependencies read it).
    from adelia.auth import require_active_subscription

    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[require_active_subscription] = lambda: user_id
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_set_speaker_names_persists_and_returns_in_document():
    user_id = await make_user()
    doc_id = await _seed_consulta(user_id)

    try:
        async with _client_as(user_id) as client:
            resp = await client.patch(
                f"/documents/{doc_id}/speakers",
                json={"speaker_names": {"1": "Pediatra", "2": "Yo"}},
            )
            assert resp.status_code == 200
            assert resp.json()["speaker_names"] == {"1": "Pediatra", "2": "Yo"}

            detail = await client.get(f"/documents/{doc_id}")
            assert detail.json()["speaker_names"] == {"1": "Pediatra", "2": "Yo"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_speaker_names_opaque_across_users_and_validated():
    owner = await make_user()
    attacker = await make_user()
    doc_id = await _seed_consulta(owner)

    try:
        async with _client_as(attacker) as client:
            resp = await client.patch(
                f"/documents/{doc_id}/speakers",
                json={"speaker_names": {"1": "X"}},
            )
            assert resp.status_code == 404

        async with _client_as(owner) as client:
            too_long = await client.patch(
                f"/documents/{doc_id}/speakers",
                json={"speaker_names": {"1": "x" * 80}},
            )
            assert too_long.status_code == 422

            not_numeric = await client.patch(
                f"/documents/{doc_id}/speakers",
                json={"speaker_names": {"medico": "X"}},
            )
            assert not_numeric.status_code == 422
    finally:
        app.dependency_overrides.clear()
