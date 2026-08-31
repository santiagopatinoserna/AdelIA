"""Briefings router — POST/GET/list/regenerate/DELETE endpoints.

Async generation pattern (per M5 brainstorm decision #1):
- POST returns 202 + briefing_id; orchestrator runs as BackgroundTask
- Frontend polls GET /briefings/{id} until status='ready'

Cross-user isolation: all routes use get_current_user_id Depends + 404 opaque.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.auth import get_current_user_id, require_active_subscription
from adelia.db import get_db
from adelia.schemas import (
    BriefingCreate,
    BriefingDetailOut,
    BriefingOut,
    BriefingPayload,
    BriefingStatus,
    Specialty,
)
from adelia.services import briefing_orchestrator, briefing_repo

router = APIRouter(prefix="/briefings", tags=["briefings"])
# Generating a briefing is a 5-stage LLM pipeline; re-reading one she already
# generated, or deleting it, is not.
# The paywall (adelia/auth.require_active_subscription) is applied PER ROUTE,
# not on the APIRouter, so it covers what spends money and nothing else.
# Router-level it also covered the reads and the deletes: a mother who
# cancelled saw her baby's records, transcripts and briefings answer 402 and
# could not erase a single document. GDPR art. 15 (access), 17 (erasure) and
# 20 (portability) are not features one stops paying for.
PAID = Depends(require_active_subscription)


def _to_out(briefing) -> BriefingOut:
    return BriefingOut(
        id=briefing.id,
        target_specialty=Specialty(briefing.target_specialty),
        status=BriefingStatus(briefing.status),
        is_stale=briefing.is_stale,
        created_at=briefing.created_at,
        completed_at=briefing.completed_at,
        error_message=briefing.error_message,
    )


def _to_detail(briefing) -> BriefingDetailOut:
    payload = None
    if briefing.payload:
        payload = BriefingPayload.model_validate(briefing.payload)
    return BriefingDetailOut(
        id=briefing.id,
        target_specialty=Specialty(briefing.target_specialty),
        status=BriefingStatus(briefing.status),
        is_stale=briefing.is_stale,
        created_at=briefing.created_at,
        completed_at=briefing.completed_at,
        error_message=briefing.error_message,
        payload=payload,
        html_render=briefing.html_render,
    )


def _enqueue(
    background_tasks: BackgroundTasks,
    briefing_id: UUID,
    user_id: UUID,
    target_specialty: Specialty,
    locale: str = "es",
) -> None:
    """Wrap orchestrator.run in BackgroundTasks. Override in tests."""
    background_tasks.add_task(
        briefing_orchestrator.run,
        briefing_id=briefing_id,
        user_id=user_id,
        target_specialty=target_specialty,
        locale=locale,
    )


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BriefingOut,
    dependencies=[PAID],
)
async def create_briefing(
    payload: BriefingCreate,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    briefing = await briefing_repo.create_briefing(
        db, user_id=user_id, target_specialty=payload.target_specialty
    )
    await db.commit()
    _enqueue(background_tasks, briefing.id, user_id, payload.target_specialty, payload.locale)
    return _to_out(briefing)


@router.get("", response_model=list[BriefingOut])
async def list_briefings(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    rows = await briefing_repo.list_for_user(db, user_id=user_id)
    return [_to_out(b) for b in rows]


@router.get("/{briefing_id}", response_model=BriefingDetailOut)
async def get_briefing(
    briefing_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    briefing = await briefing_repo.get_by_id(db, briefing_id=briefing_id, user_id=user_id)
    if briefing is None:
        raise HTTPException(status_code=404, detail="Not found")
    return _to_detail(briefing)


@router.post(
    "/{briefing_id}/regenerate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BriefingOut,
    dependencies=[PAID],
)
async def regenerate_briefing(
    briefing_id: UUID,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    original = await briefing_repo.get_by_id(db, briefing_id=briefing_id, user_id=user_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Not found")
    new = await briefing_repo.create_briefing(
        db,
        user_id=user_id,
        target_specialty=Specialty(original.target_specialty),
    )
    await db.commit()
    original_locale = (original.payload or {}).get("locale", "es")
    _enqueue(
        background_tasks, new.id, user_id,
        Specialty(original.target_specialty), original_locale,
    )
    return _to_out(new)


@router.delete("/{briefing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_briefing(
    briefing_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    ok = await briefing_repo.soft_delete(db, briefing_id=briefing_id, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    await db.commit()
    return Response(status_code=204)
