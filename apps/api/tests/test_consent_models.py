"""ConsentEvent + Document(source='consulta') ORM tests. PG-gated."""
from __future__ import annotations

import uuid

import pytest

from adelia.models import ConsentEvent, Document

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres")
@pytest.mark.asyncio
async def test_consent_event_roundtrip():
    from adelia.db import AsyncSessionLocal

    user_id = await make_user()
    async with AsyncSessionLocal() as session:
        ev = ConsentEvent(
            user_id=user_id,
            event_type="recording_informed_professional",
            policy_version="2026-08-17",
            locale="es",
        )
        session.add(ev)
        await session.commit()
        await session.refresh(ev)
        assert ev.id is not None
        assert ev.created_at is not None


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres")
@pytest.mark.asyncio
async def test_document_source_consulta_allowed():
    from adelia.db import AsyncSessionLocal

    user_id = await make_user()
    async with AsyncSessionLocal() as session:
        doc = Document(
            user_id=user_id, source="consulta",
            mime_type="audio/webm", s3_key=f"users/{user_id}/{uuid.uuid4()}-c.webm",
        )
        session.add(doc)
        await session.commit()  # no IntegrityError => CHECK ampliado
        assert doc.id is not None
