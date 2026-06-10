"""Postmark Inbound email webhook handler.

Postmark sends a JSON payload to our webhook URL with the parsed email content
+ attachments base64-encoded. We validate the HMAC signature, look up the user
by the alias in the `To:` address, and POST each attachment as a Document.

Configuration:
- POSTMARK_INBOUND_TOKEN env (server token used to HMAC-sign payloads)
- ADELIA_EMAIL_DOMAIN env (e.g. 'in.adelia.app')
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from datetime import datetime, UTC
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.config import settings
from adelia.models import EmailAlias

logger = logging.getLogger(__name__)


def _alias_for_user(user_id: UUID) -> str:
    """Deterministic but opaque alias from user_id. 8-char hex prefix."""
    digest = hashlib.sha256(str(user_id).encode()).hexdigest()[:10]
    return f"{digest}@{settings.adelia_email_domain}"


def validate_postmark_signature(raw_body: bytes, header_value: str | None) -> bool:
    """Verify HMAC SHA-256 signature from Postmark using POSTMARK_INBOUND_TOKEN."""
    if not settings.postmark_inbound_token:
        return False
    if not header_value:
        return False
    expected = hmac.new(
        settings.postmark_inbound_token.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, header_value.lower())


async def ensure_alias_for_user(
    session: AsyncSession, *, user_id: UUID
) -> EmailAlias:
    """Get or create the EmailAlias for a user. Deterministic alias from user_id."""
    stmt = select(EmailAlias).where(EmailAlias.user_id == user_id)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    alias = EmailAlias(user_id=user_id, alias=_alias_for_user(user_id))
    session.add(alias)
    await session.flush()
    return alias


async def lookup_user_by_alias(
    session: AsyncSession, *, alias: str
) -> UUID | None:
    """Find AdelIA user_id from an inbound email alias."""
    stmt = select(EmailAlias.user_id).where(EmailAlias.alias == alias.lower())
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def parse_to_address(raw_to: str) -> str | None:
    """Extract email out of 'Name <email@domain>' or plain 'email@domain' format."""
    if not raw_to:
        return None
    raw_to = raw_to.strip()
    if "<" in raw_to and ">" in raw_to:
        start = raw_to.find("<") + 1
        end = raw_to.find(">")
        if 0 < start < end:
            return raw_to[start:end].lower()
    if "@" in raw_to:
        return raw_to.lower()
    return None


async def handle_postmark_payload(payload: dict) -> dict:
    """Process a Postmark Inbound webhook payload.

    Returns dict with {action, status, attachments_queued, ...}.

    Steps:
    1. Extract recipient alias from To: field
    2. Look up AdelIA user_id by alias
    3. For each attachment: decode base64, POST internal /documents
       (deferred to v0.2.1 — handler returns metadata)
    """
    to_addr = parse_to_address(payload.get("To", ""))
    if to_addr is None:
        return {"action": "ignore", "status": "no_recipient"}

    from adelia.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        user_id = await lookup_user_by_alias(session, alias=to_addr)

    if user_id is None:
        return {
            "action": "no_link",
            "status": "error",
            "alias": to_addr,
            "reason": "no AdelIA user with this alias",
        }

    attachments = payload.get("Attachments", []) or []
    queued: list[dict] = []
    for att in attachments:
        name = att.get("Name", "attachment")
        content_b64 = att.get("Content", "")
        content_type = att.get("ContentType", "application/octet-stream")
        # In production: base64.b64decode(content_b64), then POST /documents.
        # For this commit we just gather metadata + return.
        try:
            size_bytes = len(base64.b64decode(content_b64)) if content_b64 else 0
        except Exception:
            size_bytes = 0
        queued.append({
            "name": name,
            "content_type": content_type,
            "size_bytes": size_bytes,
        })

    return {
        "action": "email_received",
        "status": "queued",
        "user_id": str(user_id),
        "alias": to_addr,
        "subject": payload.get("Subject"),
        "from": payload.get("From"),
        "attachments_count": len(queued),
        "attachments": queued,
        "received_at": datetime.now(UTC).isoformat(),
        "todo": "Attachment decode + POST /documents wiring deferred to v0.2.1",
    }
