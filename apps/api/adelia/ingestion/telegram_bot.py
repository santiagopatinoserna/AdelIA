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
    return f"https://t.me/{settings.telegram_bot_username}"


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
    """Process a Telegram Update and REPLY through the Bot API.

    - /start <token>           → link user to chat_id
    - text (non-command)       → today's diary entry (text/plain document)
    - voice / audio            → today's diary entry (transcribed by the pipeline)
    - photo / document         → regular document ingestion
    The reply is sent with sendMessage (Telegram ignores webhook response
    bodies); the returned dict is for logging/tests only.
    """
    from adelia.db import AsyncSessionLocal
    from adelia.services import telegram_diary as diary

    msg = update_data.get("message")
    if msg is None:
        return {"action": "ignore", "status": "ok", "reason": "non-message update"}
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    if not chat_id:
        return {"action": "ignore", "status": "ok", "reason": "no chat_id"}
    text = (msg.get("text") or "").strip()
    from_user = msg.get("from", {})
    username = from_user.get("username")

    async def reply(action: str, status: str, body: str, **extra) -> dict:
        await diary.tg_send(int(chat_id), body)
        return {"action": action, "status": status, "reply": body, **extra}

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return await reply("start_no_token", "instructions",
                               "Para enlazar tu cuenta, copia el token de tu panel AdelIA "
                               "(Importar → Telegram) y envía: /start TOKEN")
        user_id = decode_link_token(parts[1].strip())
        if user_id is None:
            return await reply("start_invalid_token", "error",
                               "Token inválido o caducado. Genera uno nuevo desde tu panel AdelIA.")
        async with AsyncSessionLocal() as session:
            await link_user_by_chat_id(session, user_id=user_id, chat_id=chat_id, username=username)
            await session.commit()
        return await reply("linked", "ok",
                           "✅ Cuenta enlazada. Cada tarde te preguntaré cómo ha ido el día: "
                           "respóndeme en texto o con un audio y lo guardo en su diario. "
                           "También puedes reenviarme informes, fotos o PDFs.",
                           user_id=str(user_id))

    async with AsyncSessionLocal() as session:
        user_id = await lookup_user_by_chat_id(session, chat_id=chat_id)
    if user_id is None:
        return await reply("no_link", "error",
                           "Aún no has enlazado tu cuenta. En AdelIA: Importar → Telegram → copia el token "
                           "y envíame: /start TOKEN")

    if text and not text.startswith("/"):
        try:
            doc = await diary.diary_from_text(user_id=user_id, chat_id=int(chat_id), text=text)
        except Exception:  # noqa: BLE001
            logger.exception("diary_from_text failed chat_id=%s", chat_id)
            return await reply("diary_error", "error", "No he podido guardarlo. ¿Me lo repites?")
        return await reply("diary_text", "ok", "Anotado en el diario de hoy ✓", document_id=str(doc.id))

    file_id, kind, filename = None, None, None
    if "voice" in msg:
        file_id, kind = msg["voice"].get("file_id"), "voice"
    elif "audio" in msg:
        file_id, kind, filename = msg["audio"].get("file_id"), "audio", msg["audio"].get("file_name")
    elif "photo" in msg:
        photos = msg["photo"]
        file_id, kind = (photos[-1].get("file_id") if photos else None), "photo"
    elif "document" in msg:
        file_id, kind, filename = msg["document"].get("file_id"), "document", msg["document"].get("file_name")

    if not file_id:
        return await reply("unsupported", "instructions",
                           "Cuéntame el día en texto o con un audio, o reenvíame un informe, foto o PDF.")
    try:
        doc = await diary.diary_from_file(user_id=user_id, chat_id=int(chat_id), file_id=file_id,
                                          kind=kind, filename=filename)
    except Exception:  # noqa: BLE001
        logger.exception("diary_from_file failed chat_id=%s kind=%s", chat_id, kind)
        return await reply("file_error", "error", "No he podido descargar el archivo. ¿Me lo envías otra vez?")
    body = ("🎙 Recibido. Lo transcribo y te digo qué he entendido en un momento."
            if kind in ("voice", "audio") else "📥 Recibido. Lo proceso y lo añado al historial.")
    return await reply("file_received", "queued", body, document_id=str(doc.id), kind=kind)
