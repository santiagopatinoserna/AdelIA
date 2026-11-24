from io import BytesIO
from uuid import uuid4

import httpx
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
    # subscription_status="active": /documents is behind the paywall
    # (adelia.auth.require_active_subscription).
    async with AsyncSessionLocal() as session:
        user = User(email=email, subscription_status="active")
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


# --- a cut consult whose summarizer gives nothing (third QA wave 2026-11-13) ---------
#
# The recorder flags a visit a reload, a closed tab or the browser itself cut short. The
# summarizer then leaves the last sentence out and ends with a coded line. Review of the
# summary package: when the summarizer failed (no key, as in CI; a refusal; retries spent)
# the summary was None and she never saw that the visit was cut, and the extractor still
# read the half-said fragment, so "sube de 30" could be stored as an entity.

_CUT_VISIT = (
    "[Hablante 1] El peso está muy bien, en el percentil 60.\n\n"
    "[Hablante 2] Vale. La fiebre es normal después de la vacuna. "
    "¿Y le puedo dar paracetamol esta noche si sube de 30?"
)


async def _seed_consult(meta: dict | None) -> tuple:
    """A consult Document as the upload leaves it, with processed_at set so no boot
    requeues it if the test dies (the pipeline sets it again)."""
    from datetime import datetime, timezone

    from tests.db_helpers import make_user

    user_id = await make_user()
    async with AsyncSessionLocal() as session:
        doc = Document(user_id=user_id, source="consulta", mime_type="audio/webm",
                       s3_key=f"test/{uuid4()}-consulta.webm", document_metadata=meta,
                       processed_at=datetime.now(timezone.utc))
        session.add(doc)
        await session.commit()
        return user_id, doc.id


def _fake_pipeline(monkeypatch, transcript: str) -> list[str]:
    """Storage, Voxtral, the extractor and the embedder faked; returns what the
    extractor was asked to read. The summarizer is left to each test."""
    from adelia.routers import documents as docs_mod

    class _Body:
        def read(self) -> bytes:
            return b"fake-consulta-audio"

    async def _get(key: str):
        return _Body()

    async def _transcribe(body, mime_type, diarize=False):
        return transcript

    read: list[str] = []

    async def _extract(text: str):
        read.append(text)
        return []

    async def _embed(texts: list[str]):
        return [[0.0] * 1024 for _ in texts]

    monkeypatch.setattr(docs_mod.storage, "get_object", _get)
    monkeypatch.setattr(docs_mod, "transcribe_audio", _transcribe)
    monkeypatch.setattr(docs_mod, "extract_entities", _extract)
    monkeypatch.setattr(docs_mod, "embed_texts", _embed)
    return read


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required: the pipeline writes a Document row")
@pytest.mark.parametrize("failure", ["no_key", "retries_spent"])
async def test_a_cut_consult_says_it_was_cut_when_the_summarizer_fails(monkeypatch, failure):
    from adelia.config import settings
    from adelia.routers import documents as docs_mod

    read = _fake_pipeline(monkeypatch, _CUT_VISIT)
    if failure == "no_key":
        # The real summarizer, with no key: RuntimeError, not retried (CI has no keys).
        monkeypatch.setattr(settings, "llm_provider", "mistral")
        monkeypatch.setattr(settings, "mistral_api_key", "")
    else:
        attempts: list[int] = []

        async def _down(text, **kw):
            attempts.append(1)
            raise httpx.ConnectError("summarizer down")

        monkeypatch.setattr(docs_mod, "RETRY_DELAYS", (0.0,))
        monkeypatch.setattr(docs_mod, "summarize_consultation", _down)
    _, doc_id = await _seed_consult({"interrupted": True, "locale": "en"})

    await docs_mod._process_document_inner(doc_id, "audio/webm", True)

    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, doc_id)
    # The coded line in the document's locale, with no model behind it.
    assert doc.document_metadata["summary"] == "- The recording was cut off: the end of the visit may be missing."
    assert doc.raw_text.endswith("si sube de 30? (The recording stopped here.)")
    # The extractor read only what was surely said whole.
    assert len(read) == 1
    assert "percentil 60" in read[0]
    assert "sube de 30" not in read[0]
    if failure == "retries_spent":
        assert len(attempts) == 2


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required: the pipeline writes a Document row")
async def test_a_consult_cut_after_one_sentence_stores_no_entity(monkeypatch):
    """Nothing in it was surely said whole: no extraction at all, and the summary is the
    cut line, which needs no model and so no key."""
    from adelia.config import settings
    from adelia.routers import documents as docs_mod

    read = _fake_pipeline(monkeypatch, "[Hablante 1] Le doy tres coma")
    monkeypatch.setattr(settings, "llm_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "")
    _, doc_id = await _seed_consult({"interrupted": True, "locale": "es"})

    await docs_mod._process_document_inner(doc_id, "audio/webm", True)

    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, doc_id)
        entities = (await session.execute(
            select(Entity).where(Entity.document_id == doc_id)
        )).scalars().all()
    assert read == []
    assert entities == []
    assert doc.document_metadata["summary"] == (
        "- La grabación se cortó: puede faltar el final de la consulta."
    )
    assert doc.raw_text == "[Hablante 1] Le doy tres coma (La grabación se cortó aquí.)"


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required: the pipeline writes a Document row")
async def test_a_whole_consult_is_read_whole_and_gets_no_cut_line(monkeypatch):
    """A visit she stopped herself: the extractor reads all of it, a failed summary stays
    absent as before, and the consult transcript is never rewritten (route.undictate is
    for her Spanish dictation only)."""
    from adelia.config import settings
    from adelia.routers import documents as docs_mod

    transcript = _CUT_VISIT + "\n\n[Hablante 1] Ha hecho dos cajas de pañales hoy."
    read = _fake_pipeline(monkeypatch, transcript)
    monkeypatch.setattr(settings, "llm_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "")
    _, doc_id = await _seed_consult({"locale": "es"})

    await docs_mod._process_document_inner(doc_id, "audio/webm", True)

    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, doc_id)
    assert read == [transcript]
    assert "summary" not in (doc.document_metadata or {})
    assert doc.raw_text == transcript


@pytest.mark.parametrize("locale", ["es", "en", "fr", "de", "fr-FR", None])
async def test_the_fallback_cut_line_is_the_summarizers_own(monkeypatch, locale):
    """The pipeline's fallback and the summarizer's cut line must never drift apart. A
    one-sentence cut makes the summarizer return its line alone, with no model call."""
    from adelia.config import settings
    from adelia.routers.documents import _cut_summary
    from adelia.workers.summarize import summarize_consultation

    monkeypatch.setattr(settings, "llm_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "")
    line = await summarize_consultation("[Hablante 1] Buenos", interrupted=True, locale=locale)
    assert _cut_summary(locale) == line
