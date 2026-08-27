"""Telegram-first daily diary.

The parent tells the bot how the day went, in text or as a voice note; it
lands as a diary Document (source="manual", metadata.diary_date) and runs
through the normal pipeline (voice → Voxtral transcript → entities → RAG),
so the chat and the briefings can answer "how has feeding gone this week"
with citations to concrete days. Anything better seen on the web is sent
back as a link, never crammed into Telegram.
"""
from __future__ import annotations

import asyncio
import io
import logging
import mimetypes
import uuid
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import sqlalchemy as sa

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import Document, TelegramLink
from adelia.storage import S3Storage

logger = logging.getLogger(__name__)
storage = S3Storage()

BOT_API = "https://api.telegram.org"
_VOICE_MIME = "audio/ogg"  # Telegram voice notes are OGG/Opus


# --- Bot API ---------------------------------------------------------------

async def tg_send(chat_id: int, text: str) -> bool:
    """Send a message; never raises (a failed notification must not break
    ingestion). Returns True on success."""
    if not settings.telegram_bot_token:
        return False
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{BOT_API}/bot{settings.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        if resp.status_code != 200:
            logger.warning("telegram sendMessage %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except httpx.HTTPError:
        logger.exception("telegram sendMessage failed")
        return False


async def tg_download(file_id: str) -> tuple[bytes, str]:
    """getFile + download. Returns (bytes, mime). Raises httpx errors."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        meta = await client.get(
            f"{BOT_API}/bot{settings.telegram_bot_token}/getFile", params={"file_id": file_id}
        )
        meta.raise_for_status()
        file_path = meta.json()["result"]["file_path"]
        blob = await client.get(f"{BOT_API}/file/bot{settings.telegram_bot_token}/{file_path}")
        blob.raise_for_status()
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    mime = {"oga": _VOICE_MIME, "ogg": _VOICE_MIME, "opus": _VOICE_MIME}.get(ext) or (
        mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    )
    return blob.content, mime


# --- Diary semantics -----------------------------------------------------

def today_iso() -> str:
    return datetime.now(ZoneInfo(settings.diary_reminder_tz)).date().isoformat()


def long_date_es(iso: str) -> str:
    d = date.fromisoformat(iso)
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    return f"{d.day} de {meses[d.month - 1]} de {d.year}"


def render_diary_text(text: str, diary_date: str, profile_name: str | None) -> str:
    who = profile_name or "el bebé"
    return f"Diario de {who}, {long_date_es(diary_date)}.\n\n{text.strip()}"


def doc_link(document_id: uuid.UUID | str, locale: str = "es") -> str:
    return f"{settings.adelia_app_url.rstrip('/')}/{locale}/dashboard/documents/{document_id}"


async def _default_profile(session, user_id: uuid.UUID):
    """Best-effort default profile (name + id); None if the user has none."""
    try:
        from adelia.models import Profile
        row = (
            await session.execute(
                sa.select(Profile)
                .where(Profile.user_id == user_id, Profile.deleted_at.is_(None))
                .order_by(Profile.is_default.desc(), Profile.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return row
    except Exception:  # noqa: BLE001 — profile is a nicety here
        logger.exception("default profile lookup failed")
        return None


async def ingest_bytes(
    *,
    user_id: uuid.UUID,
    body: bytes,
    mime: str,
    filename: str,
    raw_text: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Document:
    """Store a blob + Document and schedule the pipeline (no request context,
    so asyncio.create_task instead of FastAPI BackgroundTasks)."""
    from adelia.routers.documents import process_document

    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)[:80]
    s3_key = f"users/{user_id}/{uuid.uuid4()}-{safe}"
    await storage.put_object(s3_key, io.BytesIO(body), content_type=mime)

    async with AsyncSessionLocal() as session:
        profile = await _default_profile(session, user_id)
        doc = Document(
            id=uuid.uuid4(),
            user_id=user_id,
            profile_id=profile.id if profile is not None else None,
            source="manual",
            mime_type=mime,
            s3_key=s3_key,
            raw_text=raw_text,
            document_metadata=metadata or {},
        )
        session.add(doc)
        try:
            await session.commit()
        except Exception:
            try:
                await storage.delete_object(s3_key)
            except Exception:  # noqa: BLE001
                logger.exception("orphan blob cleanup failed for %s", s3_key)
            raise
        await session.refresh(doc)
        doc_id, mime_type = doc.id, doc.mime_type
    asyncio.create_task(process_document(doc_id, mime_type, False))
    return doc


async def has_diary_for(session, user_id: uuid.UUID, diary_date: str) -> bool:
    n = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Document)
        .where(
            Document.user_id == user_id,
            Document.deleted_at.is_(None),
            Document.document_metadata["diary_date"].astext == diary_date,
        )
    )
    return bool(n)


async def diary_from_text(*, user_id: uuid.UUID, chat_id: int, text: str) -> Document:
    diary_date = today_iso()
    async with AsyncSessionLocal() as session:
        profile = await _default_profile(session, user_id)
    rendered = render_diary_text(text, diary_date, profile.display_name if profile else None)
    return await ingest_bytes(
        user_id=user_id,
        body=rendered.encode("utf-8"),
        mime="text/plain",
        filename=f"diario-{diary_date}.txt",
        raw_text=rendered,
        metadata={"diary_date": diary_date, "channel": "telegram", "telegram_chat_id": chat_id},
    )


async def diary_from_file(
    *, user_id: uuid.UUID, chat_id: int, file_id: str, kind: str, filename: str | None
) -> Document:
    body, mime = await tg_download(file_id)
    diary_date = today_iso()
    is_voice = kind in ("voice", "audio")
    meta: dict[str, Any] = {"channel": "telegram", "telegram_chat_id": chat_id}
    if is_voice:
        meta["diary_date"] = diary_date
    ext = mime.split("/")[-1].replace("jpeg", "jpg").replace("x-m4a", "m4a")
    name = filename or (f"diario-{diary_date}.{ext}" if is_voice else f"telegram-{diary_date}.{ext}")
    return await ingest_bytes(user_id=user_id, body=body, mime=mime, filename=name, metadata=meta)


# --- Notifications ---------------------------------------------------------

async def notify_processed(document_id: uuid.UUID) -> None:
    """After the pipeline finishes a Telegram-originated document, tell the
    parent what was understood and link to the web when it reads better."""
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return
        meta = doc.document_metadata or {}
        chat_id = meta.get("telegram_chat_id")
        if not chat_id:
            return
        raw = (doc.raw_text or "").strip()
        link = doc_link(doc.id)
        if not raw:
            text = ("No he podido leer eso. Prueba con un audio más claro o escríbemelo. "
                    f"Lo tienes aquí: {link}")
        elif doc.mime_type.startswith("audio/"):
            snippet = raw[:600] + ("…" if len(raw) > 600 else "")
            text = f"He entendido:\n<i>{_html(snippet)}</i>\n\nGuardado en el diario ✓\nVerlo completo: {link}"
        else:
            text = f"Anotado en el diario ✓  {link}"
        summary = meta.get("summary")
        if summary:
            text += f"\n\n<b>Lo esencial</b>\n{_html(summary)}"
    await tg_send(int(chat_id), text)


def _html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def send_daily_reminders() -> int:
    """Nudge every linked chat that has no diary entry for today."""
    diary_date = today_iso()
    sent = 0
    async with AsyncSessionLocal() as session:
        links = (await session.execute(sa.select(TelegramLink))).scalars().all()
        targets = [
            (link.chat_id, link.user_id)
            for link in links
            if not await has_diary_for(session, link.user_id, diary_date)
        ]
    for chat_id, _ in targets:
        ok = await tg_send(
            int(chat_id),
            "¿Cómo ha ido hoy? Cuéntamelo aquí, en texto o con un audio 🎙: "
            "guardería, comida, sueño, cómo estaba. Lo guardo en su diario.",
        )
        sent += int(ok)
    return sent
