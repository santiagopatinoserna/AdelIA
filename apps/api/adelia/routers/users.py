"""Account endpoints — GDPR right-to-erasure (Article 17) and the one
question the app has to ask before it can be clinically safe: who the baby is
(audit 4.3)."""

import asyncio
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.auth import get_current_user_id
from adelia.db import get_db
from adelia.enrichment import profile_service
from adelia.models import BlobTombstone, Document, Profile, User
from adelia.storage import S3Storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])
storage = S3Storage()


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Erase the account and every derived record + blob.

    DB graph goes via ON DELETE CASCADE (0011): documents → entities/chunks,
    briefings → citations/share_links, chat sessions → messages, profiles,
    ingestion links. S3 blobs are deleted best-effort after the response,
    from their tombstones; a failed blob delete must not resurrect the
    account (logged for ops, retried by the next sweep).
    """
    result = await db.execute(
        sa.select(Document.s3_key).where(Document.user_id == user_id)
    )
    s3_keys = [row[0] for row in result.all()]

    # Tombstones ride the SAME transaction as the erase: if blob deletion
    # fails afterwards, the keys survive for the startup sweep to retry —
    # no orphaned medical files with zero record of them.
    #
    # not_before=None EXPLICITLY, never omitted: merge() only copies the
    # attributes that were set on the given instance, so a bare
    # BlobTombstone(s3_key=key) leaves a future date in place. Audio blobs now
    # carry one from the moment they are uploaded (documents.upload_document),
    # so omitting it would keep a recording alive for up to 7 days AFTER the
    # account was erased. Erasure means now.
    for key in s3_keys:
        await db.merge(BlobTombstone(s3_key=key, not_before=None))
    await db.execute(sa.delete(User).where(User.id == user_id))
    await db.commit()

    # Her blobs go AFTER the 204, and only hers. This request used to await a
    # sweep of every due tombstone in the system before answering. With object
    # storage unreachable each key costs 4 to 9 s of botocore retries, and a
    # backlog of failed keys only grows, so the answer took 21.6 s in CI (the
    # e2e job runs no MinIO) and 30 to 52 s locally: the page sat on its
    # deleting state and e2e/poc-journey step 15 flaked in French, the run
    # that deletes later. She is erased at the commit above; the tombstones
    # are durable, and the boot and hourly sweeps own anybody else's backlog.
    if s3_keys:
        _spawn_erasure_sweep(s3_keys)

    logger.info("account erased user_id=%s blobs=%d", user_id, len(s3_keys))
    return None


# Strong references to post-erasure sweeps: the loop keeps only a weak one, so
# a bare create_task() can be collected mid-sweep (same trap as
# documents._BACKGROUND_TASKS).
_ERASURE_SWEEPS: set[asyncio.Task] = set()


def _spawn_erasure_sweep(keys: list[str]) -> asyncio.Task:
    task = asyncio.create_task(_sweep_after_erasure(keys))
    _ERASURE_SWEEPS.add(task)
    task.add_done_callback(_ERASURE_SWEEPS.discard)
    return task


async def _sweep_after_erasure(keys: list[str]) -> None:
    try:
        await sweep_blob_tombstones(keys=keys)
    except Exception:  # noqa: BLE001 — tombstones kept, next sweep retries
        logger.exception("sweep after account erasure failed (tombstones kept)")


async def drain_erasure_sweeps(grace_s: float = 10.0) -> None:
    """Wait for in-flight post-erasure sweeps, cancelling what outlives
    `grace_s`. The lifespan calls it before disposing the engine, like
    documents.cancel_background_pipelines. Cancelling loses nothing: a
    tombstone is only dropped after its blob is gone, so the next sweep
    retries whatever was cut short."""
    tasks = [task for task in _ERASURE_SWEEPS if not task.done()]
    if not tasks:
        return
    _done, pending = await asyncio.wait(tasks, timeout=grace_s)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.wait(pending, timeout=grace_s)


async def sweep_blob_tombstones(keys: list[str] | None = None) -> None:
    """Delete every due tombstoned blob, or only `keys`; drop a tombstone only
    once its blob is gone. Called post-erasure (her keys) and at startup and
    hourly (all of them, which retries previous failures).

    No session is held while storage works: a slow or unreachable endpoint
    used to pin a pooled connection for as long as botocore kept retrying."""
    from adelia.db import AsyncSessionLocal

    now = datetime.now(timezone.utc)
    due = sa.select(BlobTombstone.s3_key).where(
        sa.or_(BlobTombstone.not_before.is_(None), BlobTombstone.not_before <= now)
    )
    if keys is not None:
        due = due.where(BlobTombstone.s3_key.in_(keys))
    async with AsyncSessionLocal() as session:
        pending = [row[0] for row in (await session.execute(due)).all()]

    gone: list[str] = []
    for key in pending:
        try:
            await storage.delete_object(key)
        except Exception:  # noqa: BLE001 — keep tombstone, retry next sweep
            logger.exception("blob tombstone delete failed for %s (kept)", key)
            continue
        gone.append(key)

    if gone:
        async with AsyncSessionLocal() as session:
            await session.execute(
                sa.delete(BlobTombstone).where(BlobTombstone.s3_key.in_(gone))
            )
            await session.commit()


class SessionRevocation(BaseModel):
    token_version: int


@router.post("/me/sessions/revoke", response_model=SessionRevocation)
async def revoke_my_sessions(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Sign out everywhere: invalidate every bridge token already issued.

    The web signs a 15-minute token per request (apps/web/lib/backend-token.ts)
    and stamps `users.token_version` into it as the `tv` claim. Incrementing
    that column here makes every token minted before this call fail
    `get_current_user`, on this device and on any other, at once. That is the
    difference between the sign-out this product had until 2026-09-01 (delete
    the browser cookie and hope) and one that actually revokes.

    NOT behind require_active_subscription: leaving must never depend on
    paying. Idempotent in the only sense that matters — calling it twice
    simply revokes twice.
    """
    new_version = await db.scalar(
        sa.update(User)
        .where(User.id == user_id)
        .values(token_version=User.token_version + 1)
        .returning(User.token_version)
    )
    await db.commit()
    if new_version is None:
        # The row went away between authentication and the update (an erasure
        # racing a sign-out). Nothing left to revoke.
        raise HTTPException(status_code=404, detail="Account not found")
    logger.info("sessions revoked for user %s (token_version=%s)", user_id, new_version)
    return SessionRevocation(token_version=new_version)


@router.get("/me/export")
async def export_my_data(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Full data export, one click (GDPR art. 20): FHIR R4 bundle for the
    clinical core + a raw section for everything FHIR has no slot for.
    Download semantics via Content-Disposition."""
    from fastapi.responses import JSONResponse

    from adelia.services.data_export import build_export

    payload = await build_export(db, user_id)
    return JSONResponse(
        content=jsonable_encoder(payload),
        headers={
            "Content-Disposition": 'attachment; filename="adelia-export.json"',
        },
    )


# ---------------------------------------------------------------------------
# Onboarding: name, date of birth, sex (audit 4.3)
#
# Deliberately NOT behind require_active_subscription. It is asked before the
# dashboard, the answer is what makes the red-flag rules, the lab ranges, the
# growth percentiles and the briefing header work at all, and a parent who
# lets a subscription lapse must still be able to correct her child's date of
# birth.
# ---------------------------------------------------------------------------


class OnboardingStatus(BaseModel):
    #: True only for an account that has never been asked. The web layout
    #: redirects on this and on nothing else, so the screen appears once.
    needed: bool


class BabyOnboarding(BaseModel):
    display_name: str = Field(min_length=1, max_length=128)
    date_of_birth: date | None = None
    sex: Literal["M", "F", "other"] | None = None


async def _has_child_profile(db: AsyncSession, user_id: uuid.UUID) -> bool:
    n = await db.scalar(
        sa.select(sa.func.count())
        .select_from(Profile)
        .where(
            Profile.user_id == user_id,
            Profile.relationship == "child",
            Profile.deleted_at.is_(None),
        )
    )
    return bool(n)


async def _retire_untouched_own_row(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Soft-delete the "Mi perfil" row GET /enrichment/profiles auto-creates,
    when nothing hangs from it.

    The dashboard layout lists profiles before it sends a new account to
    onboarding, so every new mother got that row and then saw two chips, her
    baby and "Mi perfil" (in Spanish whatever her language), the second empty
    and never asked for (RECORRIDO_POC.md). A row that holds documents,
    entities, briefings, observations or chats is a v0.1 account's real data
    and stays. (Chunks hang from documents; consent events are an audit trail,
    not her data, and a soft delete leaves their link intact.)
    """
    from adelia.models import Briefing, ChatSession, Entity, Observation

    used = sa.or_(*(
        sa.exists().where(model.profile_id == Profile.id)
        for model in (Document, Entity, Briefing, Observation, ChatSession)
    ))
    await db.execute(
        sa.update(Profile)
        .where(
            Profile.user_id == user_id,
            Profile.relationship == "self",
            Profile.display_name == "Mi perfil",
            Profile.date_of_birth.is_(None),
            Profile.deleted_at.is_(None),
            ~used,
        )
        .values(deleted_at=datetime.now(timezone.utc), is_default=False)
        .execution_options(synchronize_session=False)
    )


async def _stamp_onboarded(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        sa.update(User)
        .where(User.id == user_id, User.onboarded_at.is_(None))
        .values(onboarded_at=datetime.now(timezone.utc))
    )


@router.get("/me/onboarding", response_model=OnboardingStatus)
async def onboarding_status(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Whether the baby screen still has to be shown.

    A child profile counts as an answer even when `onboarded_at` is NULL: the
    agent's `completar_perfil` tool and the profiles screen can both create
    one, and asking a parent who already told us her daughter's date of birth
    would read as the app not listening.
    """
    stamped = await db.scalar(sa.select(User.onboarded_at).where(User.id == user_id))
    if stamped is not None:
        return OnboardingStatus(needed=False)
    return OnboardingStatus(needed=not await _has_child_profile(db, user_id))


@router.post("/me/onboarding", status_code=status.HTTP_201_CREATED)
async def complete_onboarding(
    payload: BabyOnboarding,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create the baby's profile and close the screen, in ONE transaction.

    One endpoint rather than "create a profile, then mark onboarded": a
    half-finished onboarding (profile written, flag not) would ask the same
    mother the same three questions again with the answer already on file.

    The profile becomes the DEFAULT one, which is what makes every other
    surface (chat, briefing, agent, recorder) about the baby by default
    instead of about the "Mi perfil" row auto-created for legacy accounts.
    """
    if payload.date_of_birth is not None and payload.date_of_birth > date.today():
        # A future date of birth is a typo (or a pregnancy). Accepting it
        # would make age_in_months return None and quietly disable every
        # age-gated clinical rule.
        raise HTTPException(status_code=422, detail="date_of_birth is in the future")
    profile = await profile_service.create_profile(
        db,
        user_id=user_id,
        data=profile_service.ProfileCreate(
            display_name=payload.display_name.strip(),
            relationship="child",
            date_of_birth=payload.date_of_birth,
            sex=payload.sex,
            is_default=True,
        ),
    )
    await _retire_untouched_own_row(db, user_id)
    await _stamp_onboarded(db, user_id)
    await db.commit()
    return {
        "id": str(profile.id),
        "display_name": profile.display_name,
        "relationship": profile.relationship,
        "date_of_birth": profile.date_of_birth.isoformat() if profile.date_of_birth else None,
        "sex": profile.sex,
        "is_default": profile.is_default,
    }


@router.post("/me/onboarding/skip", status_code=status.HTTP_204_NO_CONTENT)
async def skip_onboarding(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """"Ahora no". The screen is skippable on purpose: a parent arriving at
    3 a.m. with a feverish baby must be able to reach the app in one tap, and
    the agent can ask for the date of birth later, in context."""
    await _stamp_onboarded(db, user_id)
    await db.commit()
    return None
