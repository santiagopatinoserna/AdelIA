import asyncio
import io
import logging
import pathlib
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated

import httpx
from botocore.exceptions import ClientError, EndpointConnectionError
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from openai import APIError as OpenAIAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.auth import get_current_user_id
from adelia.db import AsyncSessionLocal, get_db
from adelia.models import Chunk, Document, Entity
from adelia.schemas import DocumentOut, ExtractedEntity, derive_status
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

AUDIO_MIME_PREFIXES = ("audio/",)


def _is_audio(mime_type: str) -> bool:
    return any(mime_type.startswith(prefix) for prefix in AUDIO_MIME_PREFIXES)


def _doc_to_out(doc: Document) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        source=doc.source,
        mime_type=doc.mime_type,
        s3_key=doc.s3_key,
        raw_text=doc.raw_text,
        created_at=doc.created_at,
        processed_at=doc.processed_at,
        status=derive_status(doc.raw_text, doc.processed_at),
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
                raw_text = await transcribe_audio(body, mime_type)
            elif mime_type == "application/pdf" or mime_type.startswith("image/"):
                raw_text = await extract_text_from_pdf(body, mime_type)
            else:
                raw_text = ""

            doc.raw_text = raw_text
            await session.flush()  # ensure doc.id usable for FKs below

            # Stage 2: Entity extraction → persist entities table
            entity_records: list[Entity] = []
            entity_ranges: dict[str, tuple[int, int]] = {}
            if raw_text:
                extracted: list[ExtractedEntity] = await extract_entities(raw_text)
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
                        needs_review=ex.confidence < 0.7,
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
                vectors = await embed_texts(chunk_texts)
                for chunk_record, vec in zip(chunk_records, vectors, strict=True):
                    chunk_record.embedding = vec
                    session.add(chunk_record)
        except (RuntimeError, httpx.HTTPStatusError, ClientError, EndpointConnectionError, OpenAIAPIError) as exc:
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
    await db.commit()
    await db.refresh(doc)

    background.add_task(process_document, doc.id, file.content_type)

    return _doc_to_out(doc)


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Document)
        .where(Document.user_id == user_id, Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    return [_doc_to_out(d) for d in docs]


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    doc = await db.get(Document, doc_id)
    if doc is None or doc.user_id != user_id or doc.deleted_at is not None:
        raise HTTPException(status_code=404)
    return _doc_to_out(doc)
