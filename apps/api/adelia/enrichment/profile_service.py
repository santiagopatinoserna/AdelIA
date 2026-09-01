"""Multi-profile service — user owns N profiles (self, child, parent, etc.).

Each profile is an isolated medical vault: documents + entities + chunks +
briefings all scope by profile_id. The user has exactly one `is_default`
profile at a time (DB-enforced via unique partial index).

Legacy data (v0.1) has profile_id=NULL; the auto_resolve_profile helper maps
NULL → user's default profile transparently.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.models import Profile


logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Who the answer is about (audit 3.3, 3.5, 3.9 and 3.10)
#
# Four separate defects in the audit came from the same hole: nothing read
# the baby's age. The red-flag detector could not apply the "<3 months"
# rule, `evaluar_labs` compared an infant against adult ranges,
# `proximas_vacunas` took the age from whatever the model typed, and every
# briefing header said "0 años". Profile has held `date_of_birth` and `sex`
# all along.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProfileFacts:
    """The three facts every clinical surface needs about the patient."""

    profile_id: UUID | None
    display_name: str | None
    date_of_birth: date | None
    sex: str | None
    age_months: int | None

    @property
    def has_age(self) -> bool:
        return self.age_months is not None


#: What a surface gets when there is no profile at all (a v0.1 legacy user, a
#: test, a Telegram message before onboarding). Every field is None on
#: purpose: "unknown" must never be renderable as 0.
UNKNOWN_PROFILE = ProfileFacts(None, None, None, None, None)


def age_in_months(date_of_birth: date | None, *, today: date | None = None) -> int | None:
    """Whole months lived, or None when the date of birth is unknown.

    None is the point: `briefing_orchestrator` printed `age=0` for every
    patient because 0 was easier to type than a missing value, and a
    pediatrician reading "0 años" on an 18-month-old stops reading. A future
    date of birth (a typo, or a pregnancy) also returns None rather than a
    negative age.
    """
    if date_of_birth is None:
        return None
    today = today or date.today()
    if date_of_birth > today:
        return None
    months = (today.year - date_of_birth.year) * 12 + (today.month - date_of_birth.month)
    if today.day < date_of_birth.day:
        months -= 1
    return max(months, 0)


async def get_profile_facts(
    session: AsyncSession,
    *,
    user_id: UUID,
    profile_id: UUID | None = None,
) -> ProfileFacts:
    """Resolve the active profile and read the facts off it.

    Never raises for a missing profile: returns UNKNOWN_PROFILE, so a caller
    can always render something honest.
    """
    resolved = await resolve_profile_id(session, user_id=user_id, profile_id=profile_id)
    if resolved is None:
        return UNKNOWN_PROFILE
    profile = await get_profile(session, profile_id=resolved, user_id=user_id)
    if profile is None:
        return UNKNOWN_PROFILE
    return ProfileFacts(
        profile_id=profile.id,
        display_name=profile.display_name,
        date_of_birth=profile.date_of_birth,
        sex=profile.sex,
        age_months=age_in_months(profile.date_of_birth),
    )


async def load_profile_facts(
    *, user_id: UUID, profile_id: UUID | None = None
) -> ProfileFacts:
    """`get_profile_facts` with its own session, best effort.

    Used by the answering surfaces, which run outside a request session and
    must not fail an answer because a profile lookup failed. A DB error here
    degrades the answer (no age-gated rules) and is logged; it never turns
    into a 500 in the middle of a stream.
    """
    from adelia.db import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            return await get_profile_facts(
                session, user_id=user_id, profile_id=profile_id
            )
    except Exception as exc:  # noqa: BLE001 - degrade, never break the stream
        logger.warning("profile facts unavailable (continuing without age): %s", exc)
        return UNKNOWN_PROFILE
