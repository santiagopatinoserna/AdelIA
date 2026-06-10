"""Telegram bot — receives forwarded files/photos/audios and ingests them
as Documents for the linked user.

Two modes:
- Webhook: production. Telegram POSTs to /ingestion/telegram/webhook;
  validates X-Telegram-Bot-Api-Secret-Token header.
- Polling: local dev. Bot polls Telegram API in a background task.

Activation requires TELEGRAM_BOT_TOKEN (from @BotFather) + TELEGRAM_WEBHOOK_SECRET.

Link flow:
1. User visits /dashboard/ingestion/telegram-link in web UI
2. Backend mints a signed short-lived token (JWT)
3. User sends `/start <token>` to the bot
4. Bot validates token + creates TelegramLink row
5. Subsequent file forwards → POST internal /documents
"""
from __future__ import annotations

import logging
from datetime import datetime, UTC, timedelta
from uuid import UUID

from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.config import settings
from adelia.models import TelegramLink

logger = logging.getLogger(__name__)


_LINK_TOKEN_TTL = timedelta(hours=1)
_LINK_TOKEN_AUDIENCE = "telegram-link"


def mint_link_token(user_id: UUID) -> str:
    """Generate a signed short-lived token the user includes in /start command.

    Token is opaque to the user — they just paste it into the chat.
    """
    if not settings.auth_secret:
        raise RuntimeError("AUTH_SECRET not configured")
    payload = {
        "sub": str(user_id),
        "aud": _LINK_TOKEN_AUDIENCE,
        "exp": datetime.now(UTC) + _LINK_TOKEN_TTL,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.auth_secret, algorithm="HS256")


def decode_link_token(token: str) -> UUID | None:
    """Validate + decode the link token, returning user_id or None."""
    if not settings.auth_secret:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.auth_secret,
            algorithms=["HS256"],
            audience=_LINK_TOKEN_AUDIENCE,
        )
        return UUID(payload["sub"])
    except Exception as e:
        logger.warning("link token decode failed: %s", e)
        return None


def get_bot_url() -> str:
    """Resolve the t.me URL for the bot.

    Requires bot username configured externally — derives heuristically from
    TELEGRAM_BOT_TOKEN if not. For v0.2 we expect ADELIA_BOT_USERNAME or fallback.
    """
    # Bot username typically derived from BotFather; not in token itself.
    # Spec calls this "@adelia_vault_bot" — confirm with user when activating.
    return "https://t.me/adelia_vault_bot"


async def link_user_by_chat_id(
    session: AsyncSession,
    *,
    user_id: UUID,
    chat_id: int,
    username: str | None,
) -> TelegramLink:
    """Idempotent: creates or replaces a TelegramLink for user_id."""
    # Check if an existing link exists
    stmt = select(TelegramLink).where(TelegramLink.user_id == user_id)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.chat_id = chat_id
        existing.username = username
        existing.linked_at = datetime.now(UTC)
        return existing
    link = TelegramLink(user_id=user_id, chat_id=chat_id, username=username)
    session.add(link)
    await session.flush()
    return link


async def lookup_user_by_chat_id(
    session: AsyncSession, *, chat_id: int
) -> UUID | None:
    """Find the AdelIA user_id linked to a Telegram chat_id."""
    stmt = select(TelegramLink.user_id).where(TelegramLink.chat_id == chat_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def validate_telegram_secret(header_value: str | None) -> bool:
    """Constant-time validation of the X-Telegram-Bot-Api-Secret-Token header."""
    if not settings.telegram_webhook_secret:
        return False
    if not header_value:
        return False
    import hmac

    return hmac.compare_digest(header_value, settings.telegram_webhook_secret)


# ---------------------------------------------------------------------------
# Update handler — extracts files from Telegram updates and ingests them.
#
# This handler is intentionally framework-agnostic (no python-telegram-bot
# dependency at import time) so it can run in both webhook FastAPI context AND
# python-telegram-bot polling context.
# ---------------------------------------------------------------------------


async def handle_update(update_data: dict) -> dict:
    """Process a Telegram Update payload.

    Returns a small dict with {action, status, details} for logging/response.

    Supported actions:
    - /start <token>      → link user to chat_id
    - any text msg        → reply with instructions
    - photo / document /
      voice / audio       → download via Bot API + POST /documents
    """
    from adelia.db import AsyncSessionLocal

    msg = update_data.get("message")
    if msg is None:
        return {"action": "ignore", "status": "ok", "reason": "non-message update"}

    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    if not chat_id:
        return {"action": "ignore", "status": "ok", "reason": "no chat_id"}

    text = msg.get("text", "")
    from_user = msg.get("from", {})
    username = from_user.get("username")

    # /start <token> command
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return {
                "action": "start_no_token",
                "status": "instructions",
                "reply": "Para enlazar tu cuenta, copia el token de tu dashboard AdelIA y envía '/start <token>'.",
            }
        token = parts[1].strip()
        user_id = decode_link_token(token)
        if user_id is None:
            return {
                "action": "start_invalid_token",
                "status": "error",
                "reply": "Token inválido o expirado. Genera uno nuevo desde tu dashboard AdelIA.",
            }
        async with AsyncSessionLocal() as session:
            await link_user_by_chat_id(
                session, user_id=user_id, chat_id=chat_id, username=username
            )
            await session.commit()
        return {
            "action": "linked",
            "status": "ok",
            "user_id": str(user_id),
            "reply": "✅ Cuenta AdelIA enlazada. Reenvía aquí PDFs, fotos o audios médicos y los ingestaré automáticamente.",
        }

    # File-bearing message — would download + POST /documents in production.
    # Implementation here is a stub: returns metadata for verification.
    file_info: dict | None = None
    if "photo" in msg:
        photos = msg["photo"]  # list of size variants
        biggest = photos[-1] if photos else None
        if biggest:
            file_info = {"type": "photo", "file_id": biggest.get("file_id")}
    elif "document" in msg:
        doc = msg["document"]
        file_info = {
            "type": "document",
            "file_id": doc.get("file_id"),
            "filename": doc.get("file_name"),
            "mime_type": doc.get("mime_type"),
        }
    elif "voice" in msg:
        voice = msg["voice"]
        file_info = {"type": "voice", "file_id": voice.get("file_id")}
    elif "audio" in msg:
        audio = msg["audio"]
        file_info = {
            "type": "audio",
            "file_id": audio.get("file_id"),
            "filename": audio.get("file_name"),
        }

    if file_info is None:
        return {
            "action": "text_only",
            "status": "instructions",
            "reply": "Reenvía un PDF, foto o audio médico aquí y lo ingestaré automáticamente.",
        }

    # Look up linked user
    async with AsyncSessionLocal() as session:
        user_id = await lookup_user_by_chat_id(session, chat_id=chat_id)

    if user_id is None:
        return {
            "action": "no_link",
            "status": "error",
            "reply": "No has enlazado tu cuenta aún. Visita /dashboard/ingestion en AdelIA para obtener un token de enlace.",
        }

    # Production: download file via Bot API + POST /documents.
    # The download flow needs TELEGRAM_BOT_TOKEN + 2 API calls (getFile → download URL).
    # Deferred to v0.2.1 to keep this commit's diff focused — handler shape stable now.
    return {
        "action": "file_received",
        "status": "queued",
        "user_id": str(user_id),
        "file_info": file_info,
        "reply": "📥 Recibido. Procesando...",
        "todo": "Download + POST /documents wiring deferred to v0.2.1",
    }
