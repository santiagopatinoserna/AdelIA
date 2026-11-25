"""Observations: write one, find the reading to compare it with, read them back.

The record node (agent/record.py) is the only writer, and only after the
parent confirmed the card (principle 3). Reads go through `Scope`, so a
mother of two never sees one child's temperature compared with the other's.
`notes_since` feeds the answers about what she noted (agent/diary.py).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.models import OBSERVATION_KINDS, OBSERVATION_SOURCES, Observation
from adelia.services.scope import Scope

__all__ = [
    "OBSERVATION_KINDS",
    "OBSERVATION_SOURCES",
    "add_observation",
    "notes_since",
    "previous_comparable",
]


async def add_observation(
    session: AsyncSession,
    *,
    user_id: UUID,
    profile_id: UUID | None,
    kind: str,
    value: float | None,
    unit: str | None,
    text: str,
    observed_at: datetime,
    source: str,
    timed: bool = True,
) -> Observation:
    """Insert one row and flush it. The caller commits."""
    row = Observation(
        user_id=user_id, profile_id=profile_id, kind=kind, value=value, unit=unit,
        text=text, observed_at=observed_at, source=source, timed=timed,
    )
    session.add(row)
    await session.flush()
    return row


async def previous_comparable(
    session: AsyncSession, *, scope: Scope, kind: str, before: datetime
) -> Observation | None:
    """The most recent observation of the same kind for the same child, before `before`.

    Scoped like every other read (services/scope): this profile or rows not
    assigned to any, never a sibling's.
    """
    return await session.scalar(
        sa.select(Observation)
        .where(*scope.where(Observation), Observation.kind == kind,
               Observation.observed_at < before)
        .order_by(Observation.observed_at.desc())
        .limit(1)
    )


async def notes_since(
    session: AsyncSession,
    *,
    scope: Scope,
    kinds: tuple[str, ...] | None,
    since: datetime | None,
    limit: int,
) -> list[Observation]:
    """Her notes of these kinds (all kinds when None) from `since` on, oldest first.

    The newest `limit` rows when there are more: a question about a year of
    feeds reads the recent ones, never an unbounded scan.
    """
    stmt = sa.select(Observation).where(*scope.where(Observation))
    if kinds:
        stmt = stmt.where(Observation.kind.in_(kinds))
    if since is not None:
        stmt = stmt.where(Observation.observed_at >= since)
    rows = (await session.scalars(
        stmt.order_by(Observation.observed_at.desc(), Observation.created_at.desc()).limit(limit)
    )).all()
    return list(reversed(rows))
