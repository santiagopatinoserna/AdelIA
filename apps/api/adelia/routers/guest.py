"""Guest accounts (decision of 2026-11-06, services/guest.py).

`POST /guest` is public: the web's Auth.js "guest" provider calls it on a
visitor's first question and signs the returned id into the same session JWT
an account gets. It needs no secret because the id alone opens nothing; only
the web, holding AUTH_SECRET, can turn it into a session. What it does need is
a brake, so a bot cannot mint identities by the thousand: 5 a minute
(ratelimit.ROUTE_BUDGETS) and GUEST_SIGNUPS_PER_HOUR an hour, per address.

`POST /guest/claim` and `POST /guest/adopt` are "Guardar mi cuenta": the guest
asks for a token for her email, the magic link carries it, and the account the
link signs in adopts the guest's vault.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from adelia import ratelimit
from adelia.auth import get_current_user, get_current_user_id
from adelia.config import settings
from adelia.services import guest as guest_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/guest", tags=["guest"])

GUEST_SIGNUPS_PER_HOUR = 30

# Strong references to the post-response embedding fills (the loop keeps weak ones).
_SEED_TASKS: set[asyncio.Task] = set()


class GuestRequest(BaseModel):
    locale: str = Field(default="es", max_length=8)


class ClaimRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class AdoptRequest(BaseModel):
    token: str = Field(min_length=10, max_length=128)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_guest(payload: GuestRequest, request: Request) -> dict[str, str]:
    if settings.rate_limit_enabled:
        ip = request.client.host if request.client else "unknown"
        allowed, retry_after = ratelimit.check_window(
            "guest-hour", f"ip:{ip}", GUEST_SIGNUPS_PER_HOUR, 3600.0)
        if not allowed:
            raise HTTPException(status_code=429, detail="Rate limit exceeded",
                                headers={"Retry-After": str(int(retry_after) + 1)})
    created = await guest_service.create_guest(payload.locale)
    if created.missing_embeddings:
        task = asyncio.create_task(
            guest_service.fill_seed_embeddings(created.user_id, created.missing_embeddings))
        _SEED_TASKS.add(task)
        task.add_done_callback(_SEED_TASKS.discard)
    logger.info("guest created user_id=%s", created.user_id)
    return {"user_id": str(created.user_id), "profile_id": str(created.profile_id)}


async def drain_seed_tasks() -> None:
    """Cancel and await the embedding fills (lifespan, before engine.dispose)."""
    tasks = [t for t in _SEED_TASKS if not t.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@router.post("/claim")
async def claim_guest(
    payload: ClaimRequest, user: Annotated[Any, Depends(get_current_user)]
) -> dict[str, str]:
    if not getattr(user, "is_guest", False):
        raise HTTPException(status_code=409, detail="Not a guest account")
    try:
        token = await guest_service.create_claim(user.id, payload.email)
    except guest_service.ClaimError:
        raise HTTPException(status_code=422, detail="Invalid email")
    return {"token": token}


@router.post("/adopt")
async def adopt_guest(
    payload: AdoptRequest, user_id: Annotated[uuid.UUID, Depends(get_current_user_id)]
) -> dict[str, str]:
    try:
        guest_id = await guest_service.adopt_guest(token=payload.token, user_id=user_id)
    except guest_service.ClaimError as exc:
        logger.info("guest adoption refused for user %s: %s", user_id, exc)
        raise HTTPException(status_code=404, detail="Claim not found")
    return {"adopted": str(guest_id)}
