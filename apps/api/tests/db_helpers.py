"""Shared helpers for Postgres-backed integration tests."""

from uuid import UUID, uuid4


async def make_user(subscription_status: str = "active") -> UUID:
    """Insert a throwaway user and return its id (FK target for sessions,
    briefings, profiles...).

    Defaults to an ACTIVE subscription: documents, chat, briefings, agent,
    enrichment and ingestion are behind adelia.auth.require_active_subscription,
    so a test user of those routes is a paying one. Pass "none" (or any other
    Stripe status) to exercise the 402 path.
    """
    from adelia.db import AsyncSessionLocal
    from adelia.models import User

    async with AsyncSessionLocal() as session:
        user = User(
            email=f"test-{uuid4()}@adelia.test",
            subscription_status=subscription_status,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id
