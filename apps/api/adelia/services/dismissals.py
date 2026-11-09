"""Cards and notices she closed on the panel, remembered per account.

"La barra de conectar a Telegram nunca desaparece" (Santiago, 2026-11-09). A
closed card used to come back on the next request: the suggestions are built
fresh each time and nothing remembered the "no". The key is the kind of card,
from a closed shape (`KEY_PATTERN`), never free text.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.db import AsyncSessionLocal, engine
from adelia.models import UiDismissal

# Lower-case words joined by underscores, like the card intents themselves.
KEY_PATTERN = r"^[a-z][a-z_]{0,39}$"


async def ensure_table() -> None:
    """Create the table if it is missing, without touching alembic_version.

    For tests and the shared dev database only, where other branches stamp
    their own revisions (same as services.analytics.ensure_tables); everywhere
    else `alembic upgrade head` creates it (0028_ui_dismissals)."""
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: UiDismissal.metadata.create_all(
            c, tables=[UiDismissal.__table__]))


async def dismiss(user_id: UUID, key: str) -> None:
    """Remember that she closed `key`. Closing twice is closing once."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            insert(UiDismissal).values(user_id=user_id, key=key)
            .on_conflict_do_nothing(index_elements=["user_id", "key"]))
        await session.commit()


async def dismissed_keys(session: AsyncSession, user_id: UUID) -> frozenset[str]:
    rows = await session.scalars(select(UiDismissal.key).where(UiDismissal.user_id == user_id))
    return frozenset(rows)
