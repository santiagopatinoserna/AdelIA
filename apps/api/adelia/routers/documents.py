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
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status, Query
from mistralai.client.errors import MistralError
from openai import APIError as OpenAIAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.auth import get_current_user_id
from adelia.db import AsyncSessionLocal, get_db
from adelia.models import Chunk, Document, Entity
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

ALLOWED_MIME = {"application/pdf", "image/png", "image/jpeg", "audio/mpeg", "audio/wav"}
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
        except (httpx.HTTPStatusError, MistralError, ClientError, EndpointConnectionError, OpenAIAPIError) as exc:
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


async def process_document(document_id: uuid.UUID, mime_type: str) -> None:
    """BackgroundTask: download from S3, transcribe/OCR, extract entities,
    chunk + embed. Persist all stages atomically per document."""
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return
        try:
            body_stream = await storage.get_object(doc.s3_key)
            body = await asyncio.to_thread(body_stream.read)

            # Stage 1: Get raw text via transcribe (audio) or OCR (pdf/image)
            if _is_audio(mime_type):
                raw_text = await _with_retry(
                    "transcribe", lambda: transcribe_audio(body, mime_type)
                )
            elif mime_type == "application/pdf" or mime_type.startswith("image/"):
                raw_text = await _with_retry(
                    "ocr", lambda: extract_text_from_pdf(body, mime_type)
                )
            else:
                raw_text = ""

            doc.raw_text = raw_text
            await session.flush()  # ensure doc.id usable for FKs below

            # Stage 2: Entity extraction → persist entities table
            entity_records: list[Entity] = []
            entity_ranges: dict[str, tuple[int, int]] = {}
            if raw_text:
                extracted: list[ExtractedEntity] = await _with_retry(
                    "extract", lambda: extract_entities(raw_text)
                )
                for ex in extracted:
                    entity = Entity(
                        user_id=doc.user_id,
                        document_id=doc.id,
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
                    )
                    session.add(entity)
                    entity_records.append(entity)
                await session.flush()  # populate entity.id for FK use
                for ent in entity_records:
                    if ent.raw_quote and ent.raw_quote in raw_text:
                        s = raw_text.find(ent.raw_quote)
                        entity_ranges[str(ent.id)] = (s, s + len(ent.raw_quote))

            # Stage 3: Hierarchical chunking
            chunk_records: list[Chunk] = []
            chunk_texts: list[str] = []
            if raw_text:
                chunk_output = chunk_hierarchical(
                    raw_text,
                    ChunkConfig(small_size=350, parent_size=1500, overlap=50),
                    entity_ranges=entity_ranges,
                )
                for sc in chunk_output.small_chunks:
                    chunk_record = Chunk(
                        document_id=doc.id,
                        user_id=doc.user_id,
                        content=sc.content,
                        chunk_index=sc.chunk_index,
                        chunk_metadata={
                            "parent_index": sc.parent_index,
                            "token_count": sc.token_count,
                            "start_char": sc.start_char,
                            "end_char": sc.end_char,
                            "entity_ids": sc.entity_ids,
                        },
                    )
                    chunk_records.append(chunk_record)
                    chunk_texts.append(sc.content)

            # Stage 4: Embed chunks → set Chunk.embedding
            if chunk_texts:
                vectors = await _with_retry("embed", lambda: embed_texts(chunk_texts))
                for chunk_record, vec in zip(chunk_records, vectors, strict=True):
                    chunk_record.embedding = vec
                    session.add(chunk_record)

            # Stage 5 (M5 T9): Mark any prior briefings of this user as stale.
            # User uploaded new data → previously generated briefings no longer reflect it.
            await briefing_repo.mark_stale_for_user(
                session,
                user_id=doc.user_id,
                since=datetime.now(timezone.utc),
            )
        except (RuntimeError, httpx.HTTPStatusError, MistralError, ClientError, EndpointConnectionError, OpenAIAPIError) as exc:
            logger.exception(
                "process_document failed for document_id=%s: %s",
                document_id,
                exc,
            )
            doc.raw_text = doc.raw_text or None
        except Exception as exc:  # noqa: BLE001 — final fallback to set processed_at
            logger.exception(
                "process_document unexpected failure for document_id=%s: %s",
                document_id,
                exc,
            )
            doc.raw_text = doc.raw_text or None
        finally:
            doc.processed_at = datetime.now(timezone.utc)
            await session.commit()


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background: BackgroundTasks,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail=f"Unsupported mime: {file.content_type}")

    body = await file.read()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")
    safe_name = re.sub(r"[^\w.\-]", "_", pathlib.Path(file.filename or "upload").name)
    s3_key = f"users/{user_id}/{uuid.uuid4()}-{safe_name}"
    await storage.put_object(s3_key, io.BytesIO(body), content_type=file.content_type)

    doc = Document(
        user_id=user_id,
        source="web",
        mime_type=file.content_type,
        s3_key=s3_key,
    )
    db.add(doc)
    try:
        await db.commit()
    except Exception:
        # Compensate: a failed commit after the S3 put would leave an orphan
        # blob nobody references (v0.1.1 transactional-outbox carry-over).
        try:
            await storage.delete_object(s3_key)
        except Exception:  # noqa: BLE001 — best effort, original error matters more
            logger.exception("orphan blob cleanup failed for %s", s3_key)
        raise
    await db.refresh(doc)

    background.add_task(process_document, doc.id, file.content_type)

    return _doc_to_out(doc)


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    # Aggregate counts in one query (no per-row roundtrips) so the list
    # view shows real entity/chunk numbers instead of 0.
    entity_counts = (
        sa.select(Entity.document_id, sa.func.count().label("n"))
        .where(Entity.deleted_at.is_(None))
        .group_by(Entity.document_id)
        .subquery()
    )
    chunk_counts = (
        sa.select(Chunk.document_id, sa.func.count().label("n"))
        .group_by(Chunk.document_id)
        .subquery()
    )
    result = await db.execute(
        select(
            Document,
            sa.func.coalesce(entity_counts.c.n, 0),
            sa.func.coalesce(chunk_counts.c.n, 0),
        )
        .outerjoin(entity_counts, entity_counts.c.document_id == Document.id)
        .outerjoin(chunk_counts, chunk_counts.c.document_id == Document.id)
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
