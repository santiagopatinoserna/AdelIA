"""Webhook endpoints for Telegram + Postmark Inbound — separate from main
ingestion router because they use external signature validation instead of
get_current_user_id Depends.
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from adelia.auth import get_current_user_id
from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.ingestion.email_inbound import (
    ensure_alias_for_user,
    handle_postmark_payload,
    validate_postmark_signature,
)
from adelia.ingestion.telegram_bot import (
    get_bot_url,
    handle_update,
    mint_link_token,
    validate_telegram_secret,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingestion", tags=["ingestion-webhooks"])


# ----------------------------------------------------------------------------
# Telegram
# ----------------------------------------------------------------------------


@router.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    """Telegram POSTs Updates here. Validates the secret_token configured via
    setWebhook + processes the update."""
    if not validate_telegram_secret(x_telegram_bot_api_secret_token):
        raise HTTPException(status_code=401, detail="Invalid Telegram secret")
    payload = await request.json()
    result = await handle_update(payload)
    return result


@router.get("/telegram/link")
async def telegram_link(user_id: UUID = Depends(get_current_user_id), locale: str = "es"):
    """Mint a signed link token + return bot URL. User pastes token into
    Telegram chat with the bot via /start <token>. `locale` (the UI locale)
    travels inside the token so the bot answers in that language."""
    if not settings.auth_secret:
        raise HTTPException(status_code=503, detail="AUTH_SECRET not configured")
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=503, detail="Telegram bot not configured")
    token = mint_link_token(user_id, locale)
    return {
        "bot_url": get_bot_url(),
        "link_token": token,
        "instructions": (
            f"Abre {get_bot_url()} en Telegram y envía: /start {token[:20]}..."
        ),
    }


# ----------------------------------------------------------------------------
# Postmark Inbound (email)
# ----------------------------------------------------------------------------


@router.post("/email/webhook", include_in_schema=False)
async def postmark_inbound_webhook(
    request: Request,
    x_postmark_signature: str | None = Header(default=None),
):
    """Postmark Inbound webhook handler. Validates HMAC + dispatches to handler."""
    raw_body = await request.body()
    if not validate_postmark_signature(raw_body, x_postmark_signature):
        raise HTTPException(status_code=401, detail="Invalid Postmark signature")
    import json

    payload = json.loads(raw_body.decode("utf-8"))
    result = await handle_postmark_payload(payload)
    return result


@router.get("/email/alias")
async def email_alias(
    user_id: UUID = Depends(get_current_user_id),
):
    """Get-or-create the user's unique inbound email alias."""
    async with AsyncSessionLocal() as session:
        alias = await ensure_alias_for_user(session, user_id=user_id)
        await session.commit()
    return {
        "alias": alias.alias,
        "instructions": (
            "Configura forward de tu email a este alias. Lo recibido se ingestará "
            "automáticamente a tu vault AdelIA."
        ),
    }
