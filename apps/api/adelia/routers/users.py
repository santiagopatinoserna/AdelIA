"""Account endpoints — GDPR right-to-erasure (Article 17)."""

import logging
import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.auth import get_current_user_id
from adelia.db import get_db
from adelia.models import Document, User
from adelia.storage import S3Storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])
storage = S3Storage()


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Erase the account and every derived record + blob.

    DB graph goes via ON DELETE CASCADE (0011): documents → entities/chunks,
    briefings → citations/share_links, chat sessions → messages, profiles,
    ingestion links. S3 blobs are deleted best-effort AFTER the commit —
    a failed blob delete must not resurrect the account (logged for ops).
    """
    result = await db.execute(
        sa.select(Document.s3_key).where(Document.user_id == user_id)
    )
    s3_keys = [row[0] for row in result.all()]

    await db.execute(sa.delete(User).where(User.id == user_id))
    await db.commit()

    for key in s3_keys:
        try:
            await storage.delete_object(key)
        except Exception:  # noqa: BLE001 — best effort, account is already gone
            logger.exception("gdpr blob cleanup failed for %s", key)

    logger.info("account erased user_id=%s blobs=%d", user_id, len(s3_keys))
    return None
