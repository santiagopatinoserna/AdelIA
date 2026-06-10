from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy import select

from adelia.db import AsyncSessionLocal
from adelia.models import Document, User
from tests.test_auth import make_token

from tests.pg_gate import PG_AVAILABLE

# NOTE: These integration tests need a running Postgres + MinIO stack
# (docker compose -f infra/docker-compose.dev.yml up -d) AND
# AUTH_SECRET set + alembic upgrade head executed.
# Auto-enabled when Postgres is reachable (see tests/pg_gate.py).


async def _seed_user(email: str):
    async with AsyncSessionLocal() as session:
        user = User(email=email)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.mark.skipif(
    not PG_AVAILABLE,
    reason="needs Postgres running (docker compose up -d)"
)
async def test_upload_creates_document_and_returns_processing(client, monkeypatch):
    """Skipped in sandbox; runs green when Postgres + MinIO are up + AUTH_SECRET set."""
    from adelia.config import settings
    monkeypatch.setattr(settings, "auth_secret", "test-secret")

    user = await _seed_user(f"upload-{uuid4()}@adelia.app")
    token = make_token(str(user.id))

    file_content = b"%PDF-1.4 fake test pdf body"
    files = {"file": ("test.pdf", BytesIO(file_content), "application/pdf")}

    response = await client.post(
        "/documents",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["mime_type"] == "application/pdf"
    assert body["status"] == "processing"
    assert body["raw_text"] is None

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Document).where(Document.user_id == user.id))
        doc = result.scalar_one()
        assert doc.s3_key.startswith(f"users/{user.id}/")


@pytest.mark.skipif(
    not PG_AVAILABLE,
    reason="needs Postgres running (docker compose up -d)"
)
async def test_list_documents_filters_by_user(client, monkeypatch):
    """Skipped in sandbox; runs green when Postgres is up."""
    from adelia.config import settings
    monkeypatch.setattr(settings, "auth_secret", "test-secret")

    user_a = await _seed_user(f"a-{uuid4()}@adelia.app")
    user_b = await _seed_user(f"b-{uuid4()}@adelia.app")
    token_a = make_token(str(user_a.id))

    async with AsyncSessionLocal() as session:
        session.add(Document(
            user_id=user_a.id, source="web", mime_type="application/pdf",
            s3_key="users/a/x.pdf",
        ))
        session.add(Document(
            user_id=user_b.id, source="web", mime_type="application/pdf",
            s3_key="users/b/y.pdf",
        ))
        await session.commit()

    response = await client.get(
        "/documents",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert response.status_code == 200
    docs = response.json()
    assert len(docs) == 1
    assert docs[0]["s3_key"] == "users/a/x.pdf"
