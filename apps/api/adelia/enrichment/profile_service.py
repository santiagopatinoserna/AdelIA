"""Multi-profile service — user owns N profiles (self, child, parent, etc.).

Each profile is an isolated medical vault: documents + entities + chunks +
briefings all scope by profile_id. The user has exactly one `is_default`
profile at a time (DB-enforced via unique partial index).

Legacy data (v0.1) has profile_id=NULL; the auto_resolve_profile helper maps
NULL → user's default profile transparently.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.models import Profile


Relationship = Literal["self", "child", "parent", "spouse", "sibling", "other"]


@dataclass(frozen=True)
class ProfileCreate:
    display_name: str
    relationship: Relationship
    date_of_birth: date | None = None
    sex: str | None = None
    is_default: bool = False


async def create_profile(
    session: AsyncSession,
    *,
    user_id: UUID,
    data: ProfileCreate,
) -> Profile:
    """Create a new profile for a user.

    If is_default=True, demote the current default first to maintain
    the one-default-per-user invariant.
    """
    if data.is_default:
        await _clear_default(session, user_id=user_id)

    p = Profile(
        user_id=user_id,
        display_name=data.display_name,
        relationship=data.relationship,
        date_of_birth=data.date_of_birth,
        sex=data.sex,
        is_default=data.is_default,
    )
    session.add(p)
    await session.flush()
    return p


async def update_profile(
    session: AsyncSession,
    *,
    profile_id: UUID,
    user_id: UUID,
    display_name: str | None = None,
    date_of_birth: date | None = None,
    sex: str | None = None,
) -> Profile | None:
    """Update select fields on a profile, scoped to user_id (cross-user isolation).

    Only the provided (non-None) fields are updated. Returns the updated
    profile, or None if not found / not owned by user_id.
    """
    target = await get_profile(session, profile_id=profile_id, user_id=user_id)
    if target is None:
        return None

    values: dict = {}
    if display_name is not None:
        values["display_name"] = display_name
    if date_of_birth is not None:
        values["date_of_birth"] = date_of_birth
    if sex is not None:
        values["sex"] = sex

    if values:
        stmt = (
            update(Profile)
            .where(Profile.id == profile_id)
            .where(Profile.user_id == user_id)
            .values(**values)
        )
        await session.execute(stmt)
        await session.flush()
        target = await get_profile(session, profile_id=profile_id, user_id=user_id)

    return target


async def ensure_default_profile(
    session: AsyncSession,
    *,
    user_id: UUID,
    display_name: str = "Mi perfil",
) -> Profile:
    """Idempotent — returns existing default profile or creates one.

    Called on user first-login to ensure backward compatibility for v0.1 data.
    """
    stmt = (
        select(Profile)
        .where(Profile.user_id == user_id)
        .where(Profile.is_default.is_(True))
        .where(Profile.deleted_at.is_(None))
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    return await create_profile(
        session,
        user_id=user_id,
        data=ProfileCreate(
            display_name=display_name,
            relationship="self",
            is_default=True,
        ),
    )


async def list_profiles(session: AsyncSession, *, user_id: UUID) -> list[Profile]:
    stmt = (
        select(Profile)
        .where(Profile.user_id == user_id)
        .where(Profile.deleted_at.is_(None))
        .order_by(Profile.is_default.desc(), Profile.created_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_profile(
    session: AsyncSession, *, profile_id: UUID, user_id: UUID
) -> Profile | None:
    """Cross-user isolation — only returns the profile if owned by user_id."""
    stmt = (
        select(Profile)
        .where(Profile.id == profile_id)
        .where(Profile.user_id == user_id)
        .where(Profile.deleted_at.is_(None))
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def set_default_profile(
    session: AsyncSession, *, profile_id: UUID, user_id: UUID
) -> Profile | None:
    """Mark a profile as default + demote the previous default."""
    target = await get_profile(session, profile_id=profile_id, user_id=user_id)
    if target is None:
        return None

    await _clear_default(session, user_id=user_id)

    stmt = (
        update(Profile)
        .where(Profile.id == profile_id)
        .values(is_default=True)
    )
    await session.execute(stmt)
    target = await get_profile(session, profile_id=profile_id, user_id=user_id)
    return target


async def soft_delete_profile(
    session: AsyncSession, *, profile_id: UUID, user_id: UUID
) -> bool:
    """Soft-delete. Cannot delete the only profile a user has.

    Returns False if profile not found OR is the only profile.
    """
    profiles = await list_profiles(session, user_id=user_id)
    if len(profiles) <= 1:
        return False
    target = next((p for p in profiles if p.id == profile_id), None)
    if target is None:
        return False

    from datetime import datetime, UTC

    stmt = (
        update(Profile)
        .where(Profile.id == profile_id)
        .where(Profile.user_id == user_id)
        .values(deleted_at=datetime.now(UTC))
    )
    await session.execute(stmt)

    # If deleted was default, promote the next non-deleted profile to default
    if target.is_default:
        next_default = next((p for p in profiles if p.id != profile_id), None)
        if next_default is not None:
            await session.execute(
                update(Profile)
                .where(Profile.id == next_default.id)
                .values(is_default=True)
            )
    return True


async def _clear_default(session: AsyncSession, *, user_id: UUID) -> None:
    stmt = (
        update(Profile)
        .where(Profile.user_id == user_id)
        .where(Profile.is_default.is_(True))
        .values(is_default=False)
    )
    await session.execute(stmt)


async def resolve_profile_id(
    session: AsyncSession,
    *,
    user_id: UUID,
    profile_id: UUID | None,
) -> UUID | None:
    """Resolve a requested profile_id to a real one (with isolation check).

    If profile_id is None, returns the user's default profile id (or None if
    no default exists yet — v0.1 legacy users may have none).
    """
    if profile_id is not None:
        p = await get_profile(session, profile_id=profile_id, user_id=user_id)
        return p.id if p else None

    stmt = (
        select(Profile.id)
        .where(Profile.user_id == user_id)
        .where(Profile.is_default.is_(True))
        .where(Profile.deleted_at.is_(None))
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    return row
