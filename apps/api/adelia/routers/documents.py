import io
import uuid
from datetime import datetime, timezone
from typing import Annotated

import httpx
from botocore.exceptions import ClientError
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.auth import get_current_user_id
from adelia.db import AsyncSessionLocal, get_db
from adelia.models import Document
from adelia.schemas import DocumentOut, derive_status
from adelia.storage import S3Storage
from adelia.workers.ocr import extract_text_from_pdf


router = APIRouter(prefix="/documents", tags=["documents"])
storage = S3Storage()

ALLOWED_MIME = {"application/pdf", "image/png", "image/jpeg", "audio/mpeg", "audio/wav"}


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
    """BackgroundTask: download from S3, OCR, persist raw_text, mark processed_at.

    Catches expected error contracts from ocr.extract_text_from_pdf:
    - RuntimeError: MISTRAL_API_KEY not set (config error — leave raw_text None, mark processed)
    - httpx.HTTPStatusError: API failure (transient — same handling for v0.1; future: retry)

    Always sets processed_at to ensure document doesn't stay in 'processing' forever.
    """
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return
        try:
            body_stream = await storage.get_object(doc.s3_key)
            body = body_stream.read()
            if mime_type == "application/pdf" or mime_type.startswith("image/"):
                text = await extract_text_from_pdf(body, mime_type)
            else:
                text = ""  # audio handled in M2 (Whisper)
            doc.raw_text = text
        except (RuntimeError, httpx.HTTPStatusError, ClientError):
            doc.raw_text = None
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
    s3_key = f"users/{user_id}/{uuid.uuid4()}-{file.filename}"
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
