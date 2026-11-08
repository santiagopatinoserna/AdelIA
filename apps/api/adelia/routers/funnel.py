"""The funnel: two public counters in, one owner-only table out (audit 4.8).

`POST /funnel/{event}` is deliberately the least interesting endpoint in the
codebase. It takes no body, reads no header beyond what the framework needs to
route it, sets no cookie, stores no identifier, and answers 204 whatever
happens. All it can do is add 1 to an integer.

`GET /funnel/summary` is the only way back out and it is owner-only. It answers
404, not 403, for everyone else: a 403 tells a stranger that the numbers exist
and that some account can read them. `GET /funnel/usage` is the cost side of
the same table of numbers (services/usage) behind the same gate.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from adelia.auth import get_current_user
from adelia.config import settings
from adelia.services import funnel, usage

router = APIRouter(prefix="/funnel", tags=["funnel"])

# Only the pre-account events are writable from the internet. "demo_ask" is
# counted too, but by routers/demo, which needs the post-increment value as a
# budget; letting anyone POST it would let anyone burn the demo's daily
# allowance without ever asking a question.
PUBLIC_EVENTS = ("visit", "start")


@router.post("/{event}", status_code=status.HTTP_204_NO_CONTENT)
async def record_event(event: str) -> Response:
    """Add 1 to today's counter. No body, no cookie, no identifier, no reply.

    204 even for an unknown event name: this is called from a beacon on a
    page a visitor is leaving, nobody reads the status, and an error body
    would be one more thing an unauthenticated caller could probe.
    """
    if event in PUBLIC_EVENTS:
        await funnel.bump_quietly(event)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _require_owner(user: Any) -> None:
    """404 unless `user` is settings.owner_email. Unset owner: nobody passes."""
    owner = (settings.owner_email or "").strip().lower()
    email = (getattr(user, "email", "") or "").strip().lower()
    if not owner or email != owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("/summary")
async def funnel_summary(
    user: Annotated[Any, Depends(get_current_user)],
    days: int = 30,
) -> dict[str, Any]:
    """Visits, "Empezar" presses, signups and activations, one row per day.

    Owner-only, by email against settings.owner_email. With OWNER_EMAIL unset
    (the default, and every self-hosted install) nobody passes, which is the
    right default for a number that describes the business rather than the
    account asking.
    """
    _require_owner(user)
    rows = await funnel.summary(days)
    return {
        "days": len(rows),
        "columns": ["visit", "start", "signup", "activation", "demo_ask"],
        "rows": rows,
    }


@router.get("/usage")
async def usage_summary(
    user: Annotated[Any, Depends(get_current_user)],
    days: int = 30,
) -> dict[str, Any]:
    """Provider calls, tokens, OCR pages and audio seconds over the last `days`.

    Owner-only, same gate and same 404 as /summary. `estimated_usd` applies the
    list prices of services/usage_prices; models without an official price are
    named in `unpriced`. Divide by `active_accounts` for the mean per account.
    """
    _require_owner(user)
    return await usage.summary(days)
