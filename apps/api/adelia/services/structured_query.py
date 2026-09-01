from datetime import date
from typing import TypedDict
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import or_

from adelia.db import AsyncSessionLocal
from adelia.models import Entity
from adelia.services.scope import Scope


class ObservationRow(TypedDict):
    id: UUID
    name: str
    value: dict | None
    event_date: date | None
    raw_quote: str | None
    document_id: UUID


async def query_observations_by_name_and_date_range(
    *,
    scope: Scope,
    name_substring: str,
    from_date: date | None,
    to_date: date | None,
) -> list[ObservationRow]:
    """Return entities of type 'observation' whose name contains the given
    substring (case-insensitive), within the date window.

    Args:
        scope: whose entities to read (user, and optionally one profile). The
            temporal path ("¿y el peso de los últimos 6 meses?") is the one
            that most obviously mixed two children: it returned every
            observation of the account, so two babies' weight curves came back
            as one series. Rows with a NULL profile_id stay in (pre-profile
            data).
        name_substring: case-insensitive substring of entity.name.
        from_date / to_date: inclusive bounds on event_date. None = unbounded.

    Returns:
        List of dicts with keys: id, name, value, event_date, raw_quote,
        document_id. Sorted ascending by event_date.

    The caller (chat orchestrator) formats this into a context table that
    is fed to the LLM for the structured-temporal-query path.
    """
    async with AsyncSessionLocal() as session:
        stmt = (
            sa.select(
                Entity.id,
                Entity.name,
                Entity.value,
                Entity.event_date,
                Entity.raw_quote,
                Entity.document_id,
            )
            .where(
                *scope.where(Entity),
                Entity.entity_type == "observation",
                Entity.deleted_at.is_(None),
                or_(
                    sa.func.lower(Entity.name).like(f"%{name_substring.lower()}%"),
                ),
            )
            .order_by(Entity.event_date.asc().nullslast())
        )
        if from_date is not None:
            stmt = stmt.where(Entity.event_date >= from_date)
        if to_date is not None:
            stmt = stmt.where(Entity.event_date <= to_date)
        # Cap at 50 rows to fit LLM context budget. T6 orchestrator
        # formats each row as a numbered context line; 50 entries comfortably
        # fits Mistral's context window with headroom for system prompt + reply.
        stmt = stmt.limit(50)
        result = await session.execute(stmt)
        return [
            ObservationRow(**{
                "id": row.id,
                "name": row.name,
                "value": row.value,
                "event_date": row.event_date,
                "raw_quote": row.raw_quote,
                "document_id": row.document_id,
            })
            for row in result.all()
        ]
