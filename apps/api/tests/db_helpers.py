"""Shared helpers for Postgres-backed integration tests."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4


async def make_user(
    subscription_status: str = "active",
    *,
    created_days_ago: int | None = None,
) -> UUID:
    """Insert a throwaway user and return its id (FK target for sessions,
    briefings, profiles...).

    Defaults to an ACTIVE subscription: documents, chat, briefings, agent,
    enrichment and ingestion are behind adelia.auth.require_active_subscription,
    so a test user of those routes is a paying one. Pass "none" (or any other
    Stripe status) to exercise the 402 path.

    `created_days_ago` ages the row. It matters because the card-free trial
    (audit 4.7) is DERIVED from users.created_at: an account created just now
    with status "none" is inside its free trial and is NOT paywalled, so a
    test that wants the refusal has to say how old the account is. Pass a
    number comfortably past settings.free_trial_days to mean "the trial ran
    out".
    """
    from adelia.db import AsyncSessionLocal
    from adelia.models import User

    async with AsyncSessionLocal() as session:
        user = User(
            email=f"test-{uuid4()}@adelia.test",
            subscription_status=subscription_status,
        )
        if created_days_ago is not None:
            user.created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id
