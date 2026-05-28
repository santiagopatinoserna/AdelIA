"""M6 sharing router — POST/GET/DELETE share links + public viewer + PDF download.

Routes:
- POST   /shares                       create share link for a briefing (auth'd)
- GET    /shares                       list user's shares (auth'd)
- DELETE /shares/{token}               revoke (auth'd)
- GET    /s/{token}                    PUBLIC view (no auth)
- GET    /s/{token}/pdf                PUBLIC PDF download (no auth)
- GET    /briefings/{id}/pdf           direct PDF for owner (auth'd)
"""
from __future__ import annotations

import logging
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.auth import get_current_user_id
from adelia.db import AsyncSessionLocal, get_db
from adelia.services import sharing as sharing_svc
from adelia.services import briefing_repo

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sharing"])


class CreateShareRequest(BaseModel):
    briefing_id: UUID
    ttl_hours: int = Field(default=24, ge=1, le=720)  # 1h - 30d


class ShareLinkOut(BaseModel):
    token: str
    briefing_id: UUID
    expires_at: object
    revoked: bool = False
    access_count: int = 0
    last_accessed_at: object | None = None
    created_at: object
    share_url: str  # full public URL


def _to_share_out(link, *, app_url: str) -> ShareLinkOut:
    return ShareLinkOut(
        token=link.token,
        briefing_id=link.briefing_id,
        expires_at=link.expires_at,
        revoked=bool(link.revoked),
        access_count=link.access_count or 0,
        last_accessed_at=link.last_accessed_at,
        created_at=link.created_at,
        share_url=f"{app_url}/s/{link.token}",
    )


def _app_url() -> str:
    from adelia.config import settings
    return settings.adelia_app_url.rstrip("/")


@router.post("/shares", status_code=status.HTTP_201_CREATED, response_model=ShareLinkOut)
async def create_share(
    payload: CreateShareRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    # Verify briefing belongs to user
    briefing = await briefing_repo.get_by_id(
        db, briefing_id=payload.briefing_id, user_id=user_id
    )
    if briefing is None:
        raise HTTPException(status_code=404, detail="Briefing not found")
    if briefing.status != "ready":
        raise HTTPException(
            status_code=409,
            detail="Briefing not ready (status: " + str(briefing.status) + ")",
        )

    link = await sharing_svc.create_share_link(
        db,
        briefing_id=payload.briefing_id,
        user_id=user_id,
        ttl=timedelta(hours=payload.ttl_hours),
    )
    await db.commit()
    return _to_share_out(link, app_url=_app_url())


@router.get("/shares", response_model=list[ShareLinkOut])
async def list_my_shares(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    links = await sharing_svc.list_shares_for_user(db, user_id=user_id)
    return [_to_share_out(l, app_url=_app_url()) for l in links]


@router.delete("/shares/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share_endpoint(
    token: str,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    ok = await sharing_svc.revoke_share(db, token=token, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Share not found")
    await db.commit()
    return Response(status_code=204)


# ----------------------------------------------------------------------------
# PUBLIC viewer (no auth) — uses opaque token as the only credential
# ----------------------------------------------------------------------------


@router.get("/s/{token}", response_class=HTMLResponse)
async def public_view(token: str):
    """Public HTML view of a shared briefing. No auth — token IS the credential."""
    async with AsyncSessionLocal() as session:
        resolved = await sharing_svc.resolve_token(session, token=token)
    if resolved is None or resolved.briefing_html is None:
        # Generic 404 to avoid token enumeration
        return HTMLResponse(
            content="<html><body><h1>404</h1><p>This link is invalid or has expired.</p></body></html>",
            status_code=404,
        )
    return HTMLResponse(content=resolved.briefing_html)


@router.get("/s/{token}/pdf")
async def public_pdf(token: str):
    """Public PDF download of a shared briefing."""
    async with AsyncSessionLocal() as session:
        resolved = await sharing_svc.resolve_token(session, token=token)
    if resolved is None or resolved.briefing_payload is None:
        raise HTTPException(status_code=404, detail="Invalid or expired link")

    try:
        pdf_bytes = sharing_svc.render_pdf(resolved.briefing_payload)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="PDF rendering unavailable (WeasyPrint not installed)",
        )
    except Exception as e:
        logger.exception("PDF render failed: %s", e)
        raise HTTPException(status_code=500, detail="PDF render error")

    filename = f"briefing-{resolved.briefing_id.hex[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# ----------------------------------------------------------------------------
# Owner PDF endpoint (no share token needed if owner)
# ----------------------------------------------------------------------------


@router.get("/briefings/{briefing_id}/pdf")
async def owner_pdf(
    briefing_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    briefing = await briefing_repo.get_by_id(db, briefing_id=briefing_id, user_id=user_id)
    if briefing is None:
        raise HTTPException(status_code=404, detail="Briefing not found")
    if briefing.status != "ready" or briefing.payload is None:
        raise HTTPException(status_code=409, detail="Briefing not ready")

    from adelia.schemas import BriefingPayload
    payload = BriefingPayload.model_validate(briefing.payload)

    try:
        pdf_bytes = sharing_svc.render_pdf(payload)
    except ImportError:
        raise HTTPException(status_code=503, detail="WeasyPrint not installed")
    except Exception as e:
        logger.exception("PDF render failed: %s", e)
        raise HTTPException(status_code=500, detail="PDF render error")

    filename = f"briefing-{briefing.id.hex[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
