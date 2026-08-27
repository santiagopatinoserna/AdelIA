"""Telegram-first daily diary: text → diary document, voice → audio document
transcribed by the pipeline, reminder only for chats without today's entry.
Bot API and S3 are mocked; the DB is the real dev Postgres."""
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from adelia.db import AsyncSessionLocal
from adelia.ingestion import telegram_bot
from adelia.models import Document, Profile, TelegramLink, User
from adelia.services import telegram_diary as diary

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fake_bot(monkeypatch):
    """Capture outgoing messages; neutralise S3 and the pipeline."""
    sent: list[tuple[int, str]] = []

    async def _send(chat_id, text):
        sent.append((chat_id, text))
        return True

    async def _put(key, body, content_type=None):
        return None

    async def _noop_process(document_id, mime_type, is_consulta=False):
        return None

    monkeypatch.setattr(diary, "tg_send", _send)
    monkeypatch.setattr(diary.storage, "put_object", _put)
    monkeypatch.setattr("adelia.routers.documents.process_document", _noop_process)
    monkeypatch.setattr(diary.settings, "telegram_bot_token", "test-token")
    return sent


async def _make_linked_user(chat_id: int) -> uuid.UUID:
    async with AsyncSessionLocal() as session:
        user = User(id=uuid.uuid4(), email=f"tg-{uuid.uuid4().hex[:8]}@adelia.test")
        session.add(user)
        await session.flush()
        session.add(Profile(user_id=user.id, display_name="Adel", relationship="child", is_default=True))
        session.add(TelegramLink(user_id=user.id, chat_id=chat_id, username="santi"))
        await session.commit()
        return user.id


async def _docs_for(user_id: uuid.UUID) -> list[Document]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(sa.select(Document).where(Document.user_id == user_id))).scalars().all()
        return list(rows)


async def test_text_message_becomes_diary_entry(fake_bot):
    chat_id = int(uuid.uuid4().int % 10**9)
    user_id = await _make_linked_user(chat_id)

    out = await telegram_bot.handle_update(
        {"message": {"chat": {"id": chat_id}, "from": {"username": "santi"}, "text": "Hoy ha comido medio plátano y ha dormido 2 horas"}}
    )

    assert out["action"] == "diary_text"
    docs = await _docs_for(user_id)
    assert len(docs) == 1
    d = docs[0]
    assert d.mime_type == "text/plain"
    assert d.source == "manual"
    assert d.document_metadata["diary_date"] == diary.today_iso()
    assert d.document_metadata["telegram_chat_id"] == chat_id
    assert "Diario de Adel" in d.raw_text
    assert "medio plátano" in d.raw_text
    assert d.profile_id is not None
    assert fake_bot and "Anotado" in fake_bot[-1][1]


async def test_voice_note_is_downloaded_and_queued(fake_bot, monkeypatch):
    chat_id = int(uuid.uuid4().int % 10**9)
    user_id = await _make_linked_user(chat_id)

    async def _download(file_id):
        assert file_id == "voice-123"
        return b"OggS-fake", "audio/ogg"

    monkeypatch.setattr(diary, "tg_download", _download)

    out = await telegram_bot.handle_update(
        {"message": {"chat": {"id": chat_id}, "voice": {"file_id": "voice-123", "duration": 12}}}
    )

    assert out["action"] == "file_received" and out["kind"] == "voice"
    docs = await _docs_for(user_id)
    assert len(docs) == 1
    assert docs[0].mime_type == "audio/ogg"
    assert docs[0].raw_text is None  # transcription is the pipeline's job
    assert docs[0].document_metadata["diary_date"] == diary.today_iso()
    assert "transcribo" in fake_bot[-1][1]


async def test_photo_is_ingested_without_diary_date(fake_bot, monkeypatch):
    chat_id = int(uuid.uuid4().int % 10**9)
    user_id = await _make_linked_user(chat_id)

    async def _download(file_id):
        return b"\x89PNG", "image/png"

    monkeypatch.setattr(diary, "tg_download", _download)
    out = await telegram_bot.handle_update(
        {"message": {"chat": {"id": chat_id}, "photo": [{"file_id": "small"}, {"file_id": "big"}]}}
    )
    assert out["kind"] == "photo"
    docs = await _docs_for(user_id)
    assert docs[0].mime_type == "image/png"
    assert "diary_date" not in docs[0].document_metadata


async def test_unlinked_chat_gets_instructions(fake_bot):
    chat_id = int(uuid.uuid4().int % 10**9)
    out = await telegram_bot.handle_update({"message": {"chat": {"id": chat_id}, "text": "hola"}})
    assert out["action"] == "no_link"
    assert "/start" in fake_bot[-1][1]


async def test_reminder_skips_chats_with_todays_entry(fake_bot):
    chat_done = int(uuid.uuid4().int % 10**9)
    chat_pending = int(uuid.uuid4().int % 10**9)
    await _make_linked_user(chat_done)
    await _make_linked_user(chat_pending)
    await telegram_bot.handle_update({"message": {"chat": {"id": chat_done}, "text": "día tranquilo"}})
    fake_bot.clear()

    sent = await diary.send_daily_reminders()

    reminded = {c for c, _ in fake_bot}
    assert chat_pending in reminded
    assert chat_done not in reminded
    assert sent >= 1 and "¿Cómo ha ido hoy?" in fake_bot[-1][1]


def test_bot_url_uses_configured_username(monkeypatch):
    monkeypatch.setattr(telegram_bot.settings, "telegram_bot_username", "Adelia_godiai_bot")
    assert telegram_bot.get_bot_url() == "https://t.me/Adelia_godiai_bot"


def test_notify_text_escapes_html():
    assert diary._html("a<b>&c") == "a&lt;b&gt;&amp;c"
