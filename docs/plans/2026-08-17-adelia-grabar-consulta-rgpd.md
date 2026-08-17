# "Grabar consulta" RGPD — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Botón "Grabar consulta" que graba la visita médica en el navegador, con gate de consentimiento RGPD, transcripción diarizada vía Mistral Voxtral (UE) y borrado del audio tras transcribir.

**Architecture:** Reusa el pipeline de documentos existente (upload → transcribe → extract → chunk → embed). Se añade: provider STT conmutable (Voxtral default), campos de formulario en el upload (`source=consulta`, `profile_id`, `consent_policy_version`) que crean un `ConsentEvent` atómico, y tombstone diferido del blob de audio al completar el pipeline. Frontend: componente grabador con MediaRecorder detrás de un gate no saltable, más página pública `/profesionales` (transparencia art. 14).

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic + httpx (backend), Next.js 15 + next-intl + Tailwind v4 (frontend), Playwright (e2e), Mistral La Plateforme audio/transcriptions.

**Spec:** `docs/specs/2026-08-17-adelia-grabar-consulta-rgpd-design.md`

## Global Constraints

- Trabajar SIEMPRE en `~/dev/AdelIA` (clone limpio, rama `feat/consulta-recording`). NUNCA en la copia de Google Drive.
- Python: correr tests con `cd apps/api && uv run pytest`. Lint: `uv run ruff check .`
- Web: `pnpm --filter @adelia/web typecheck && pnpm --filter @adelia/web build` deben quedar verdes en cada task frontend.
- i18n: TODA clave nueva se añade en `es.json`, `en.json` y `fr.json` (paridad de leaf keys; hay test/convención de paridad).
- Migración nueva = `0015_consulta_recording` (head actual: `0014_subscriptions`).
- Los tests que requieren Postgres usan el patrón `pg_gate.py` existente; los que requieren API keys reales usan `pytest.mark.skipif` sobre `settings.*_api_key` (patrón `test_transcribe.py`).
- `CONSENT_POLICY_VERSION = "2026-08-17"` (constante compartida frontend; el backend la persiste opaca, no la valida contra una lista).
- Commits: mensaje convencional (`feat:`/`fix:`/`docs:`) + `Co-Authored-By: Claude` si aplica al flujo del ejecutor.

---

### Task 1: STT provider conmutable — Voxtral con diarización en `transcribe.py`

**Files:**
- Modify: `apps/api/adelia/config.py` (tras línea 38, junto a `openai_chat_model`)
- Modify: `apps/api/adelia/workers/transcribe.py`
- Test: `apps/api/tests/test_transcribe.py`

**Interfaces:**
- Consumes: `settings.mistral_api_key` (ya existe), patrón REST httpx de `workers/ocr.py`.
- Produces: `transcribe_audio(body: bytes, mime_type: str, *, diarize: bool = False) -> str` (firma que consume Task 4). Settings nuevos: `settings.stt_provider: str` (`"mistral" | "openai"`, default `"mistral"`), `settings.mistral_stt_model: str` (default `"voxtral-mini-latest"`).

- [ ] **Step 1: Write the failing tests**

Añadir a `apps/api/tests/test_transcribe.py`:

```python
import json

import httpx
import pytest

from adelia.config import settings
from adelia.workers import transcribe as transcribe_mod
from adelia.workers.transcribe import transcribe_audio


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


def _patch_mistral_post(monkeypatch, payload: dict, captured: dict):
    async def fake_post(self, url, **kwargs):
        captured["url"] = url
        captured["data"] = kwargs.get("data")
        captured["files"] = kwargs.get("files")
        return _FakeResponse(payload)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


async def test_mistral_plain_transcription(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    captured: dict = {}
    _patch_mistral_post(monkeypatch, {"text": "hola bebé"}, captured)

    result = await transcribe_audio(b"fake-audio", "audio/webm")

    assert result == "hola bebé"
    assert captured["data"]["model"] == settings.mistral_stt_model
    assert "diarize" not in captured["data"]


async def test_mistral_diarized_formats_speakers(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    captured: dict = {}
    payload = {
        "text": "ignored when segments have speakers",
        "segments": [
            {"speaker": "speaker_0", "text": "El peso está en el percentil 60."},
            {"speaker": "speaker_0", "text": "Todo normal."},
            {"speaker": "speaker_1", "text": "¿Y la vacuna de los 12 meses?"},
            {"speaker": "speaker_0", "text": "Se la ponemos hoy."},
        ],
    }
    _patch_mistral_post(monkeypatch, payload, captured)

    result = await transcribe_audio(b"fake-audio", "audio/webm", diarize=True)

    assert captured["data"]["diarize"] == "true"
    assert result == (
        "[Hablante 1] El peso está en el percentil 60. Todo normal.\n\n"
        "[Hablante 2] ¿Y la vacuna de los 12 meses?\n\n"
        "[Hablante 1] Se la ponemos hoy."
    )


async def test_mistral_diarize_without_speakers_falls_back_to_text(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    payload = {"text": "texto plano", "segments": [{"text": "texto plano"}]}
    _patch_mistral_post(monkeypatch, payload, {})

    result = await transcribe_audio(b"fake-audio", "audio/webm", diarize=True)

    assert result == "texto plano"


async def test_mistral_raises_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "")

    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
        await transcribe_audio(b"fake-audio", "audio/webm")


async def test_openai_provider_still_selected(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await transcribe_audio(b"fake-audio", "audio/wav")
```

Nota: los tests existentes del fichero (whisper live-gated y `test_transcribe_raises_without_api_key`) deben seguir pasando — el segundo hay que ajustarlo si asume provider OpenAI por defecto: añadirle `monkeypatch.setattr(settings, "stt_provider", "openai")`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && uv run pytest tests/test_transcribe.py -v`
Expected: FAIL — `transcribe_audio() got an unexpected keyword argument 'diarize'` / `AttributeError: stt_provider`.

- [ ] **Step 3: Implement**

`apps/api/adelia/config.py` — añadir tras `openai_chat_model` (línea 38):

```python
    # STT (speech-to-text). "mistral" = Voxtral (UE por defecto, diarización);
    # "openai" = whisper-1 (sin diarización). Voxtral reusa mistral_api_key.
    stt_provider: str = "mistral"  # "mistral" | "openai"
    mistral_stt_model: str = "voxtral-mini-latest"
```

`apps/api/adelia/workers/transcribe.py` — reescribir así (conserva `_ext_from_mime` y el código whisper actual como `_transcribe_openai`):

```python
import io

import httpx
from openai import AsyncOpenAI

from adelia.config import settings

MISTRAL_TRANSCRIBE_URL = "https://api.mistral.ai/v1/audio/transcriptions"


def _ext_from_mime(mime_type: str) -> str:
    return {
        "audio/wav": "wav",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/mp4": "m4a",
        "audio/x-m4a": "m4a",
        "audio/ogg": "ogg",
        "audio/webm": "webm",
        "audio/flac": "flac",
    }.get(mime_type, "wav")


def _format_diarized(segments: list[dict]) -> str:
    """Group consecutive same-speaker segments into '[Hablante N] …' blocks.

    Speaker labels from the API are opaque (e.g. 'speaker_0'); we map them to
    1, 2, … in order of first appearance. Diarization can't know WHO the
    doctor is — neutral labels, renaming is a v1.1 feature.
    """
    label_of: dict[object, int] = {}
    blocks: list[tuple[int, list[str]]] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        raw = seg.get("speaker")
        if raw not in label_of:
            label_of[raw] = len(label_of) + 1
        label = label_of[raw]
        if blocks and blocks[-1][0] == label:
            blocks[-1][1].append(text)
        else:
            blocks.append((label, [text]))
    return "\n\n".join(f"[Hablante {n}] {' '.join(parts)}" for n, parts in blocks)


async def _transcribe_mistral(body: bytes, mime_type: str, *, diarize: bool) -> str:
    """Mistral Voxtral via La Plateforme REST (same httpx pattern as ocr.py).

    Raises:
        RuntimeError: MISTRAL_API_KEY not set. Config error — do NOT retry.
        httpx.HTTPStatusError: non-2xx from the API. May be transient —
            caller retries with backoff (_with_retry covers httpx.HTTPError).
    """
    if not settings.mistral_api_key:
        raise RuntimeError("MISTRAL_API_KEY not set")

    bare_mime = mime_type.split(";")[0].strip()
    ext = _ext_from_mime(bare_mime)
    data: dict[str, str] = {"model": settings.mistral_stt_model}
    if diarize:
        data["diarize"] = "true"
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            MISTRAL_TRANSCRIBE_URL,
            headers={"Authorization": f"Bearer {settings.mistral_api_key}"},
            data=data,
            files={"file": (f"upload.{ext}", body, bare_mime)},
        )
        resp.raise_for_status()
    payload = resp.json()
    segments = payload.get("segments") or []
    if diarize and any(s.get("speaker") is not None for s in segments):
        return _format_diarized(segments)
    return payload.get("text") or ""


async def _transcribe_openai(body: bytes, mime_type: str) -> str:
    """OpenAI Whisper fallback (no diarization). Unchanged v0.1 behavior."""
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    ext = _ext_from_mime(mime_type)
    file_tuple = (f"upload.{ext}", io.BytesIO(body), mime_type)

    response = await client.audio.transcriptions.create(
        model="whisper-1",
        file=file_tuple,
        response_format="text",
    )
    return response if isinstance(response, str) else str(response)


async def transcribe_audio(body: bytes, mime_type: str, *, diarize: bool = False) -> str:
    """Transcribe audio via the configured STT provider.

    Args:
        body: raw audio bytes.
        mime_type: audio/* mime (";codecs=" suffix tolerated).
        diarize: label speakers ([Hablante N]) — Mistral only; ignored by
            the OpenAI provider.

    Returns:
        Transcript text. Empty string on silent audio.
    """
    if settings.stt_provider == "mistral":
        return await _transcribe_mistral(body, mime_type, diarize=diarize)
    return await _transcribe_openai(body, mime_type)
```

- [ ] **Step 4: Run tests**

Run: `cd apps/api && uv run pytest tests/test_transcribe.py -v && uv run ruff check adelia/workers/transcribe.py adelia/config.py`
Expected: PASS (los live-gated se saltan sin keys).

- [ ] **Step 5: Añadir test live-gated Voxtral** (verifica el contrato REAL de la API — el formato `segments/speaker` está escrito a partir de docs, no verificado):

```python
AUDIO_FIXTURE = Path(__file__).parent / "fixtures" / "sample.wav"


@pytest.mark.skipif(not settings.mistral_api_key, reason="MISTRAL_API_KEY not set")
async def test_voxtral_live_transcription(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "mistral")
    body = AUDIO_FIXTURE.read_bytes()
    result = await transcribe_audio(body, "audio/wav")
    assert isinstance(result, str)
```

(Si no existe `fixtures/sample.wav`, reusar el fixture del test whisper live existente en el mismo fichero.) Ejecutarlo con la key real cuando esté disponible; si la API devuelve un shape distinto para `diarize`, ajustar `_transcribe_mistral`/`_format_diarized` y los tests mocked ANTES de continuar — este es el punto de verificación del contrato.

- [ ] **Step 6: Commit**

```bash
git add apps/api/adelia/config.py apps/api/adelia/workers/transcribe.py apps/api/tests/test_transcribe.py
git commit -m "feat(stt): switchable provider — Voxtral (EU, diarize) default, whisper fallback"
```

---

### Task 2: MIME del navegador — normalización `;codecs=` + tipos MediaRecorder

**Files:**
- Modify: `apps/api/adelia/routers/documents.py:37` (ALLOWED_MIME) y `:236-237` (check en `upload_document`)
- Test: `apps/api/tests/test_documents_upload.py` (crear si no existe un test de router de upload; si existe `test_documents*.py`, añadir ahí)

**Interfaces:**
- Produces: `normalize_mime(content_type: str | None) -> str` en `documents.py` (Task 4 lo reusa); `ALLOWED_MIME` ampliado.

- [ ] **Step 1: Write the failing tests**

```python
from adelia.routers.documents import ALLOWED_MIME, normalize_mime


def test_normalize_strips_codecs_suffix():
    assert normalize_mime("audio/webm;codecs=opus") == "audio/webm"
    assert normalize_mime("audio/mp4; codecs=mp4a.40.2") == "audio/mp4"
    assert normalize_mime("application/pdf") == "application/pdf"
    assert normalize_mime(None) == ""


def test_browser_recording_mimes_allowed():
    for mime in ("audio/webm", "audio/mp4", "audio/ogg", "audio/x-m4a", "audio/flac"):
        assert mime in ALLOWED_MIME
```

- [ ] **Step 2: Run to verify fail**

Run: `cd apps/api && uv run pytest tests/test_documents_upload.py -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_mime'`.

- [ ] **Step 3: Implement**

En `documents.py`:

```python
ALLOWED_MIME = {
    "application/pdf", "image/png", "image/jpeg",
    "audio/mpeg", "audio/wav", "audio/webm", "audio/mp4",
    "audio/ogg", "audio/x-m4a", "audio/flac",
}


def normalize_mime(content_type: str | None) -> str:
    """MediaRecorder emits 'audio/webm;codecs=opus' — compare/store bare type."""
    return (content_type or "").split(";")[0].strip()
```

Y en `upload_document`, sustituir el uso directo de `file.content_type`:

```python
    content_type = normalize_mime(file.content_type)
    if content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail=f"Unsupported mime: {file.content_type}")
```

…y usar `content_type` (no `file.content_type`) en `storage.put_object(...)`, en `Document(mime_type=...)` y en `background.add_task(process_document, doc.id, content_type)`.

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_documents_upload.py tests/test_transcribe.py -v` → PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(upload): accept MediaRecorder audio mimes, normalize ;codecs= suffix"`

---

### Task 3: Migración 0015 + ORM — `consent_events`, `source='consulta'`, `profile_id`, `not_before`

**Files:**
- Create: `apps/api/alembic/versions/0015_consulta_recording.py`
- Modify: `apps/api/adelia/models.py` (Document `__table_args__` + columnas `profile_id`; clase nueva `ConsentEvent`; `BlobTombstone.not_before`)
- Test: `apps/api/tests/test_consent_models.py`

**Interfaces:**
- Produces: `ConsentEvent` ORM (campos: `id, user_id, profile_id, document_id, event_type, policy_version, locale, created_at`), `Document.profile_id`, `Entity.profile_id`, `Chunk.profile_id` (columnas YA existen en BD desde la migración 0006 — solo se declaran en ORM), `BlobTombstone.not_before`. Constantes `CONSENT_EVENT_TYPES = ("recording_informed_professional", "recording_declined")`.

- [ ] **Step 1: Write the failing test** (`tests/test_consent_models.py`, PG-gated con el patrón `pg_gate`):

```python
import uuid

import pytest

from adelia.models import ConsentEvent, Document
from tests.pg_gate import pg_required  # ajustar al helper real de pg_gate.py


@pg_required
async def test_consent_event_roundtrip(db_session, seeded_user):
    ev = ConsentEvent(
        user_id=seeded_user.id,
        event_type="recording_informed_professional",
        policy_version="2026-08-17",
        locale="es",
    )
    db_session.add(ev)
    await db_session.commit()
    await db_session.refresh(ev)
    assert ev.id is not None
    assert ev.created_at is not None


@pg_required
async def test_document_source_consulta_allowed(db_session, seeded_user):
    doc = Document(
        user_id=seeded_user.id, source="consulta",
        mime_type="audio/webm", s3_key=f"users/{seeded_user.id}/{uuid.uuid4()}-c.webm",
    )
    db_session.add(doc)
    await db_session.commit()  # no IntegrityError => CHECK ampliado
```

(Adaptar los nombres de fixtures a los reales de `conftest.py`/`db_helpers.py` — el implementador debe abrir esos dos ficheros antes de escribir el test.)

- [ ] **Step 2: Run** — sin Postgres se salta (gated); con docker compose dev: FAIL (`relation consent_events does not exist` / CHECK violation).

- [ ] **Step 3: Migración** `apps/api/alembic/versions/0015_consulta_recording.py`:

```python
"""Consulta recording: consent_events, source='consulta', tombstone grace.

Revision ID: 0015_consulta_recording
Revises: 0014_subscriptions

consent_events is the append-only RGPD accountability log for consultation
recordings (who informed the professional, when, under which policy text).
Deliberately minimal: NO doctor name/center (data minimization). Deleted in
cascade with the user account. blob_tombstones.not_before adds a deferred
deletion window (48h audio grace) — NULL keeps today's immediate semantics.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_consulta_recording"
down_revision: Union[str, None] = "0014_subscriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("documents_source_check", "documents", type_="check")
    op.create_check_constraint(
        "documents_source_check", "documents", "source IN ('web','manual','consulta')"
    )
    op.create_table(
        "consent_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "profile_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "document_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("locale", sa.String(8), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('recording_informed_professional','recording_declined')",
            name="ck_consent_events_type",
        ),
    )
    op.create_index("ix_consent_events_user_id", "consent_events", ["user_id"])
    op.add_column(
        "blob_tombstones",
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blob_tombstones", "not_before")
    op.drop_index("ix_consent_events_user_id", table_name="consent_events")
    op.drop_table("consent_events")
    op.drop_constraint("documents_source_check", "documents", type_="check")
    op.create_check_constraint(
        "documents_source_check", "documents", "source IN ('web','manual')"
    )
```

- [ ] **Step 4: ORM en `models.py`**

En `Document`: cambiar el CheckConstraint a `"source IN ('web','manual','consulta')"` y añadir (la columna existe en BD desde 0006, solo se declara):

```python
    profile_id = Column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
```

Añadir la misma declaración `profile_id` a `Entity` y `Chunk` (también creadas por 0006). En `BlobTombstone`:

```python
    not_before = Column(DateTime(timezone=True))  # NULL = delete on next sweep
```

Clase nueva (junto a BlobTombstone):

```python
CONSENT_EVENT_TYPES = ("recording_informed_professional", "recording_declined")


class ConsentEvent(Base):
    """Append-only RGPD accountability log for consultation recordings.

    Minimization by design: no doctor name, no clinic, no content — the
    professional's identity only exists (if mentioned) inside the transcript.
    Cascade-deleted with the account (art. 5.2 accountability while it lives).
    """
    __tablename__ = "consent_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    profile_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="SET NULL"))
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"))
    event_type = Column(String, nullable=False)
    policy_version = Column(String(64), nullable=False)
    locale = Column(String(8), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('recording_informed_professional','recording_declined')",
            name="ck_consent_events_type",
        ),
    )
```

- [ ] **Step 5: Run** — `uv run pytest tests/test_consent_models.py -v` (con PG: PASS tras `uv run alembic upgrade head`); sin PG: skipped. `uv run ruff check adelia/models.py` limpio.

- [ ] **Step 6: Commit** — `git commit -m "feat(db): consent_events log + source=consulta + tombstone grace window (0015)"`

---

### Task 4: Upload de consulta — form fields, ConsentEvent atómico, diarize + profile_id en el pipeline

**Files:**
- Modify: `apps/api/adelia/routers/documents.py` (firma `upload_document`, `process_document`, `_process_document_inner`)
- Test: `apps/api/tests/test_documents_upload.py`

**Interfaces:**
- Consumes: `normalize_mime` (Task 2), `ConsentEvent` (Task 3), `transcribe_audio(..., diarize=)` (Task 1).
- Produces: `upload_document` acepta `Form` fields `profile_id: uuid|None`, `source: str = "web"`, `consent_policy_version: str|None`, `locale: str = "es"`. `process_document(document_id, mime_type, is_consulta: bool = False)` — Task 5 extiende su final.

- [ ] **Step 1: Write the failing tests** (TestClient + monkeypatch de storage/db según patrón de `test_documents*`/`conftest.py` — el implementador replica cómo los tests de router existentes mockean `S3Storage` y sesión):

```python
async def test_upload_consulta_requires_consent(client, auth_headers):
    resp = await client.post(
        "/documents",
        headers=auth_headers,
        files={"file": ("c.webm", b"audio", "audio/webm;codecs=opus")},
        data={"source": "consulta"},
    )
    assert resp.status_code == 400
    assert "consent" in resp.json()["detail"].lower()


async def test_upload_rejects_unknown_source(client, auth_headers):
    resp = await client.post(
        "/documents",
        headers=auth_headers,
        files={"file": ("c.webm", b"audio", "audio/webm")},
        data={"source": "hacker"},
    )
    assert resp.status_code == 400


@pg_required
async def test_upload_consulta_creates_consent_event_atomically(client, auth_headers, db_session):
    resp = await client.post(
        "/documents",
        headers=auth_headers,
        files={"file": ("c.webm", b"audio", "audio/webm;codecs=opus")},
        data={
            "source": "consulta",
            "consent_policy_version": "2026-08-17",
            "locale": "es",
        },
    )
    assert resp.status_code == 201
    doc_id = resp.json()["id"]
    events = (await db_session.execute(
        sa.select(ConsentEvent).where(ConsentEvent.document_id == uuid.UUID(doc_id))
    )).scalars().all()
    assert len(events) == 1
    assert events[0].event_type == "recording_informed_professional"
    assert events[0].policy_version == "2026-08-17"
```

- [ ] **Step 2: Run to verify fail** — 400-tests fallan (hoy `source` form field ni existe → el endpoint lo ignora y devuelve 201).

- [ ] **Step 3: Implement** — en `upload_document`:

```python
VALID_SOURCES = {"web", "manual", "consulta"}


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background: BackgroundTasks,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    file: UploadFile = File(...),
    profile_id: Annotated[uuid.UUID | None, Form()] = None,
    source: Annotated[str, Form()] = "web",
    consent_policy_version: Annotated[str | None, Form()] = None,
    locale: Annotated[str, Form()] = "es",
):
    content_type = normalize_mime(file.content_type)
    if content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail=f"Unsupported mime: {file.content_type}")
    if source not in VALID_SOURCES:
        raise HTTPException(status_code=400, detail=f"Invalid source: {source}")
    is_consulta = source == "consulta"
    if is_consulta and not _is_audio(content_type):
        raise HTTPException(status_code=400, detail="Consulta recordings must be audio")
    if is_consulta and not consent_policy_version:
        raise HTTPException(
            status_code=400,
            detail="consent_policy_version required for consulta recordings",
        )
    # … (body read, size check, s3 put: sin cambios, pero usando content_type) …

    doc = Document(
        user_id=user_id,
        source=source,
        mime_type=content_type,
        s3_key=s3_key,
        profile_id=profile_id,
    )
    async with AsyncSessionLocal() as db:
        db.add(doc)
        if is_consulta:
            db.add(ConsentEvent(
                user_id=user_id,
                profile_id=profile_id,
                document_id=doc.id,
                event_type="recording_informed_professional",
                policy_version=consent_policy_version,
                locale=locale[:8],
            ))
        # … (commit + compensación orphan blob: sin cambios) …

    background.add_task(process_document, doc.id, content_type, is_consulta)
    return _doc_to_out(doc)
```

(`from fastapi import Form` al import; `from adelia.models import ConsentEvent` al import de models.)

En el pipeline:

```python
async def process_document(document_id: uuid.UUID, mime_type: str, is_consulta: bool = False) -> None:
    async with _get_processing_semaphore():
        await _process_document_inner(document_id, mime_type, is_consulta)
```

En `_process_document_inner(document_id, mime_type, is_consulta: bool = False)`:
- en la primera lectura corta, capturar también `profile_id = doc.profile_id`
- stage transcribe: `raw_text = await _with_retry("transcribe", lambda: transcribe_audio(body, mime_type, diarize=is_consulta))`
- pasar `profile_id=profile_id` al construir cada `Entity(...)` y cada `Chunk(...)`.

- [ ] **Step 4: Run** — `uv run pytest tests/test_documents_upload.py tests/test_transcribe.py -v` → PASS; suite completa `uv run pytest` sin regresiones (los tests de upload existentes siguen verdes porque los defaults `source="web"` mantienen el comportamiento actual).

- [ ] **Step 5: Commit** — `git commit -m "feat(upload): consulta source with atomic consent event, diarized transcription, profile propagation"`

---

### Task 5: Borrado del audio — tombstone con gracia 48h y sweep filtrado

**Files:**
- Modify: `apps/api/adelia/routers/users.py:53-70` (`sweep_blob_tombstones`)
- Modify: `apps/api/adelia/routers/documents.py` (final de `_process_document_inner` + `process_document`)
- Test: `apps/api/tests/test_audio_retention.py`

**Interfaces:**
- Consumes: `BlobTombstone.not_before` (Task 3), `process_document(..., is_consulta)` (Task 4).
- Produces: al completar el pipeline de una consulta, el blob queda tombstoned (`not_before = now + 48h` en éxito, `now + 7 días` si la transcripción falló) y `document_metadata["audio_deleted_scheduled"] = True`; el sweep ignora tombstones futuros.

- [ ] **Step 1: Write the failing tests** (PG-gated; mock de `storage.delete_object`):

```python
@pg_required
async def test_sweep_skips_future_tombstones(db_session, monkeypatch):
    deleted: list[str] = []

    async def fake_delete(key):
        deleted.append(key)

    monkeypatch.setattr("adelia.routers.users.storage.delete_object", fake_delete)
    now = datetime.now(timezone.utc)
    db_session.add_all([
        BlobTombstone(s3_key="users/x/old-blob", not_before=None),
        BlobTombstone(s3_key="users/x/expired", not_before=now - timedelta(hours=1)),
        BlobTombstone(s3_key="users/x/fresh-audio", not_before=now + timedelta(hours=48)),
    ])
    await db_session.commit()

    await sweep_blob_tombstones()

    assert set(deleted) == {"users/x/old-blob", "users/x/expired"}


@pg_required
async def test_consulta_pipeline_schedules_audio_deletion(db_session, seeded_user, monkeypatch):
    # mock transcribe para no llamar a la API; mock storage.get_object
    ...  # sembrar Document(source="consulta"), correr process_document(doc.id, "audio/webm", True)
    row = (await db_session.execute(
        sa.select(BlobTombstone).where(BlobTombstone.s3_key == doc.s3_key)
    )).scalar_one()
    assert row.not_before is not None
    refreshed = await db_session.get(Document, doc.id)
    assert refreshed.document_metadata["audio_deleted_scheduled"] is True
```

(El segundo test replica el patrón de mocks del pipeline usado por los tests de orquestador existentes — el implementador abre `tests/test_concurrency.py` o el test de pipeline más parecido y copia el andamiaje de mocks.)

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement**

`users.py` — filtrar el select:

```python
        now = datetime.now(timezone.utc)
        result = await session.execute(
            sa.select(BlobTombstone.s3_key).where(
                sa.or_(BlobTombstone.not_before.is_(None), BlobTombstone.not_before <= now)
            )
        )
```

`documents.py` — en el bloque final de escritura de `_process_document_inner`, tras `doc.processed_at = ...` y antes del `commit()`:

```python
        if is_consulta:
            grace = timedelta(hours=48) if raw_text else timedelta(days=7)
            session.add(BlobTombstone(
                s3_key=s3_key,
                not_before=datetime.now(timezone.utc) + grace,
            ))
            doc.document_metadata = {
                **(doc.document_metadata or {}),
                "audio_deleted_scheduled": True,
            }
```

(`from datetime import timedelta` + `from adelia.models import BlobTombstone` en imports.) Y en `process_document`, tras liberar el semáforo, disparar un sweep oportunista para que los tombstones vencidos no esperen al próximo boot:

```python
async def process_document(document_id: uuid.UUID, mime_type: str, is_consulta: bool = False) -> None:
    async with _get_processing_semaphore():
        await _process_document_inner(document_id, mime_type, is_consulta)
    if is_consulta:
        from adelia.routers.users import sweep_blob_tombstones
        try:
            await sweep_blob_tombstones()
        except Exception:  # noqa: BLE001 — sweep retries at next boot/upload
            logger.exception("opportunistic tombstone sweep failed")
```

- [ ] **Step 4: Run** — `uv run pytest tests/test_audio_retention.py -v` + suite completa → PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(rgpd): audio blob tombstoned after transcription (48h grace, 7d on failure)"`

---

### Task 6: Endpoint `POST /consent-events` (rechazo del profesional) + proxy allow-list

**Files:**
- Create: `apps/api/adelia/routers/consent.py`
- Modify: `apps/api/adelia/main.py:156-167` (include_router), `apps/web/app/api/backend/[...path]/route.ts:18` (ALLOWED_PREFIXES)
- Test: `apps/api/tests/test_consent_router.py`

**Interfaces:**
- Consumes: `ConsentEvent` (Task 3), `get_current_user_id` (patrón de todos los routers).
- Produces: `POST /consent-events` body JSON `{event_type: "recording_declined", profile_id?: uuid, policy_version: str, locale: str}` → 201 `{id, created_at}`. El frontend (Task 8) lo llama desde el kill switch.

- [ ] **Step 1: Write the failing tests**

```python
async def test_declined_event_created(client, auth_headers):
    resp = await client.post(
        "/consent-events",
        headers=auth_headers,
        json={"event_type": "recording_declined", "policy_version": "2026-08-17", "locale": "es"},
    )
    assert resp.status_code == 201
    assert "id" in resp.json()


async def test_informed_type_rejected_here(client, auth_headers):
    # 'informed' solo se crea embebido en el upload — este endpoint es solo declined
    resp = await client.post(
        "/consent-events",
        headers=auth_headers,
        json={"event_type": "recording_informed_professional", "policy_version": "x", "locale": "es"},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run to verify fail** (404: router no existe).

- [ ] **Step 3: Implement** `apps/api/adelia/routers/consent.py`:

```python
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from adelia.auth import get_current_user_id
from adelia.db import AsyncSessionLocal
from adelia.models import ConsentEvent

router = APIRouter(prefix="/consent-events", tags=["consent"])


class DeclinedEventIn(BaseModel):
    # Only 'declined' is accepted here: 'informed' events are created
    # atomically with the document row inside POST /documents.
    event_type: Literal["recording_declined"]
    profile_id: uuid.UUID | None = None
    policy_version: str = Field(min_length=1, max_length=64)
    locale: str = Field(min_length=2, max_length=8)


class ConsentEventOut(BaseModel):
    id: uuid.UUID
    created_at: str


@router.post("", response_model=ConsentEventOut, status_code=status.HTTP_201_CREATED)
async def create_declined_event(
    payload: DeclinedEventIn,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
    ev = ConsentEvent(
        user_id=user_id,
        profile_id=payload.profile_id,
        event_type=payload.event_type,
        policy_version=payload.policy_version,
        locale=payload.locale,
    )
    async with AsyncSessionLocal() as db:
        db.add(ev)
        await db.commit()
        await db.refresh(ev)
    return ConsentEventOut(id=ev.id, created_at=ev.created_at.isoformat())
```

`main.py`: `from adelia.routers import consent` (en el import existente) + `app.include_router(consent.router)`.
`route.ts`: añadir `"consent-events",` a `ALLOWED_PREFIXES`.

- [ ] **Step 4: Run** — `uv run pytest tests/test_consent_router.py -v` → PASS; `pnpm --filter @adelia/web typecheck` verde.

- [ ] **Step 5: Commit** — `git commit -m "feat(rgpd): consent-events endpoint for declined recordings + proxy allow-list"`

---

### Task 7: Frontend base — Permissions-Policy micrófono + claves i18n

**Files:**
- Modify: `apps/web/next.config.ts:33`
- Modify: `apps/web/messages/es.json`, `apps/web/messages/en.json`, `apps/web/messages/fr.json`

**Interfaces:**
- Produces: micrófono habilitado same-origin; namespace `consulta.record.*` y `professionals.*` que consumen Tasks 8-9.

- [ ] **Step 1: Permissions-Policy** — en `next.config.ts` línea 33:

```typescript
          { key: "Permissions-Policy", value: "camera=(), microphone=(self), geolocation=()" },
```

(Hoy `microphone=()` bloquea getUserMedia en la PROPIA app — y muy probablemente el dictado Web Speech del Modo Consulta actual. Bugfix además de prerequisito.)

- [ ] **Step 2: Claves i18n.** Añadir en `es.json` dentro del namespace `consulta` existente la subclave `record`, y el namespace raíz `professionals`. Contenido ES (en/fr = traducción fiel; fr con tuteo de marca; mantener anglicismos de marca ya usados):

```json
"record": {
  "entryTitle": "Grabar la consulta",
  "entryBody": "Graba la visita completa y AdelIA la transcribe al historial. El audio se elimina después.",
  "title": "Grabar consulta",
  "profileLabel": "¿De quién es la consulta?",
  "scriptLabel": "Díselo así al profesional:",
  "scriptText": "“¿Le parece bien que grabe la consulta para el historial de mi bebé?”",
  "checkboxLabel": "He informado al profesional y no se opone",
  "showInfo": "Mostrar información para profesionales",
  "legalNoteEs": "Grabar tu propia consulta es legal en España. Compartirla o difundirla, no. Uso personal y familiar.",
  "legalNoteFr": "Graba siempre de forma anunciada: en Francia la grabación oculta puede ser delito (art. 226-1).",
  "legalNoteGeneric": "Graba siempre de forma anunciada y para uso personal y familiar.",
  "startDisabledHint": "Marca la casilla de arriba para poder grabar",
  "start": "Grabar",
  "recording": "Grabando",
  "askNow": "Pregúntaselo ahora en voz alta: así queda su OK al inicio de la grabación",
  "keepScreenOn": "Mantén la pantalla encendida durante la grabación",
  "stop": "Terminar y guardar",
  "decline": "El profesional se opone",
  "declineDone": "Grabación descartada. No se ha guardado nada.",
  "declineFallback": "Puedes seguir con el modo dictado, sin grabar.",
  "uploading": "Subiendo…",
  "transcribing": "Transcribiendo la consulta…",
  "done": "Consulta guardada en el historial",
  "audioDeleted": "El audio se elimina tras la transcripción. Solo conservamos el texto.",
  "viewDocument": "Ver la transcripción",
  "micDenied": "AdelIA no tiene permiso de micrófono. Actívalo en tu navegador y recarga.",
  "error": "No se pudo procesar la grabación. El audio queda guardado unos días para reintentar.",
  "retry": "Reintentar"
}
```

```json
"professionals": {
  "title": "Información para profesionales sanitarios",
  "intro": "Una familia usa AdelIA para guardar el historial de salud de su bebé. Con su permiso explícito, puede grabar la consulta para transcribirla a ese historial.",
  "whatTitle": "Qué se graba y para qué",
  "whatBody": "El audio de la consulta se transcribe con IA y se convierte en texto dentro del historial privado del bebé. Finalidad exclusivamente personal y familiar: recordar sus indicaciones con fidelidad. La difusión está prohibida por las condiciones de uso.",
  "whereTitle": "Dónde se procesa",
  "whereBody": "Los datos se alojan y procesan en la Unión Europea. La transcripción la realiza Mistral AI (Francia) como encargado del tratamiento. Sus datos no se usan para entrenar modelos.",
  "retentionTitle": "Cuánto se conserva",
  "retentionBody": "El audio se elimina automáticamente tras la transcripción (máximo 48 horas). Solo se conserva el texto, dentro del historial privado de la familia.",
  "rightsTitle": "Sus derechos",
  "rightsBody": "Su voz es un dato personal. Puede oponerse a la grabación en cualquier momento (la app descarta el audio al instante) y ejercer sus derechos RGPD de acceso, rectificación o supresión.",
  "contactTitle": "Contacto",
  "contactBody": "security@godi.ai — responderemos en un plazo máximo de 30 días."
}
```

- [ ] **Step 3: Verificar paridad** — Run: `pnpm --filter @adelia/web typecheck && pnpm --filter @adelia/web build`. Además comprobar paridad de leaf keys es/en/fr (script/test de paridad existente en el repo; si es manual: `node -e` comparando keys planas).

- [ ] **Step 4: Commit** — `git commit -m "feat(web): enable same-origin microphone + consulta.record/professionals i18n (es/en/fr)"`

---

### Task 8: Componente grabador + página `/dashboard/consulta/grabar` + entradas

**Files:**
- Create: `apps/web/components/consulta-recorder.tsx`
- Create: `apps/web/app/[locale]/dashboard/consulta/grabar/page.tsx`
- Modify: `apps/web/app/[locale]/dashboard/consulta/page.tsx` (card de entrada), `apps/web/components/upload-zone.tsx` o su página (enlace "¿Estás en la consulta? Grábala")

**Interfaces:**
- Consumes: `POST /api/backend/documents` (FormData con `source=consulta`, `profile_id`, `consent_policy_version`, `locale`), `POST /api/backend/consent-events` (Task 6), `GET /api/backend/documents/{id}` (polling estado), `useProfiles()` de `apps/web/lib/profile-context.tsx` (`{ profiles, activeId, setActiveId }`), claves `consulta.record.*` (Task 7), clases `.ad-btn`, `.ad-btn-primary`, `.ad-btn-danger`, `.ad-btn-ghost`, `.ad-card` de `globals.css`.
- Produces: `<ConsultaRecorder locale={locale} />` client component.

- [ ] **Step 1: Component** — `apps/web/components/consulta-recorder.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { AlertCircle, CheckCircle2, Loader2, Mic, Square, XCircle } from "lucide-react";

import { useProfiles } from "@/lib/profile-context";

export const CONSENT_POLICY_VERSION = "2026-08-17";

const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

type Phase = "gate" | "recording" | "uploading" | "transcribing" | "done" | "declined" | "error";

function pickMime(): string {
  if (typeof MediaRecorder === "undefined") return "";
  return MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m)) ?? "";
}

export function ConsultaRecorder() {
  const t = useTranslations("consulta.record");
  const locale = useLocale();
  const { profiles, activeId, setActiveId } = useProfiles();

  const [phase, setPhase] = useState<Phase>("gate");
  const [informed, setInformed] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [docId, setDocId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const wakeLockRef = useRef<{ release(): Promise<void> } | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const discardRef = useRef(false);

  // Screen wake lock: iOS suspends MediaRecorder when the screen locks.
  async function acquireWakeLock() {
    try {
      const wl = await (navigator as unknown as {
        wakeLock?: { request(type: "screen"): Promise<{ release(): Promise<void> }> };
      }).wakeLock?.request("screen");
      if (wl) wakeLockRef.current = wl;
    } catch {
      /* unsupported — the on-screen hint still tells the mom */
    }
  }

  function cleanup() {
    timerRef.current && clearInterval(timerRef.current);
    timerRef.current = null;
    streamRef.current?.getTracks().forEach((tr) => tr.stop());
    streamRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    wakeLockRef.current?.release().catch(() => {});
    wakeLockRef.current = null;
  }

  useEffect(() => () => cleanup(), []);

  async function start() {
    setError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch {
      setError(t("micDenied"));
      return;
    }
    streamRef.current = stream;
    chunksRef.current = [];
    discardRef.current = false;

    const mime = pickMime();
    const rec = new MediaRecorder(stream, {
      ...(mime ? { mimeType: mime } : {}),
      audioBitsPerSecond: 32_000,
    });
    recorderRef.current = rec;
    rec.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    rec.onstop = () => {
      cleanup();
      if (discardRef.current) {
        chunksRef.current = [];
        return;
      }
      void upload();
    };
    rec.start(10_000); // 10s timeslice: partial data survives a crash

    await acquireWakeLock();
    setElapsed(0);
    timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);

    // Live input level so the mom sees it's actually capturing.
    const ctx = new AudioContext();
    audioCtxRef.current = ctx;
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const buf = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      if (!audioCtxRef.current) return;
      analyser.getByteFrequencyData(buf);
      setLevel(Math.min(100, Math.round((buf.reduce((a, b) => a + b, 0) / buf.length / 255) * 300)));
      requestAnimationFrame(tick);
    };
    tick();

    setPhase("recording");
  }

  function stop() {
    recorderRef.current?.stop();
    setPhase("uploading");
  }

  function decline() {
    discardRef.current = true;
    recorderRef.current?.stop();
    setPhase("declined");
    void fetch("/api/backend/consent-events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_type: "recording_declined",
        profile_id: activeId,
        policy_version: CONSENT_POLICY_VERSION,
        locale,
      }),
    }).catch(() => {});
  }

  async function upload() {
    const mime = recorderRef.current?.mimeType || "audio/webm";
    const bare = mime.split(";")[0];
    const ext = bare === "audio/mp4" ? "m4a" : bare.split("/")[1];
    const blob = new Blob(chunksRef.current, { type: mime });
    const fd = new FormData();
    fd.append("file", blob, `consulta-${new Date().toISOString().slice(0, 10)}.${ext}`);
    if (activeId) fd.append("profile_id", activeId);
    fd.append("source", "consulta");
    fd.append("consent_policy_version", CONSENT_POLICY_VERSION);
    fd.append("locale", locale);
    try {
      const res = await fetch("/api/backend/documents", { method: "POST", body: fd });
      if (!res.ok) throw new Error(`status ${res.status}`);
      const doc = (await res.json()) as { id: string };
      setDocId(doc.id);
      setPhase("transcribing");
      poll(doc.id);
    } catch {
      setError(t("error"));
      setPhase("error");
    }
  }

  function poll(id: string) {
    const iv = setInterval(async () => {
      try {
        const res = await fetch(`/api/backend/documents/${id}`);
        if (!res.ok) return;
        const doc = (await res.json()) as { status: string };
        if (doc.status === "ready") {
          clearInterval(iv);
          setPhase("done");
        } else if (doc.status === "failed") {
          clearInterval(iv);
          setError(t("error"));
          setPhase("error");
        }
      } catch {
        /* transient — keep polling */
      }
    }, 3000);
  }

  const legalNote =
    locale === "es" ? t("legalNoteEs") : locale === "fr" ? t("legalNoteFr") : t("legalNoteGeneric");
  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(elapsed % 60).padStart(2, "0");

  if (phase === "gate") {
    return (
      <div className="ad-card space-y-4 p-6">
        <h1 className="text-xl font-semibold">{t("title")}</h1>
        {profiles.length > 1 && (
          <label className="block space-y-1">
            <span className="text-sm font-medium">{t("profileLabel")}</span>
            <select
              className="w-full rounded-lg border p-2"
              value={activeId ?? ""}
              onChange={(e) => setActiveId(e.target.value)}
            >
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>{p.display_name}</option>
              ))}
            </select>
          </label>
        )}
        <div>
          <p className="text-sm font-medium">{t("scriptLabel")}</p>
          <p className="mt-1 text-lg">{t("scriptText")}</p>
        </div>
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            checked={informed}
            onChange={(e) => setInformed(e.target.checked)}
            className="mt-1 h-5 w-5"
          />
          <span>{t("checkboxLabel")}</span>
        </label>
        <Link href={`/${locale}/profesionales`} target="_blank" className="block text-sm underline">
          {t("showInfo")}
        </Link>
        <p className="text-xs opacity-70">{legalNote}</p>
        {error && (
          <p role="alert" className="flex items-center gap-2 text-sm text-red-600">
            <AlertCircle className="h-4 w-4" /> {error}
          </p>
        )}
        <button
          type="button"
          className="ad-btn ad-btn-primary w-full"
          disabled={!informed}
          onClick={start}
        >
          <Mic className="h-5 w-5" /> {t("start")}
        </button>
        {!informed && <p className="text-center text-xs opacity-70">{t("startDisabledHint")}</p>}
      </div>
    );
  }

  if (phase === "recording") {
    return (
      <div className="ad-card space-y-4 p-6">
        <div
          role="status"
          className="flex items-center justify-between rounded-lg bg-red-600 px-4 py-3 text-white"
        >
          <span className="flex items-center gap-2 font-semibold">
            <span className="h-3 w-3 animate-pulse rounded-full bg-white" />
            {t("recording")} {mm}:{ss}
          </span>
          <span className="h-2 w-24 overflow-hidden rounded bg-red-800">
            <span className="block h-full bg-white transition-all" style={{ width: `${level}%` }} />
          </span>
        </div>
        {elapsed < 15 && <p className="text-sm">{t("askNow")}</p>}
        <p className="text-xs opacity-70">{t("keepScreenOn")}</p>
        <button type="button" className="ad-btn ad-btn-primary w-full" onClick={stop}>
          <Square className="h-5 w-5" /> {t("stop")}
        </button>
        <button type="button" className="ad-btn ad-btn-danger w-full" onClick={decline}>
          <XCircle className="h-5 w-5" /> {t("decline")}
        </button>
      </div>
    );
  }

  if (phase === "declined") {
    return (
      <div className="ad-card space-y-3 p-6 text-center">
        <p className="font-medium">{t("declineDone")}</p>
        <Link href={`/${locale}/dashboard/consulta`} className="ad-btn ad-btn-ghost">
          {t("declineFallback")}
        </Link>
      </div>
    );
  }

  if (phase === "uploading" || phase === "transcribing") {
    return (
      <div className="ad-card space-y-3 p-6 text-center" role="status">
        <Loader2 className="mx-auto h-8 w-8 animate-spin" />
        <p>{phase === "uploading" ? t("uploading") : t("transcribing")}</p>
        <p className="text-xs opacity-70">{t("audioDeleted")}</p>
      </div>
    );
  }

  if (phase === "done") {
    return (
      <div className="ad-card space-y-3 p-6 text-center">
        <CheckCircle2 className="mx-auto h-8 w-8 text-green-600" />
        <p className="font-medium">{t("done")}</p>
        <p className="text-sm opacity-80">{t("audioDeleted")}</p>
        {docId && (
          <Link href={`/${locale}/dashboard/documents/${docId}`} className="ad-btn ad-btn-primary">
            {t("viewDocument")}
          </Link>
        )}
      </div>
    );
  }

  return (
    <div className="ad-card space-y-3 p-6 text-center">
      <p role="alert" className="text-red-600">{error}</p>
      <button type="button" className="ad-btn ad-btn-ghost" onClick={() => setPhase("gate")}>
        {t("retry")}
      </button>
    </div>
  );
}
```

Notas de adaptación obligadas (verificar contra el código real, no asumir): la ruta del detalle de documento (`/dashboard/documents/[id]` — confirmar en `app/[locale]/dashboard/documents/`), el shape real de `useProfiles`/`Profile` en `profile-context.tsx` (nombre del hook y de `display_name`), y si `GET /documents/{id}` devuelve `status` (lo deriva `derive_status` — sí, campo `status` en `DocumentOut`).

- [ ] **Step 2: Page** — `apps/web/app/[locale]/dashboard/consulta/grabar/page.tsx`:

```tsx
import { ConsultaRecorder } from "@/components/consulta-recorder";

export default function GrabarConsultaPage() {
  return (
    <main className="mx-auto max-w-lg p-4">
      <ConsultaRecorder />
    </main>
  );
}
```

(Seguir el patrón real de las pages hermanas — si `consulta/page.tsx` exporta `generateMetadata` o recibe `params.locale`, replicarlo.)

- [ ] **Step 3: Entradas** — en `dashboard/consulta/page.tsx` añadir card superior con `t("record.entryTitle")` / `t("record.entryBody")` y link a `consulta/grabar` (clases `.ad-card` + `.ad-btn-accent`, patrón visual de las cards existentes de esa página). En la página de upload, un enlace secundario al mismo destino.

- [ ] **Step 4: Verify** — `pnpm --filter @adelia/web typecheck && pnpm --filter @adelia/web build` verdes. Smoke manual: `pnpm dev` + Chrome → `/es/dashboard/consulta/grabar` → checkbox habilita Grabar → banner rojo + timer + nivel → Parar sube y muestra "Transcribiendo…" (con backend dev corriendo).

- [ ] **Step 5: Commit** — `git commit -m "feat(web): consulta recorder — consent gate, recording banner, kill switch, upload+poll"`

---

### Task 9: Página pública `/profesionales`

**Files:**
- Create: `apps/web/app/[locale]/profesionales/page.tsx`

**Interfaces:**
- Consumes: namespace `professionals.*` (Task 7).
- Produces: página estática pública (fuera de `dashboard/` → sin guard de auth, como la landing).

- [ ] **Step 1: Implement**

```tsx
import { useTranslations } from "next-intl";

export default function ProfessionalsPage() {
  const t = useTranslations("professionals");
  const sections = [
    ["whatTitle", "whatBody"],
    ["whereTitle", "whereBody"],
    ["retentionTitle", "retentionBody"],
    ["rightsTitle", "rightsBody"],
    ["contactTitle", "contactBody"],
  ] as const;
  return (
    <main className="mx-auto max-w-2xl space-y-6 p-6">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <p>{t("intro")}</p>
      {sections.map(([title, body]) => (
        <section key={title}>
          <h2 className="font-semibold">{t(title)}</h2>
          <p className="mt-1 text-sm opacity-90">{t(body)}</p>
        </section>
      ))}
    </main>
  );
}
```

(Replicar el patrón de page pública real de la landing: si `app/[locale]/page.tsx` usa `setRequestLocale`/`getTranslations` async, copiar ese andamiaje exacto.)

- [ ] **Step 2: Verify** — build verde; `curl -s http://localhost:3001/es/profesionales | grep -o "<h1[^>]*>[^<]*"` muestra el título SIN sesión iniciada (confirmar que ningún middleware lo redirige a signin).

- [ ] **Step 3: Commit** — `git commit -m "feat(web): public /profesionales page — art. 14 transparency notice"`

---

### Task 10: E2E + a11y

**Files:**
- Create: `apps/web/e2e/consulta-record.spec.ts`
- Modify: `apps/web/e2e/a11y.spec.ts` (añadir las 2 superficies nuevas), `apps/web/playwright.config.ts` (fake mic)

**Interfaces:**
- Consumes: `e2e/utils/session.ts` (siembra de cookie next-auth — patrón existente), páginas de Tasks 8-9.

- [ ] **Step 1: Fake mic en Playwright** — en `playwright.config.ts` dentro de `use`:

```typescript
    launchOptions: {
      args: [
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
      ],
    },
```

- [ ] **Step 2: Spec** — `e2e/consulta-record.spec.ts`:

```typescript
import { expect, test } from "@playwright/test";

import { seedSession } from "./utils/session"; // ajustar al export real de utils/session.ts

test.describe("consulta recorder", () => {
  test.beforeEach(async ({ page, context }) => {
    await seedSession(context);
    await page.goto("/es/dashboard/consulta/grabar");
  });

  test("gate blocks recording until informed checkbox", async ({ page }) => {
    const start = page.getByRole("button", { name: "Grabar" });
    await expect(start).toBeDisabled();
    await page.getByRole("checkbox").check();
    await expect(start).toBeEnabled();
  });

  test("kill switch discards audio and logs declined event", async ({ page }) => {
    let uploaded = false;
    let declined = false;
    await page.route("**/api/backend/documents", (route) => {
      uploaded = true;
      return route.fulfill({ status: 500 });
    });
    await page.route("**/api/backend/consent-events", (route) => {
      declined = true;
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "x", created_at: "now" }),
      });
    });
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Grabar" }).click();
    await expect(page.getByRole("status")).toContainText("Grabando");
    await page.getByRole("button", { name: "El profesional se opone" }).click();
    await expect(page.getByText("Grabación descartada", { exact: false })).toBeVisible();
    expect(declined).toBe(true);
    expect(uploaded).toBe(false);
  });

  test("record → stop uploads source=consulta with consent version", async ({ page }) => {
    let form: Record<string, string> = {};
    await page.route("**/api/backend/documents", async (route) => {
      const req = route.request();
      const body = req.postDataBuffer()?.toString("latin1") ?? "";
      for (const field of ["source", "consent_policy_version", "locale"]) {
        const m = body.match(new RegExp(`name="${field}"\\r\\n\\r\\n([^\\r]+)`));
        if (m) form[field] = m[1];
      }
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "00000000-0000-0000-0000-000000000001", status: "processing" }),
      });
    });
    await page.route("**/api/backend/documents/*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ id: "00000000-0000-0000-0000-000000000001", status: "ready" }),
      }),
    );
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Grabar" }).click();
    await page.waitForTimeout(1500); // capture some fake-device audio
    await page.getByRole("button", { name: "Terminar y guardar" }).click();
    await expect(page.getByText("Consulta guardada", { exact: false })).toBeVisible({ timeout: 15_000 });
    expect(form.source).toBe("consulta");
    expect(form.consent_policy_version).toBe("2026-08-17");
  });
});

test("professionals page is public in 3 locales", async ({ page }) => {
  for (const locale of ["es", "en", "fr"]) {
    await page.goto(`/${locale}/profesionales`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(page.url()).not.toContain("signin");
  }
});
```

- [ ] **Step 3: a11y** — añadir `/es/dashboard/consulta/grabar` y `/es/profesionales` a las superficies de `a11y.spec.ts` (patrón existente axe 0 serious/critical).

- [ ] **Step 4: Run** — stack dev arriba (docker compose dev + api + web build en :3001): `pnpm --filter @adelia/web e2e -g "consulta recorder|professionals"` → PASS.

- [ ] **Step 5: Commit** — `git commit -m "test(e2e): consulta recorder gate/kill-switch/upload + public professionals page + a11y"`

---

### Task 11: Documentación RGPD — DPIA, README, retención

**Files:**
- Create: `docs/legal/dpia-grabacion-consulta.md`
- Modify: `README.md` (sección self-host: reparto de roles responsable/encargado + nueva feature)

**Interfaces:** ninguna de código. La DPIA cita este spec y el research (`agent_marketing/08_adelia/research/2026-08-17_grabar_consulta_rgpd_research.md`).

- [ ] **Step 1: DPIA** — crear `docs/legal/dpia-grabacion-consulta.md` con estas secciones RELLENAS (contenido base del spec §2 y §7; no dejar esqueletos):
  1. **Descripción del tratamiento**: grabación de consulta pediátrica iniciada por el progenitor; audio → transcripción diarizada (Mistral Voxtral, UE) → texto en historial; audio eliminado ≤48h.
  2. **Base jurídica**: art. 9.2.a (consentimiento explícito del titular de la patria potestad, registrado en onboarding + por grabación en `consent_events`); interés legítimo documentado para los datos incidentales del profesional (test de ponderación: finalidad memoria familiar, expectativa razonable en acto profesional, grabación anunciada por diseño, minimización).
  3. **Transparencia**: gate obligatorio + script verbal + página `/profesionales` (art. 14).
  4. **Riesgos y mitigaciones** (tabla): grabación clandestina (imposible por diseño: gate + banner), difusión (prohibida en términos; sin feature de compartir audio), retención Mistral 30 días abuse-monitoring plan estándar (mitigación: minimización, DPA art. 28, ZDR al escalar a plan Scale), server sin certificación HDS para usuarios FR (gap documentado; plan: OVH/Scaleway HDS si tracción FR), acceso no autorizado (cifrado tránsito+reposo, blob privado, borrado 48h).
  5. **Derechos**: supresión en 1 clic (cascadas GDPR 0011 + tombstones), acceso/portabilidad (export FHIR existente), oposición del profesional (kill switch + contacto security@godi.ai).
  6. **Decisión**: aprobado para lanzar con las mitigaciones anteriores. Firmado: Santiago Patiño, fecha.
- [ ] **Step 2: README** — añadir a la sección self-host: "En despliegue self-host, el responsable del tratamiento es quien opera la instancia; en el SaaS adelia.godi.ai, Godi.AI. La función Grabar consulta exige mostrar el aviso a profesionales y mantener el borrado de audio activado."
- [ ] **Step 3: Commit** — `git commit -m "docs(rgpd): DPIA grabación de consulta + self-host controller roles"`

---

## Self-review (hecho al escribir el plan)

- **Spec coverage**: §4 gate/banner/kill-switch → Task 8; §4.2.4 página profesionales → Tasks 7+9; §5 Permissions-Policy/i18n → Task 7; §6.1 MIME → Task 2; §6.2 STT → Task 1; §6.3 migración+consent → Tasks 3+4+6; §6.4 borrado → Task 5; §8 testing → Tasks 1-6 (unit) + 10 (e2e/a11y); §7 legales → Task 11 (+ /profesionales). El cap de 25→50MB del cliente (spec §5) queda cubierto al no usar `upload-zone` para grabar (el recorder sube directo); subir el cap de `upload-zone` NO se toca (YAGNI: ficheros externos siguen limitados a 25MB).
- **Contrato Voxtral**: el shape `segments[].speaker` está escrito desde docs públicas, no verificado — por eso Task 1 Step 5 es un checkpoint live-gated obligatorio antes de seguir.
- **Type consistency**: `transcribe_audio(..., diarize=)` (T1) = lo que llama T4; `ConsentEvent` (T3) = lo que usan T4/T6; `process_document(..., is_consulta)` (T4) = lo que extiende T5; `CONSENT_POLICY_VERSION = "2026-08-17"` idéntico en recorder (T8) y e2e (T10).
