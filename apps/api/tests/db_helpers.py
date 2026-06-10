"""Shared helpers for Postgres-backed integration tests."""

from uuid import UUID, uuid4


async def make_user() -> UUID:
    """Insert a throwaway user and return its id (FK target for sessions,
    briefings, profiles...)."""
    from adelia.db import AsyncSessionLocal
    from adelia.models import User

    async with AsyncSessionLocal() as session:
        user = User(email=f"test-{uuid4()}@adelia.test")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id
