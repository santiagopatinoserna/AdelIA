"""Erasing an account, one path for every door (GDPR art. 17).

DELETE /users/me (routers/users.py) is the mother's door. scripts/erase_user.py
is the operator's, added on 2026-11-08 for the test guests that smoke runs and
other agents leave behind with no session left to call the endpoint with. Both
call `erase_account` so the two can never drift: what one erases, the other
erases, and a fix to one is a fix to both. Removing the blobs afterwards
(routers/users.sweep_blob_tombstones) is the caller's: the endpoint does it
after its 204, the script before it exits.
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.models import BlobTombstone, Document, User


async def erase_account(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """Delete the account and everything that hangs off it; return its blob keys.

    The DB graph goes via ON DELETE CASCADE (0011): documents → entities/chunks,
    briefings → citations/share_links, chat sessions → messages, profiles,
    ingestion links. Commits.
    """
    result = await db.execute(sa.select(Document.s3_key).where(Document.user_id == user_id))
    s3_keys = [row[0] for row in result.all()]

    # Tombstones ride the SAME transaction as the erase: if blob deletion
    # fails afterwards, the keys survive for the startup sweep to retry:
    # no orphaned medical files with zero record of them.
    #
    # not_before=None EXPLICITLY, never omitted: merge() only copies the
    # attributes that were set on the given instance, so a bare
    # BlobTombstone(s3_key=key) leaves a future date in place. Audio blobs now
    # carry one from the moment they are uploaded (documents.upload_document),
    # so omitting it would keep a recording alive for up to 7 days AFTER the
    # account was erased. Erasure means now.
    for key in s3_keys:
        await db.merge(BlobTombstone(s3_key=key, not_before=None))
    await db.execute(sa.delete(User).where(User.id == user_id))
    await db.commit()
    return s3_keys
