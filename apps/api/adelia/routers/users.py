"""Account endpoints — GDPR right-to-erasure (Article 17)."""

import logging
import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.auth import get_current_user_id
from adelia.db import get_db
from adelia.models import BlobTombstone, Document, User
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

    # Tombstones ride the SAME transaction as the erase: if blob deletion
    # fails afterwards, the keys survive for the startup sweep to retry —
    # no orphaned medical files with zero record of them.
    for key in s3_keys:
        await db.merge(BlobTombstone(s3_key=key))
    await db.execute(sa.delete(User).where(User.id == user_id))
    await db.commit()

    await sweep_blob_tombstones()

    logger.info("account erased user_id=%s blobs=%d", user_id, len(s3_keys))
    return None


async def sweep_blob_tombstones() -> None:
    """Delete every tombstoned blob; drop the tombstone only on success.
    Called post-erasure and at startup (retries previous failures)."""
    from adelia.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await session.execute(sa.select(BlobTombstone.s3_key))
        keys = [row[0] for row in result.all()]
        for key in keys:
            try:
                await storage.delete_object(key)
            except Exception:  # noqa: BLE001 — keep tombstone, retry next sweep
                logger.exception("blob tombstone delete failed for %s (kept)", key)
                continue
            await session.execute(
                sa.delete(BlobTombstone).where(BlobTombstone.s3_key == key)
            )
        await session.commit()
