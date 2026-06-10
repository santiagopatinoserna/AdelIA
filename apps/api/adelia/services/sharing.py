"""M6 sharing service — signed URL + TTL + revocation.

Generates opaque, unguessable tokens for share links. Token = HMAC-signed
random bytes — never sequential or predictable. Token is the lookup key,
not the briefing UUID, so cross-user enumeration is impossible.

WeasyPrint PDF rendering reuses the M5 Jinja2 template (single source of truth
between in-app HTML preview and shareable PDF).
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, UTC, timedelta
from typing import Literal
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.models import Briefing, ShareLink
from adelia.services.briefing_html_renderer import render_briefing_html
from adelia.schemas import BriefingPayload

logger = logging.getLogger(__name__)

_DEFAULT_TTL = timedelta(hours=24)
_MAX_TTL = timedelta(days=30)


def _new_token() -> str:
    """Cryptographically opaque token. 32 bytes urlsafe → ~43 chars."""
    return secrets.token_urlsafe(32)


async def create_share_link(
    session: AsyncSession,
    *,
    briefing_id: UUID,
    user_id: UUID,
    ttl: timedelta | None = None,
) -> ShareLink:
    """Create a new share link. Cross-user isolation: caller MUST verify
    briefing.user_id == user_id BEFORE calling (done at router layer).
    """
    if ttl is None:
        ttl = _DEFAULT_TTL
    if ttl > _MAX_TTL:
        ttl = _MAX_TTL
    if ttl.total_seconds() < 60:
        ttl = timedelta(minutes=1)

    link = ShareLink(
        briefing_id=briefing_id,
        user_id=user_id,
        token=_new_token(),
        expires_at=datetime.now(UTC) + ttl,
    )
    session.add(link)
    await session.flush()
    return link


async def list_shares_for_user(
    session: AsyncSession, *, user_id: UUID
) -> list[ShareLink]:
    stmt = (
        select(ShareLink)
        .where(ShareLink.user_id == user_id)
        .order_by(ShareLink.created_at.desc())
        .limit(100)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def revoke_share(
    session: AsyncSession, *, token: str, user_id: UUID
) -> bool:
    """Revoke a share link by token. Only owner can revoke (cross-user isolation).
    Returns True if revoked, False if not found or not owned."""
    stmt = (
        update(ShareLink)
        .where(ShareLink.token == token)
        .where(ShareLink.user_id == user_id)
        .values(revoked=True)
    )
    result = await session.execute(stmt)
    return (result.rowcount or 0) > 0


@dataclass(frozen=True)
class ResolvedShare:
    """Result of resolving a token to a briefing (public endpoint use)."""
    briefing_id: UUID
    briefing_payload: BriefingPayload | None
    briefing_html: str | None
    expires_at: datetime
    view_count: int


async def resolve_token(
    session: AsyncSession, *, token: str
) -> ResolvedShare | None:
    """Resolve a share token to its briefing data (PUBLIC endpoint use).

    Validates:
    - token exists
    - not revoked
    - not expired

    Increments view_count + sets last_accessed_at as side effect.
    Returns None on any validation failure (caller renders 404).
    """
    stmt = select(ShareLink).where(ShareLink.token == token)
    result = await session.execute(stmt)
    link = result.scalar_one_or_none()
    if link is None:
        return None
    if link.revoked:
        return None
    if link.expires_at <= datetime.now(UTC):
        return None

    # Load the briefing
    b_stmt = (
        select(Briefing)
        .where(Briefing.id == link.briefing_id)
        .where(Briefing.deleted_at.is_(None))
    )
    b_result = await session.execute(b_stmt)
    briefing = b_result.scalar_one_or_none()
    if briefing is None:
        return None

    # Bump view_count + last_accessed_at
    await session.execute(
        update(ShareLink)
        .where(ShareLink.id == link.id)
        .values(
            access_count=(link.access_count or 0) + 1,
            last_accessed_at=datetime.now(UTC),
        )
    )
    await session.commit()

    payload = None
    if briefing.payload:
        payload = BriefingPayload.model_validate(briefing.payload)

    return ResolvedShare(
        briefing_id=briefing.id,
        briefing_payload=payload,
        briefing_html=briefing.html_render,
        expires_at=link.expires_at,
        view_count=(link.access_count or 0) + 1,
    )


def render_pdf(payload: BriefingPayload) -> bytes:
    """Render briefing payload to PDF bytes via WeasyPrint.

    Reuses the M5 Jinja2 template (single source of truth: same HTML for
    in-app preview + PDF download + shared link viewer).

    Returns PDF binary bytes.
    Raises ImportError if WeasyPrint not installed (deferred dep at v0.2).
    """
    from weasyprint import HTML

    html_str = render_briefing_html(payload)
    # WeasyPrint reads URLs as file paths by default; base_url makes /static/* resolvable
    pdf_bytes = HTML(string=html_str).write_pdf()
    return pdf_bytes


SharingMode = Literal["link", "pdf", "html"]
