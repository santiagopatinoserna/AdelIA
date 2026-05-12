from datetime import date
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import or_

from adelia.db import AsyncSessionLocal
from adelia.models import Entity


async def query_observations_by_name_and_date_range(
    *,
    user_id: UUID,
    name_substring: str,
    from_date: date | None,
    to_date: date | None,
) -> list[dict[str, Any]]:
    """Return entities of type 'observation' whose name contains the given
    substring (case-insensitive), within the date window.

    Args:
        user_id: filter to the calling user's entities.
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
                Entity.user_id == user_id,
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
        result = await session.execute(stmt)
        return [
            {
                "id": row.id,
                "name": row.name,
                "value": row.value,
                "event_date": row.event_date,
                "raw_quote": row.raw_quote,
                "document_id": row.document_id,
            }
            for row in result.all()
        ]
