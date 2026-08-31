from typing import Annotated, Any
from uuid import UUID

import sqlalchemy as sa
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from adelia.config import settings


bearer_scheme = HTTPBearer()


def decode_session_token(token: str) -> dict[str, Any]:
    if not settings.auth_secret:
        # An empty secret would happily verify tokens signed with "" —
        # i.e. anyone could forge a session. Refuse to authenticate at all.
        raise RuntimeError("AUTH_SECRET not configured")
    return jwt.decode(token, settings.auth_secret, algorithms=["HS256"])


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> Any:
    """The `users` row behind the bearer token, loaded ONCE per request.

    FastAPI caches each dependency within a request, so get_current_user_id
    and require_active_subscription below share this single SELECT. They used
    to cost two: get_current_user_id loaded the whole row only to prove the
    account existed and threw it away, then subscription_status_for opened a
    SECOND session and read the same primary key again. Two pool checkouts and
    two round-trips per authenticated request on every route of six routers,
    in a single-event-loop process whose pool exhaustion is documented in
    routers/documents.py.

    Returns the ORM object, not a UUID: `expire_on_commit=False` (db.py) means
    reading `user.subscription_status` after the session closes issues no SQL.
    """
    try:
        payload = decode_session_token(credentials.credentials)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server auth not configured",
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token missing sub")
    try:
        user_id = UUID(sub)
    except ValueError:
        raise HTTPException(status_code=401, detail="Token sub is not a valid UUID")

    # Tokens must not outlive the account (GDPR erasure): a JWT is only a
    # claim — the user row is the source of truth.
    from adelia.db import AsyncSessionLocal
    from adelia.models import User

    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    return user


async def get_current_user_id(
    user: Annotated[Any, Depends(get_current_user)],
) -> UUID:
    """The public contract every router depends on: the caller's user id.

    Annotated[Any, ...] rather than Annotated[User, ...] on purpose: `User` is
    imported lazily inside get_current_user (importing adelia.models at module
    scope would build the engine at import time), and FastAPI resolves these
    hints at import time — an unresolvable forward reference degrades the
    parameter into a query param and every guarded route answers 422.
    """
    return user.id


# ---------------------------------------------------------------------------
# Paywall
#
# Until 2026-08-31 the ONLY subscription check in the whole product lived in
# apps/web/app/[locale]/dashboard/layout.tsx. ACTIVE_STATUSES was read
# nowhere but routers/billing.py, so a valid JWT (or a linked Telegram chat)
# reached documents, chat, briefings, the agent and every enrichment route
# for free, spending Mistral OCR/Voxtral credit with no ceiling. The business
# rule now lives with the data it protects.
#
# 402 Payment Required, not 403: the caller is authenticated and the block is
# lifted by paying, which is exactly what the status code means.
# ---------------------------------------------------------------------------

SUBSCRIPTION_REQUIRED_DETAIL = "Subscription required"


def billing_is_enabled() -> bool:
    """False when this deployment sells nothing.

    Without STRIPE_SECRET_KEY, /billing/checkout and /billing/portal already
    answer 503 and the webhook that writes users.subscription_status never
    fires, so no account can ever leave "none". Charging a toll nobody can pay
    makes the self-hosted AGPL install the README documents ("## Self-host")
    unusable: every product route 402s and the only way back in is an
    undocumented UPDATE in SQL. Same condition as _require_stripe() in
    routers/billing.py, so gate and billing cannot disagree.

    This cannot fail open on the hosted SaaS: if the key were empty there,
    checkout would already be dead and there would be no revenue to protect.
    """
    return bool(settings.stripe_secret_key)


def _status_is_active(value: str | None) -> bool:
    """ACTIVE_STATUSES is imported lazily: routers.billing imports this
    module, so a module-level import would be circular."""
    from adelia.routers.billing import ACTIVE_STATUSES

    if not billing_is_enabled():
        return True
    return (value or "none") in ACTIVE_STATUSES


async def subscription_status_for(user_id: UUID) -> str:
    """The user's mirrored Stripe status ("none" when never subscribed).

    Standalone lookup for callers with no request context — the Telegram bot
    (ingestion/telegram_bot.py) has no User row in hand. HTTP routes go
    through require_active_subscription, which reads the row that
    get_current_user already loaded, so this is NOT the per-request path.
    """
    from adelia.db import AsyncSessionLocal
    from adelia.models import User

    async with AsyncSessionLocal() as session:
        value = await session.scalar(
            sa.select(User.subscription_status).where(User.id == user_id)
        )
    return value or "none"


async def has_active_subscription(user_id: UUID) -> bool:
    """True when the user may use the product (trialing or active)."""
    return _status_is_active(await subscription_status_for(user_id))


async def require_active_subscription(
    user: Annotated[Any, Depends(get_current_user)],
) -> UUID:
    """Dependency: authenticated AND paying, or 402.

    Applied to what SPENDS money — uploads (Mistral OCR/Voxtral), the chat
    and agent turns, briefing generation, enrichment and ingestion — and
    deliberately NOT to reads, deletes or the sharing links a parent may need
    to revoke. Cancelling a subscription must not close the door on her own
    records, on erasing one of them, or on exporting them: GDPR art. 15, 17
    and 20 are not features one stops paying for. Nor is it applied to health
    or billing (the way out of a 402), nor to the unauthenticated webhooks
    Stripe and Telegram call.
    """
    if not _status_is_active(user.subscription_status):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=SUBSCRIPTION_REQUIRED_DETAIL,
        )
    return user.id
