from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy import select

from adelia.db import AsyncSessionLocal
from adelia.models import Chunk, Document, Entity, User
from adelia.routers.documents import ALLOWED_MIME, normalize_mime
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
    assert docs[0]["file_name"] == "x.pdf"
    assert "s3_key" not in docs[0]


@pytest.mark.skipif(
    not PG_AVAILABLE,
    reason="needs Postgres running (docker compose up -d)"
)
async def test_list_documents_returns_real_counts_and_paginates(client, monkeypatch):
    """List endpoint must aggregate entity/chunk counts (was hardcoded 0)
    and honor limit/offset."""
    from adelia.config import settings
    monkeypatch.setattr(settings, "auth_secret", "test-secret")

    user = await _seed_user(f"counts-{uuid4()}@adelia.app")
    token = make_token(str(user.id))

    async with AsyncSessionLocal() as session:
        doc1 = Document(
            user_id=user.id, source="web", mime_type="application/pdf",
            s3_key="users/c/one.pdf",
        )
        doc2 = Document(
            user_id=user.id, source="web", mime_type="application/pdf",
            s3_key="users/c/two.pdf",
        )
        session.add_all([doc1, doc2])
        await session.flush()
        session.add_all([
            Entity(
                user_id=user.id, document_id=doc1.id, entity_type="condition",
                name="diabetes", provenance="extracted_from_clinician_doc",
            ),
            Entity(
                user_id=user.id, document_id=doc1.id, entity_type="medication",
                name="metformin", provenance="extracted_from_clinician_doc",
            ),
            Chunk(
                user_id=user.id, document_id=doc1.id, content="texto",
                chunk_index=0,
            ),
        ])
        await session.commit()
        doc1_id = str(doc1.id)

    response = await client.get(
        "/documents", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    docs = {d["id"]: d for d in response.json()}
    assert docs[doc1_id]["entity_count"] == 2
    assert docs[doc1_id]["chunk_count"] == 1

    paged = await client.get(
        "/documents?limit=1&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert paged.status_code == 200
    assert len(paged.json()) == 1


def test_normalize_strips_codecs_suffix():
    assert normalize_mime("audio/webm;codecs=opus") == "audio/webm"
    assert normalize_mime("audio/mp4; codecs=mp4a.40.2") == "audio/mp4"
    assert normalize_mime("application/pdf") == "application/pdf"
    assert normalize_mime(None) == ""


def test_browser_recording_mimes_allowed():
    for mime in ("audio/webm", "audio/mp4", "audio/ogg", "audio/x-m4a", "audio/flac"):
        assert mime in ALLOWED_MIME
