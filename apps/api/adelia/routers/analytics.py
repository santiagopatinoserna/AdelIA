"""Consented journeys: two public writes, two admin-only reads (2026-11-07).

`POST /analytics/collect` takes a batch from lib/analytics.ts and answers 204
whatever happens, like /funnel: it is called from sendBeacon on a page being
left, nobody reads the status, and an error body would be one more thing an
unauthenticated caller could probe. Every refusal (no consent, GPC, a bot, a
malformed body) is the same silent 204. services/analytics decides.

`POST /analytics/consent` stores the proof of an answer to the banner.

`GET /analytics/summary` and `GET /analytics/access` are for the admins of
auth.is_admin (ADMIN_EMAILS plus OWNER_EMAIL, the same rule as /funnel) and
answer 404 to everyone else, signed in or not: a 403 or a 401
would tell a stranger that the numbers exist.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from adelia.auth import get_current_user, is_admin
from adelia.config import settings
from adelia.services import analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])

_optional_bearer = HTTPBearer(auto_error=False)


async def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
) -> Any:
    """The signed-in user if she is an admin (auth.is_admin), else a 404."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        user = await get_current_user(credentials)
    except HTTPException:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return user


class ConsentIn(BaseModel):
    consent_id: uuid.UUID
    choice: Literal["accepted", "rejected", "withdrawn"]
    version: str = Field(pattern=r"^[0-9A-Za-z.\-]{1,16}$")
    source: Literal["banner", "settings", "privacy"]
    # Only read with "withdrawn": the visitor id this browser used, so what it
    # sent can be deleted with the withdrawal.
    forget_visitor: uuid.UUID | None = None


@router.post("/consent", status_code=status.HTTP_204_NO_CONTENT)
async def record_consent(payload: ConsentIn) -> Response:
    await analytics.record_consent(
        consent_id=payload.consent_id, choice=payload.choice, version=payload.version,
        source=payload.source, forget_visitor=payload.forget_visitor,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/collect", status_code=status.HTTP_204_NO_CONTENT)
async def collect(request: Request) -> Response:
    payload = analytics.parse_body(await request.body())
    if payload is not None:
        # Cloudflare overwrites CF-IPCountry at the edge, so it is believed
        # exactly where CF-Connecting-IP is (ratelimit.client_ip). The country
        # is all that is kept of the address.
        country = (
            analytics.clean_country(request.headers.get("cf-ipcountry"))
            if settings.trust_cf_connecting_ip
            else None
        )
        try:
            await analytics.ingest(
                payload,
                user_agent=request.headers.get("user-agent"),
                gpc=request.headers.get("sec-gpc", "").strip() == "1",
                country=country,
            )
        except Exception:  # noqa: BLE001 — a lost batch is not an incident
            analytics.logger.warning("analytics: batch not stored", exc_info=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/access", status_code=status.HTTP_204_NO_CONTENT)
async def access(_: Annotated[Any, Depends(require_admin)]) -> Response:
    """204 for an admin, 404 for anyone else. The web asks before drawing the
    link to the admin page in Settings."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/summary")
async def summary(_: Annotated[Any, Depends(require_admin)], days: int = 30) -> dict[str, Any]:
    return await analytics.summary(days)
