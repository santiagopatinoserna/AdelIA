"""Telegram bot — receives forwarded files/photos/audios and ingests them
as Documents for the linked user.

Two modes:
- Webhook: production. Telegram POSTs to /ingestion/telegram/webhook;
  validates X-Telegram-Bot-Api-Secret-Token header.
- Polling: local dev. Bot polls Telegram API in a background task.

Activation requires TELEGRAM_BOT_TOKEN (from @BotFather) + TELEGRAM_WEBHOOK_SECRET.

Link flow:
1. User visits /dashboard/ingestion/telegram-link in web UI
2. Backend mints a signed short-lived token (JWT, carries the UI locale)
3. User sends `/start <token>` to the bot (private chat only)
4. Bot validates token + creates TelegramLink row; the token is single-use
   (a token minted before the current link can never re-link)
5. Subsequent messages → diary entries / document ingestion
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, UTC, timedelta
from uuid import UUID

from jose import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.config import settings
from adelia.models import TelegramLink

logger = logging.getLogger(__name__)


_LINK_TOKEN_TTL = timedelta(hours=1)
_LINK_TOKEN_AUDIENCE = "telegram-link"


@dataclass(frozen=True)
class LinkClaims:
    user_id: UUID
    locale: str
    issued_at: datetime  # aware UTC, second resolution (JWT iat)


def mint_link_token(user_id: UUID, locale: str = "es") -> str:
    """Generate a signed short-lived token the user includes in /start command.

    Token is opaque to the user — they just paste it into the chat. `loc`
    carries the UI locale so the bot answers in the same language.
    """
    if not settings.auth_secret:
        raise RuntimeError("AUTH_SECRET not configured")
    from adelia.services.telegram_diary import normalize_locale

    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "aud": _LINK_TOKEN_AUDIENCE,
        "exp": now + _LINK_TOKEN_TTL,
        "iat": now,
        # Sub-second issue time: JWT iat is floored to the second, so a token
        # minted right after a /start in the same second would look older
        # than the link and be refused as a replay.
        "mts": now.timestamp(),
        "loc": normalize_locale(locale),
    }
    return jwt.encode(payload, settings.auth_secret, algorithm="HS256")


def decode_link_claims(token: str) -> LinkClaims | None:
    """Validate + decode the link token; None if invalid/expired."""
    if not settings.auth_secret:
        return None
    from adelia.services.telegram_diary import normalize_locale

    try:
        payload = jwt.decode(
            token,
            settings.auth_secret,
            algorithms=["HS256"],
            audience=_LINK_TOKEN_AUDIENCE,
        )
        return LinkClaims(
            user_id=UUID(payload["sub"]),
            locale=normalize_locale(payload.get("loc")),
            issued_at=datetime.fromtimestamp(float(payload.get("mts", payload["iat"])), UTC),
        )
    except Exception as e:
        logger.warning("link token decode failed: %s", e)
        return None


def decode_link_token(token: str) -> UUID | None:
    """Validate + decode the link token, returning user_id or None."""
    claims = decode_link_claims(token)
    return claims.user_id if claims else None


def get_bot_url() -> str:
    """Resolve the t.me URL for the bot.

    Requires bot username configured externally — derives heuristically from
    TELEGRAM_BOT_TOKEN if not. For v0.2 we expect ADELIA_BOT_USERNAME or fallback.
    """
    return f"https://t.me/{settings.telegram_bot_username}"


class ChatAlreadyLinked(Exception):
    """The Telegram chat is linked to a different AdelIA account."""


class LinkTokenUsed(Exception):
    """The token predates the account's current link: replay, refused."""


async def link_user_by_chat_id(
    session: AsyncSession,
    *,
    user_id: UUID,
    chat_id: int,
    username: str | None,
    locale: str = "es",
    token_issued_at: datetime | None = None,
) -> tuple[TelegramLink, int | None]:
    """Idempotent: creates or replaces a TelegramLink for user_id.

    Returns (link, previous_chat_id): previous_chat_id is set when the
    account was linked to ANOTHER chat before, so the caller can warn it.

    Raises ChatAlreadyLinked if chat_id belongs to another account (the
    column is UNIQUE; without this check the commit dies with an
    IntegrityError and the parent gets no reply), and LinkTokenUsed if the
    token was minted before the current link (single-use tokens).
    """
    taken = (
        await session.execute(
            select(TelegramLink).where(
                TelegramLink.chat_id == chat_id, TelegramLink.user_id != user_id
            )
        )
    ).scalar_one_or_none()
    if taken is not None:
        raise ChatAlreadyLinked(str(chat_id))

    stmt = select(TelegramLink).where(TelegramLink.user_id == user_id)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        if (
            token_issued_at is not None
            and existing.linked_at is not None
            and existing.linked_at >= token_issued_at
        ):
            raise LinkTokenUsed()
        previous_chat = existing.chat_id if existing.chat_id != chat_id else None
        existing.chat_id = chat_id
        existing.username = username
        existing.locale = locale
        existing.linked_at = datetime.now(UTC)
        return existing, previous_chat
    link = TelegramLink(user_id=user_id, chat_id=chat_id, username=username, locale=locale)
    session.add(link)
    await session.flush()
    return link, None


async def lookup_link_by_chat_id(session: AsyncSession, *, chat_id: int) -> TelegramLink | None:
    stmt = select(TelegramLink).where(TelegramLink.chat_id == chat_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def lookup_user_by_chat_id(
    session: AsyncSession, *, chat_id: int
) -> UUID | None:
    """Find the AdelIA user_id linked to a Telegram chat_id."""
    link = await lookup_link_by_chat_id(session, chat_id=chat_id)
    return link.user_id if link is not None else None


def validate_telegram_secret(header_value: str | None) -> bool:
    """Constant-time validation of the X-Telegram-Bot-Api-Secret-Token header."""
    if not settings.telegram_webhook_secret:
        return False
    if not header_value:
        return False
    import hmac

    # Compare bytes: compare_digest raises TypeError on non-ASCII str, which
    # would turn a bad header into a 500 instead of a 401.
    return hmac.compare_digest(
        header_value.encode("utf-8"), settings.telegram_webhook_secret.encode("utf-8")
    )


# ---------------------------------------------------------------------------
# Diary text guard: "ok" / "👍" / "hola" answering the reminder is not a
# diary entry. No generic minimum length (a legit "Día tranquilo" is short).
# ---------------------------------------------------------------------------

_ACKS = {
    "hola", "hey", "buenas", "ok", "okay", "okey", "vale", "gracias", "genial", "perfecto",
    "si", "no", "luego", "ahora no", "hello", "hi", "thanks", "thank you", "yes", "later",
    "bonjour", "salut", "merci", "oui", "non", "d accord", "daccord", "plus tard",
}


def is_ack(text: str) -> bool:
    if not any(ch.isalnum() for ch in text):
        return True
    folded = "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn"
    )
    norm = re.sub(r"[^\w\s]+", " ", folded)
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm in _ACKS


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
    Only private chats are served: a family group must never become the
    linked chat (other members' messages would land in the health record).
    The reply is sent with sendMessage (Telegram ignores webhook response
    bodies); the returned dict is for logging/tests only.
    """
    from adelia.db import AsyncSessionLocal
    from adelia.services import telegram_diary as diary
    from adelia.services.telegram_diary import normalize_locale, t

    msg = update_data.get("message")
    if msg is None:
        return {"action": "ignore", "status": "ok", "reason": "non-message update"}
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    if not chat_id:
        return {"action": "ignore", "status": "ok", "reason": "no chat_id"}
    text = (msg.get("text") or "").strip()
    caption = (msg.get("caption") or "").strip()
    from_user = msg.get("from", {})
    username = from_user.get("username")
    locale = normalize_locale(from_user.get("language_code"))

    async def reply(action: str, status: str, body: str, **extra) -> dict:
        await diary.tg_send(int(chat_id), body)
        return {"action": action, "status": status, "reply": body, **extra}

    if (chat.get("type") or "private") != "private":
        if text.startswith("/start"):
            await diary.tg_send(int(chat_id), t(locale, "start_private_only", bot_url=get_bot_url()))
        return {"action": "ignore", "status": "ok", "reason": "non-private chat"}

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return await reply("start_no_token", "instructions", t(locale, "start_no_token"))
        claims = decode_link_claims(parts[1].strip())
        if claims is None:
            return await reply("start_invalid_token", "error", t(locale, "start_invalid_token"))
        locale = claims.locale
        previous_chat: int | None = None
        try:
            async with AsyncSessionLocal() as session:
                _, previous_chat = await link_user_by_chat_id(
                    session, user_id=claims.user_id, chat_id=chat_id, username=username,
                    locale=locale, token_issued_at=claims.issued_at,
                )
                await session.commit()
        except LinkTokenUsed:
            return await reply("start_token_used", "error", t(locale, "start_token_used"))
        except (ChatAlreadyLinked, IntegrityError):
            logger.warning("telegram /start refused: chat already linked to another account")
            return await reply("start_chat_taken", "error", t(locale, "start_chat_taken"))
        if previous_chat is not None:
            await diary.tg_send(int(previous_chat), t(locale, "relinked_notice"))
        return await reply("linked", "ok", t(locale, "linked"), user_id=str(claims.user_id),
                           previous_chat_id=previous_chat)

    async with AsyncSessionLocal() as session:
        link = await lookup_link_by_chat_id(session, chat_id=chat_id)
        if link is None:
            user_id = None
        else:
            user_id = link.user_id
            locale = normalize_locale(link.locale)
    if user_id is None:
        return await reply("no_link", "error", t(locale, "no_link"))

    if text and not text.startswith("/"):
        if is_ack(text):
            return await reply("diary_ack", "instructions", t(locale, "diary_ack"))
        try:
            res = await diary.diary_from_text(user_id=user_id, chat_id=int(chat_id), text=text,
                                              locale=locale)
        except Exception:  # noqa: BLE001
            logger.exception("diary_from_text failed user_id=%s", user_id)
            return await reply("diary_error", "error", t(locale, "diary_error"))
        when = diary.long_date(diary.today_iso(), locale)
        link_url = diary.doc_link(res.document.id, locale)
        if res.profile is not None:
            # Names are user text inside a parse_mode=HTML message: escape them
            # or "Nora <3" makes Telegram reject the only confirmation.
            body = t(locale, "diary_saved", name=diary._html(res.profile.display_name),
                     date=when, link=link_url)
            if res.other_profiles:
                body += "\n" + t(locale, "diary_other_profile_hint",
                                  example=diary._html(res.other_profiles[0]))
        else:
            body = t(locale, "diary_saved_no_profile", date=when, link=link_url)
        return await reply("diary_text", "ok", body, document_id=str(res.document.id),
                           profile_id=str(res.profile.id) if res.profile else None)

    file_id, kind, filename, mime_hint = None, None, None, None
    if "voice" in msg:
        file_id, kind, mime_hint = msg["voice"].get("file_id"), "voice", msg["voice"].get("mime_type")
    elif "audio" in msg:
        file_id, kind = msg["audio"].get("file_id"), "audio"
        filename, mime_hint = msg["audio"].get("file_name"), msg["audio"].get("mime_type")
    elif "photo" in msg:
        photos = msg["photo"]
        file_id, kind = (photos[-1].get("file_id") if photos else None), "photo"
    elif "document" in msg:
        file_id, kind = msg["document"].get("file_id"), "document"
        filename, mime_hint = msg["document"].get("file_name"), msg["document"].get("mime_type")

    if not file_id:
        return await reply("unsupported", "instructions", t(locale, "unsupported"))
    try:
        res = await diary.diary_from_file(
            user_id=user_id, chat_id=int(chat_id), file_id=file_id, kind=kind, filename=filename,
            mime_hint=mime_hint, caption=caption or None, locale=locale,
        )
    except diary.UnsupportedFileType:
        return await reply("unsupported_file", "instructions", t(locale, "unsupported_file"), kind=kind)
    except diary.FileTooLarge:
        return await reply("file_too_large", "instructions", t(locale, "file_too_large"), kind=kind)
    except Exception:  # noqa: BLE001 — never logs the chat_id nor the token
        logger.exception("diary_from_file failed user_id=%s kind=%s", user_id, kind)
        return await reply("file_error", "error", t(locale, "file_error"))
    body = t(locale, "voice_received") if kind in ("voice", "audio") else t(locale, "file_received")
    return await reply("file_received", "queued", body, document_id=str(res.document.id), kind=kind,
                       profile_id=str(res.profile.id) if res.profile else None)
