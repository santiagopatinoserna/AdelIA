"""GDPR right-to-erasure: DELETE /users/me removes the whole graph."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import Briefing, Chunk, Document, Entity, ShareLink, User
from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE
from tests.test_auth import make_token


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_delete_me_erases_documents_briefings_shares(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    user_id = await make_user()

    async with AsyncSessionLocal() as session:
        doc = Document(
            user_id=user_id, source="web", mime_type="application/pdf",
            s3_key=f"users/{user_id}/{uuid4()}-x.pdf", raw_text="data",
        )
        session.add(doc)
        await session.flush()
        session.add(Entity(
            user_id=user_id, document_id=doc.id, entity_type="observation",
            name="glucosa", provenance="extracted_from_clinician_doc",
        ))
        session.add(Chunk(
            user_id=user_id, document_id=doc.id, content="texto", chunk_index=0,
        ))
        briefing = Briefing(user_id=user_id, target_specialty="default")
        session.add(briefing)
        await session.flush()
        session.add(ShareLink(
            token=f"tok-{uuid4()}", user_id=user_id, briefing_id=briefing.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        await session.commit()

    token = make_token(str(user_id))
    response = await client.delete(
        "/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 204

    async with AsyncSessionLocal() as session:
        for model in (User, Document, Entity, Chunk, Briefing, ShareLink):
            owner = model.user_id if model is not User else model.id
            count = await session.scalar(
                sa.select(sa.func.count()).select_from(model).where(owner == user_id)
            )
            assert count == 0, f"{model.__tablename__} not erased"


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_delete_me_requires_auth(client):
    response = await client.delete("/users/me")
    assert response.status_code in (401, 403)
