import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from adelia.auth import get_current_user_id
from adelia.db import AsyncSessionLocal
from adelia.enrichment import profile_service
from adelia.models import ConsentEvent

router = APIRouter(prefix="/consent-events", tags=["consent"])


class DeclinedEventIn(BaseModel):
    # Only 'declined' is accepted here: 'informed' events are created
    # atomically with the document row inside POST /documents.
    event_type: Literal["recording_declined"]
    profile_id: uuid.UUID | None = None
    policy_version: str = Field(min_length=1, max_length=64)
    locale: str = Field(min_length=2, max_length=8)


class ConsentEventOut(BaseModel):
    id: uuid.UUID
    created_at: str


@router.post("", response_model=ConsentEventOut, status_code=status.HTTP_201_CREATED)
async def create_declined_event(
    payload: DeclinedEventIn,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
    if payload.profile_id is not None:
        # Ownership check before persisting — a client-supplied profile_id must be
        # verified against user_id, same IDOR guard as documents.py.
        # Same idiom as adelia.routers.enrichment.get_user_profile.
        async with AsyncSessionLocal() as db:
            owned_profile = await profile_service.get_profile(
                db, profile_id=payload.profile_id, user_id=user_id
            )
        if owned_profile is None:
            raise HTTPException(status_code=404, detail="Profile not found")

    ev = ConsentEvent(
        user_id=user_id,
        profile_id=payload.profile_id,
        event_type=payload.event_type,
        policy_version=payload.policy_version,
        locale=payload.locale,
    )
    async with AsyncSessionLocal() as db:
        db.add(ev)
        await db.commit()
        await db.refresh(ev)
    return ConsentEventOut(id=ev.id, created_at=ev.created_at.isoformat())
