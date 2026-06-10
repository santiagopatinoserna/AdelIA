"""briefing_repo — CRUD over Briefing + BriefingCitation tables.

Cross-user isolation enforced at every read: WHERE user_id = :uid AND deleted_at IS NULL.
"""
from __future__ import annotations

from datetime import datetime, UTC
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.models import Briefing
from adelia.schemas import BriefingPayload, Specialty


async def create_briefing(
    session: AsyncSession,
    *,
    user_id: UUID,
    target_specialty: Specialty,
) -> Briefing:
    """Insert a new briefing row with status='processing'."""
    b = Briefing(
        user_id=user_id,
        target_specialty=target_specialty.value,
        status="processing",
        is_stale=False,
    )
    session.add(b)
    await session.flush()
    return b


async def get_by_id(
    session: AsyncSession,
    *,
    briefing_id: UUID,
    user_id: UUID,
) -> Briefing | None:
    """Return briefing if owned by user_id and not soft-deleted, else None (opaque 404)."""
    stmt = (
        select(Briefing)
        .where(Briefing.id == briefing_id)
        .where(Briefing.user_id == user_id)
        .where(Briefing.deleted_at.is_(None))
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_for_user(
    session: AsyncSession,
    *,
    user_id: UUID,
    limit: int = 50,
) -> list[Briefing]:
    """Return non-deleted briefings for user, newest first."""
    stmt = (
        select(Briefing)
        .where(Briefing.user_id == user_id)
        .where(Briefing.deleted_at.is_(None))
        .order_by(Briefing.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_payload_html_status(
    session: AsyncSession,
    *,
    briefing_id: UUID,
    payload: BriefingPayload | None,
    html_render: str | None,
    status: str,
    error_message: str | None,
) -> None:
    """Update payload + html + status + completed_at + error_message."""
    stmt = (
        update(Briefing)
        .where(Briefing.id == briefing_id)
        .values(
            payload=payload.model_dump(mode="json") if payload else None,
            html_render=html_render,
            status=status,
            error_message=error_message,
            completed_at=datetime.now(UTC),
        )
    )
    await session.execute(stmt)


async def mark_stale_for_user(
    session: AsyncSession,
    *,
    user_id: UUID,
    since: datetime,
) -> int:
    """Mark all non-deleted briefings of user_id created before `since` as stale.

    Returns: count of rows updated. Idempotent (already-stale rows stay stale).
    """
    stmt = (
        update(Briefing)
        .where(Briefing.user_id == user_id)
        .where(Briefing.deleted_at.is_(None))
        .where(Briefing.created_at < since)
        .values(is_stale=True)
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def soft_delete(
    session: AsyncSession,
    *,
    briefing_id: UUID,
    user_id: UUID,
) -> bool:
    """Soft-delete a briefing. Returns True if a row was updated."""
    stmt = (
        update(Briefing)
        .where(Briefing.id == briefing_id)
        .where(Briefing.user_id == user_id)
        .where(Briefing.deleted_at.is_(None))
        .values(deleted_at=datetime.now(UTC))
    )
    result = await session.execute(stmt)
    return (result.rowcount or 0) > 0
