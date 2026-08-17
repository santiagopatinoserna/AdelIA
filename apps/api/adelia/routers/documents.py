import asyncio
import io
import logging
import pathlib
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated

import sqlalchemy as sa
import httpx
from botocore.exceptions import ClientError, EndpointConnectionError
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status, Query
from mistralai.client.errors import MistralError
from openai import APIError as OpenAIAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.auth import get_current_user_id
from adelia.config import settings
from adelia.db import AsyncSessionLocal, get_db
from adelia.models import Chunk, ConsentEvent, Document, Entity
from adelia.schemas import DocumentOut, ExtractedEntity, derive_status
from adelia.services import briefing_repo
from adelia.storage import S3Storage
from adelia.workers.chunker import ChunkConfig, chunk_hierarchical
from adelia.workers.embed import embed_texts
from adelia.workers.extract import extract_entities
from adelia.workers.ocr import extract_text_from_pdf
from adelia.workers.transcribe import transcribe_audio

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])
storage = S3Storage()

ALLOWED_MIME = {
    "application/pdf", "image/png", "image/jpeg",
    "audio/mpeg", "audio/wav", "audio/webm", "audio/mp4",
    "audio/ogg", "audio/x-m4a", "audio/flac",
}

VALID_SOURCES = {"web", "manual", "consulta"}


def normalize_mime(content_type: str | None) -> str:
    """MediaRecorder emits 'audio/webm;codecs=opus' — compare/store bare type."""
    return (content_type or "").split(";")[0].strip()


MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB — Mistral OCR limit

# Confidence threshold below which an extracted entity is flagged for human review.
# Per spec section 6.1: low-confidence entities should not auto-populate briefings
# without verification.
NEEDS_REVIEW_CONFIDENCE_THRESHOLD = 0.7

AUDIO_MIME_PREFIXES = ("audio/",)


def _is_audio(mime_type: str) -> bool:
    return any(mime_type.startswith(prefix) for prefix in AUDIO_MIME_PREFIXES)


# Transient-failure retry for external API stages (Mistral OCR/extract/embed,
# Whisper). Bounded in-process backoff — the v0.1.1 alternative to a Celery
# queue. Tests can shrink RETRY_DELAYS to keep runs fast.
RETRY_DELAYS: tuple[float, ...] = (1.0, 4.0)


async def _with_retry(stage: str, make_call):
    """Run make_call() retrying RETRY_DELAYS times on transient errors.

    Non-transient errors (RuntimeError = misconfiguration) propagate at once.
    """
    last_exc: Exception | None = None
    for attempt, delay in enumerate((*RETRY_DELAYS, None)):
        try:
            return await make_call()
        except (httpx.HTTPError, MistralError, ClientError, EndpointConnectionError, OpenAIAPIError) as exc:
            last_exc = exc
            if delay is None:
                break
            logger.warning(
                "%s failed (attempt %d, retrying in %.0fs): %s",
                stage, attempt + 1, delay, exc,
            )
            await asyncio.sleep(delay)
    raise last_exc


def _file_name_from_key(s3_key: str) -> str:
    """users/{uid}/{uuid4}-{safe_name} → safe_name (the user-facing name)."""
    leaf = s3_key.rsplit("/", 1)[-1]
    # uuid4 canonical form is 36 chars followed by the '-' separator we add
    return leaf[37:] if len(leaf) > 37 and leaf[36] == "-" else leaf


def _doc_to_out(doc: Document, *, entity_count: int = 0, chunk_count: int = 0) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        source=doc.source,
        mime_type=doc.mime_type,
        file_name=_file_name_from_key(doc.s3_key),
        raw_text=doc.raw_text,
        created_at=doc.created_at,
        processed_at=doc.processed_at,
        status=derive_status(doc.raw_text, doc.processed_at),
        entity_count=entity_count,
        chunk_count=chunk_count,
    )


_processing_semaphore: asyncio.Semaphore | None = None


def _get_processing_semaphore() -> asyncio.Semaphore:
    global _processing_semaphore
    if _processing_semaphore is None:
        _processing_semaphore = asyncio.Semaphore(settings.doc_processing_concurrency)
    return _processing_semaphore


async def process_document(document_id: uuid.UUID, mime_type: str, is_consulta: bool = False) -> None:
    # Cap concurrent pipelines: a burst of uploads queues here instead of
    # each grabbing a DB connection + Mistral call at once (pool/API
    # exhaustion → 500). Waiting tasks hold no connection.
    async with _get_processing_semaphore():
        await _process_document_inner(document_id, mime_type, is_consulta)


async def _process_document_inner(document_id: uuid.UUID, mime_type: str, is_consulta: bool = False) -> None:
    """BackgroundTask: download from S3, transcribe/OCR, extract entities,
    chunk + embed.

    DB connections are held only for two short reads/writes — never across
    the slow OCR/extract/embed network I/O. Holding a pooled connection for
    the whole ~6s pipeline exhausted the pool under concurrent uploads
    (QueuePool timeout → 500). Entity/Chunk ids are generated client-side so
    the in-memory records can be built before any second connection.
    """
    # Short read: just the fields the pipeline needs, then release the conn.
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return
        s3_key = doc.s3_key
        user_id = doc.user_id
        profile_id = doc.profile_id

    raw_text = ""
    entities: list[Entity] = []
    chunks: list[Chunk] = []

    try:
        body_stream = await storage.get_object(s3_key)
        body = await asyncio.to_thread(body_stream.read)

        # Stage 1: raw text via transcribe (audio) or OCR (pdf/image)
        if _is_audio(mime_type):
            raw_text = await _with_retry(
                "transcribe", lambda: transcribe_audio(body, mime_type, diarize=is_consulta)
            )
        elif mime_type == "application/pdf" or mime_type.startswith("image/"):
            raw_text = await _with_retry("ocr", lambda: extract_text_from_pdf(body, mime_type))

        if raw_text:
            # Stage 2: entity extraction (ids assigned now for entity_ranges)
            extracted: list[ExtractedEntity] = await _with_retry(
                "extract", lambda: extract_entities(raw_text)
            )
            entity_ranges: dict[str, tuple[int, int]] = {}
            for ex in extracted:
                eid = uuid.uuid4()
                entities.append(Entity(
                    id=eid,
                    user_id=user_id,
                    profile_id=profile_id,
                    document_id=document_id,
                    entity_type=ex.entity_type,
                    coding_system=ex.coding_system,
                    code=ex.code,
                    name=ex.name,
                    value=ex.value,
                    event_date=ex.event_date,
                    status=ex.status,
                    provenance=ex.provenance,
                    confidence=ex.confidence,
                    raw_quote=ex.raw_quote,
                    page=ex.page,
                    needs_review=ex.confidence < NEEDS_REVIEW_CONFIDENCE_THRESHOLD,
                ))
                if ex.raw_quote and ex.raw_quote in raw_text:
                    s = raw_text.find(ex.raw_quote)
                    entity_ranges[str(eid)] = (s, s + len(ex.raw_quote))

            # Stage 3: hierarchical chunking
            chunk_output = chunk_hierarchical(
                raw_text,
                ChunkConfig(small_size=350, parent_size=1500, overlap=50),
                entity_ranges=entity_ranges,
            )
            small = chunk_output.small_chunks
            chunk_texts = [sc.content for sc in small]

            # Stage 4: embed (slow network I/O — no DB connection held)
            vectors = await _with_retry("embed", lambda: embed_texts(chunk_texts)) if chunk_texts else []
            for sc, vec in zip(small, vectors, strict=True):
                chunks.append(Chunk(
                    document_id=document_id,
                    user_id=user_id,
                    profile_id=profile_id,
                    content=sc.content,
                    chunk_index=sc.chunk_index,
                    embedding=vec,
                    chunk_metadata={
                        "parent_index": sc.parent_index,
                        "token_count": sc.token_count,
                        "start_char": sc.start_char,
                        "end_char": sc.end_char,
                        "entity_ids": sc.entity_ids,
                    },
                ))
    except (RuntimeError, httpx.HTTPError, MistralError, ClientError, EndpointConnectionError, OpenAIAPIError) as exc:
        logger.exception("process_document failed for document_id=%s: %s", document_id, exc)
        raw_text, entities, chunks = "", [], []
    except Exception as exc:  # noqa: BLE001 — final fallback to set processed_at
        logger.exception("process_document unexpected failure for document_id=%s: %s", document_id, exc)
        raw_text, entities, chunks = "", [], []

    # Short write: persist everything in one quick transaction.
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return
        doc.raw_text = raw_text or None
        if entities:
            session.add_all(entities)
        if chunks:
            session.add_all(chunks)
        await briefing_repo.mark_stale_for_user(
            session, user_id=user_id, since=datetime.now(timezone.utc)
        )
        doc.processed_at = datetime.now(timezone.utc)
        await session.commit()


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

    body = await file.read()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")
    safe_name = re.sub(r"[^\w.\-]", "_", pathlib.Path(file.filename or "upload").name)
    s3_key = f"users/{user_id}/{uuid.uuid4()}-{safe_name}"
    # Upload to S3 BEFORE acquiring a DB connection — a pooled connection held
    # across the blob upload exhausted the pool under concurrent uploads.
    await storage.put_object(s3_key, io.BytesIO(body), content_type=content_type)

    # id generated client-side (not left to the Column default) — the
    # ConsentEvent below needs doc.id before the INSERT flush would assign
    # one; see the _process_document_inner docstring for the same pattern.
    doc = Document(
        id=uuid.uuid4(),
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
        try:
            await db.commit()
        except Exception:
            # Compensate: a failed commit after the S3 put would leave an
            # orphan blob nobody references (transactional-outbox carry-over).
            try:
                await storage.delete_object(s3_key)
            except Exception:  # noqa: BLE001 — best effort, original error matters
                logger.exception("orphan blob cleanup failed for %s", s3_key)
            raise
        await db.refresh(doc)

    background.add_task(process_document, doc.id, content_type, is_consulta)

    return _doc_to_out(doc)


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    # Correlated scalar counts: 2 index lookups per returned row (≤limit),
    # O(page) instead of O(total table) — the previous GROUP BY subqueries
    # seq-scanned entities+chunks across ALL users on every dashboard load.
    entity_count = (
        sa.select(sa.func.count())
        .where(Entity.document_id == Document.id, Entity.deleted_at.is_(None))
        .correlate(Document)
        .scalar_subquery()
    )
    chunk_count = (
        sa.select(sa.func.count())
        .where(Chunk.document_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
    )
    result = await db.execute(
        select(Document, entity_count, chunk_count)
        .where(Document.user_id == user_id, Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        _doc_to_out(doc, entity_count=ec, chunk_count=cc)
        for doc, ec, cc in result.all()
    ]


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    doc = await db.get(Document, doc_id)
    if doc is None or doc.user_id != user_id or doc.deleted_at is not None:
        raise HTTPException(status_code=404)

    entity_count = await db.scalar(
        sa.select(sa.func.count()).select_from(Entity).where(
            Entity.document_id == doc.id, Entity.deleted_at.is_(None)
        )
    )
    chunk_count = await db.scalar(
        sa.select(sa.func.count()).select_from(Chunk).where(Chunk.document_id == doc.id)
    )

    return _doc_to_out(doc, entity_count=entity_count or 0, chunk_count=chunk_count or 0)
