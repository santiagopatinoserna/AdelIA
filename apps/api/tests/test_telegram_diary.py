"""Telegram-first daily diary: text → diary document, voice → audio document
transcribed by the pipeline, reminder only for chats without today's entry.
Bot API and S3 are mocked; the DB is the real dev Postgres. Every row a
test creates is deleted again in the `linked_user` teardown (a leftover
telegram_links row makes every reminder run call Telegram for a dead chat).
"""
from __future__ import annotations

import io
import json
import logging
import mimetypes
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
import sqlalchemy as sa

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.ingestion import telegram_bot
from adelia.main import seconds_until_next_reminder
from adelia.models import Chunk, Document, Profile, TelegramLink, User
from adelia.routers import documents as docs_mod
from adelia.services import telegram_diary as diary

TOKEN = "123456:ABC-secret-bot-token"


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
    monkeypatch.setattr(diary.settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(settings, "auth_secret", "test-secret-32bytes-min")
    return sent


@pytest.fixture
async def linked_user():
    """Factory: user + child profile "Adel" + telegram link. Teardown deletes
    the users (profiles/links cascade) after their documents (no cascade)."""
    ids: list[uuid.UUID] = []

    async def _make(chat_id: int | None, *, locale: str = "es", profiles=(("Adel", "child", True),),
                    linked_at: datetime | None = None) -> uuid.UUID:
        async with AsyncSessionLocal() as session:
            user = User(id=uuid.uuid4(), email=f"tg-{uuid.uuid4().hex[:8]}@adelia.test")
            session.add(user)
            await session.flush()
            for name, rel, is_default in profiles:
                session.add(Profile(user_id=user.id, display_name=name, relationship=rel,
                                    is_default=is_default))
                await session.flush()
            if chat_id is not None:
                # linked_at in the past: a token minted NOW must be newer than the link.
                session.add(TelegramLink(user_id=user.id, chat_id=chat_id, username="santi",
                                         locale=locale,
                                         linked_at=linked_at or datetime.now(UTC) - timedelta(hours=1)))
            await session.commit()
            ids.append(user.id)
            return user.id

    yield _make
    async with AsyncSessionLocal() as session:
        await session.execute(sa.delete(Document).where(Document.user_id.in_(ids)))
        await session.execute(sa.delete(User).where(User.id.in_(ids)))
        await session.commit()


def _chat() -> int:
    return int(uuid.uuid4().int % 10**9)


def _msg(chat_id: int, chat_type: str = "private", **fields) -> dict:
    return {"update_id": 1, "message": {"message_id": 1, "date": 0,
                                        "chat": {"id": chat_id, "type": chat_type},
                                        "from": {"id": chat_id, "username": "santi"}, **fields}}


async def _docs_for(user_id: uuid.UUID) -> list[Document]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(sa.select(Document).where(Document.user_id == user_id))).scalars().all()
        return list(rows)


async def _link_for(user_id: uuid.UUID) -> TelegramLink | None:
    async with AsyncSessionLocal() as session:
        return (await session.execute(
            sa.select(TelegramLink).where(TelegramLink.user_id == user_id))).scalar_one_or_none()


def _mock_client(handler):
    """tg_download builds its own httpx.AsyncClient: swap it for a MockTransport one.
    (diary.httpx IS the httpx module, so keep a reference to the real class.)"""
    real_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        kwargs.pop("transport", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)
    return _factory


def _stub_pipeline(monkeypatch, *, body: bytes = b"", transcript: str = "", ocr: str = "",
                   extract=None):
    """Run the real _process_document_inner with S3 + Mistral stages stubbed."""
    monkeypatch.setattr(docs_mod, "RETRY_DELAYS", ())

    async def _get(key):
        return io.BytesIO(body)

    async def _transcribe(b, mime, diarize=False):
        return transcript

    async def _ocr(b, mime):
        return ocr

    async def _embed(texts):
        return [[0.0] * 1024 for _ in texts]

    async def _extract(text, *, diary_date=None):
        return []

    monkeypatch.setattr(docs_mod.storage, "get_object", _get)
    monkeypatch.setattr(docs_mod, "transcribe_audio", _transcribe)
    monkeypatch.setattr(docs_mod, "extract_text_from_pdf", _ocr)
    monkeypatch.setattr(docs_mod, "embed_texts", _embed)
    monkeypatch.setattr(docs_mod, "extract_entities", extract or _extract)


# --- Baseline behaviour -----------------------------------------------------

async def test_text_message_becomes_diary_entry(fake_bot, linked_user):
    chat_id = _chat()
    user_id = await linked_user(chat_id)

    out = await telegram_bot.handle_update(
        _msg(chat_id, text="Hoy ha comido medio plátano y ha dormido 2 horas"))

    assert out["action"] == "diary_text"
    docs = await _docs_for(user_id)
    assert len(docs) == 1
    d = docs[0]
    assert d.mime_type == "text/plain"
    assert d.source == "manual"
    assert d.document_metadata["diary_date"] == diary.today_iso()
    assert d.document_metadata["telegram_chat_id"] == chat_id
    assert d.document_metadata["locale"] == "es"
    assert "Diario de Adel" in d.raw_text
    assert "medio plátano" in d.raw_text
    assert d.profile_id is not None
    # The synchronous reply already names the child and links the entry.
    assert fake_bot and "Anotado" in fake_bot[-1][1] and "Adel" in fake_bot[-1][1]
    assert f"/es/dashboard/documents/{d.id}" in fake_bot[-1][1]


async def test_voice_note_is_downloaded_and_queued(fake_bot, linked_user, monkeypatch):
    chat_id = _chat()
    user_id = await linked_user(chat_id)

    async def _download(file_id, mime_hint=None):
        assert file_id == "voice-123"
        assert mime_hint == "audio/ogg"
        return b"OggS-fake", "audio/ogg"

    monkeypatch.setattr(diary, "tg_download", _download)

    out = await telegram_bot.handle_update(
        _msg(chat_id, voice={"file_id": "voice-123", "duration": 12, "mime_type": "audio/ogg"}))

    assert out["action"] == "file_received" and out["kind"] == "voice"
    docs = await _docs_for(user_id)
    assert len(docs) == 1
    assert docs[0].mime_type == "audio/ogg"
    assert docs[0].raw_text is None  # transcription is the pipeline's job
    assert docs[0].document_metadata["diary_date"] == diary.today_iso()
    assert "transcribo" in fake_bot[-1][1]


async def test_photo_is_ingested_without_diary_date_and_keeps_caption(fake_bot, linked_user, monkeypatch):
    chat_id = _chat()
    user_id = await linked_user(chat_id)

    async def _download(file_id, mime_hint=None):
        return b"\x89PNG", "image/png"

    monkeypatch.setattr(diary, "tg_download", _download)
    out = await telegram_bot.handle_update(
        _msg(chat_id, photo=[{"file_id": "small"}, {"file_id": "big"}], caption="Analítica 12/08, Dra. X"))
    assert out["kind"] == "photo"
    docs = await _docs_for(user_id)
    assert docs[0].mime_type == "image/png"
    assert "diary_date" not in docs[0].document_metadata
    assert docs[0].document_metadata["caption"] == "Analítica 12/08, Dra. X"
    assert "historial" in fake_bot[-1][1]


async def test_unlinked_chat_gets_instructions(fake_bot):
    out = await telegram_bot.handle_update(_msg(_chat(), text="hola"))
    assert out["action"] == "no_link"
    assert "/start" in fake_bot[-1][1]


async def test_reminder_skips_chats_with_todays_entry(fake_bot, linked_user):
    chat_done, chat_pending = _chat(), _chat()
    await linked_user(chat_done)
    await linked_user(chat_pending)
    await telegram_bot.handle_update(_msg(chat_done, text="día tranquilo"))
    fake_bot.clear()

    sent = await diary.send_daily_reminders()

    reminded = {c for c, _ in fake_bot}
    assert chat_pending in reminded
    assert chat_done not in reminded
    assert sent >= 1
    assert any(c == chat_pending and "¿Cómo ha ido hoy?" in m for c, m in fake_bot)


def test_bot_url_uses_configured_username(monkeypatch):
    monkeypatch.setattr(telegram_bot.settings, "telegram_bot_username", "Adelia_godiai_bot")
    assert telegram_bot.get_bot_url() == "https://t.me/Adelia_godiai_bot"


def test_notify_text_escapes_html():
    assert diary._html("a<b>&c") == "a&lt;b&gt;&amp;c"


# --- Bot token never reaches the log (findings 3/8) ---------------------------

async def test_getfile_failure_never_logs_token(fake_bot, linked_user, monkeypatch, caplog):
    chat_id = _chat()
    await linked_user(chat_id)

    def handler(request: httpx.Request) -> httpx.Response:
        assert TOKEN in str(request.url)
        return httpx.Response(400, json={"ok": False, "error_code": 400,
                                         "description": "Bad Request: file is too big"})

    monkeypatch.setattr(diary.httpx, "AsyncClient", _mock_client(handler))
    with caplog.at_level(logging.DEBUG):
        out = await telegram_bot.handle_update(_msg(chat_id, voice={"file_id": "stale", "duration": 1}))

    assert out["action"] == "file_error"
    rendered = caplog.text + "".join(str(r.exc_info) for r in caplog.records)
    assert TOKEN not in rendered
    assert "file is too big" in caplog.text
    assert "Bad Request" not in fake_bot[-1][1]
    # httpx logs every request URL at INFO: the redaction filter masks the token there too.
    httpx_lines = [r.getMessage() for r in caplog.records if r.name == "httpx"]
    assert httpx_lines and all("/bot<redacted>/getFile" in line for line in httpx_lines)


def test_log_redaction_masks_token_in_tracebacks(caplog):
    log = logging.getLogger("adelia.test_redaction")
    with caplog.at_level(logging.INFO):
        try:
            raise ValueError(f"boom https://api.telegram.org/bot{TOKEN}/getFile?file_id=x")
        except ValueError:
            log.exception("failed %s", f"{diary.BOT_API}/bot{TOKEN}/sendMessage")
    assert TOKEN not in caplog.text
    assert "/bot<redacted>/sendMessage" in caplog.text and "/bot<redacted>/getFile" in caplog.text


async def test_download_transport_error_is_sanitised(monkeypatch):
    monkeypatch.setattr(diary.settings, "telegram_bot_token", TOKEN)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    monkeypatch.setattr(diary.httpx, "AsyncClient", _mock_client(handler))
    with pytest.raises(diary.TelegramApiError) as exc:
        await diary.tg_download("f1")
    assert TOKEN not in str(exc.value)
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


# --- m4a / mime hints (finding 19) ---------------------------------------------

async def test_m4a_is_audio_even_without_system_mime_types(monkeypatch):
    monkeypatch.setattr(diary.settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(mimetypes, "guess_type", lambda *a, **k: (None, None))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getFile"):
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "music/file_1.m4a"}})
        return httpx.Response(200, content=b"m4a-bytes")

    monkeypatch.setattr(diary.httpx, "AsyncClient", _mock_client(handler))
    body, mime = await diary.tg_download("f1")
    assert body == b"m4a-bytes" and mime == "audio/mp4"
    _, hinted = await diary.tg_download("f1", mime_hint="audio/x-m4a")
    assert hinted == "audio/x-m4a"
    _, octet = await diary.tg_download("f1", mime_hint="application/octet-stream")
    assert octet == "audio/mp4"


async def test_audio_message_passes_telegram_mime_hint(fake_bot, linked_user, monkeypatch):
    chat_id = _chat()
    user_id = await linked_user(chat_id)
    seen = {}

    async def _download(file_id, mime_hint=None):
        seen["hint"] = mime_hint
        return b"m4a", "audio/x-m4a"

    monkeypatch.setattr(diary, "tg_download", _download)
    out = await telegram_bot.handle_update(
        _msg(chat_id, audio={"file_id": "a1", "file_name": "memo.m4a", "mime_type": "audio/x-m4a"}))
    assert out["action"] == "file_received"
    assert seen["hint"] == "audio/x-m4a"
    docs = await _docs_for(user_id)
    assert docs[0].mime_type == "audio/x-m4a" and docs[0].document_metadata["diary_date"]


async def test_unsupported_attachment_is_refused_not_stored(fake_bot, linked_user, monkeypatch):
    chat_id = _chat()
    user_id = await linked_user(chat_id)

    async def _download(file_id, mime_hint=None):
        return b"PK", "application/octet-stream"

    monkeypatch.setattr(diary, "tg_download", _download)
    out = await telegram_bot.handle_update(
        _msg(chat_id, document={"file_id": "d1", "file_name": "informe.docx"}))
    assert out["action"] == "unsupported_file"
    assert await _docs_for(user_id) == []
    assert "PDF" in fake_bot[-1][1]


# --- /start conflicts, replay, re-link notice (findings 9/10/18/26) ------------

async def test_start_from_chat_linked_to_other_account_is_refused(fake_bot, linked_user):
    chat_x = _chat()
    user_a = await linked_user(chat_x)
    user_b = await linked_user(None)
    fake_bot.clear()

    out = await telegram_bot.handle_update(_msg(chat_x, text=f"/start {telegram_bot.mint_link_token(user_b)}"))

    assert out["action"] == "start_chat_taken"
    assert len(fake_bot) == 1 and "otra cuenta" in fake_bot[0][1]
    link = await _link_for(user_a)
    assert link is not None and link.chat_id == chat_x
    assert await _link_for(user_b) is None


async def test_link_token_is_single_use(fake_bot, linked_user):
    user_id = await linked_user(None)
    token = telegram_bot.mint_link_token(user_id)
    chat_1, chat_2 = _chat(), _chat()

    first = await telegram_bot.handle_update(_msg(chat_1, text=f"/start {token}"))
    assert first["action"] == "linked"
    replay = await telegram_bot.handle_update(_msg(chat_2, text=f"/start {token}"))

    assert replay["action"] == "start_token_used"
    link = await _link_for(user_id)
    assert link.chat_id == chat_1
    assert all(c != chat_1 or "otro chat" not in m for c, m in fake_bot)


async def test_relink_from_new_chat_notifies_previous_chat(fake_bot, linked_user):
    chat_1, chat_2 = _chat(), _chat()
    user_id = await linked_user(chat_1)
    fake_bot.clear()

    out = await telegram_bot.handle_update(
        _msg(chat_2, text=f"/start {telegram_bot.mint_link_token(user_id)}"))

    assert out["action"] == "linked" and out["previous_chat_id"] == chat_1
    link = await _link_for(user_id)
    assert link.chat_id == chat_2
    notices = [m for c, m in fake_bot if c == chat_1]
    assert len(notices) == 1 and "otro chat" in notices[0]


async def test_start_stores_token_locale_and_replies_in_it(fake_bot, linked_user):
    user_id = await linked_user(None)
    chat_id = _chat()
    out = await telegram_bot.handle_update(
        _msg(chat_id, text=f"/start {telegram_bot.mint_link_token(user_id, 'fr')}"))
    assert out["action"] == "linked"
    assert "Compte lié" in fake_bot[-1][1]
    assert (await _link_for(user_id)).locale == "fr"


# --- Group chats (finding 11) -------------------------------------------------

async def test_group_chats_are_ignored(fake_bot, linked_user):
    user_id = await linked_user(None)
    group = -100_000_000_000 - _chat()
    out = await telegram_bot.handle_update(
        _msg(group, "supergroup", text=f"/start {telegram_bot.mint_link_token(user_id)}"))
    assert out["action"] == "ignore" and out["reason"] == "non-private chat"
    assert await _link_for(user_id) is None
    assert len(fake_bot) == 1 and "privado" in fake_bot[0][1]

    chat_id = _chat()
    linked = await linked_user(chat_id)
    fake_bot.clear()
    out = await telegram_bot.handle_update(_msg(chat_id, "group", text="ha comido bien y ha dormido"))
    assert out["action"] == "ignore"
    assert await _docs_for(linked) == [] and fake_bot == []


# --- Failed entries do not count as today's diary (findings 12/17) ------------

async def test_failed_voice_entry_does_not_silence_reminder(fake_bot, linked_user):
    chat_id = _chat()
    user_id = await linked_user(chat_id)
    today = diary.today_iso()
    async with AsyncSessionLocal() as session:
        failed = Document(id=uuid.uuid4(), user_id=user_id, source="manual", mime_type="audio/ogg",
                          s3_key=f"users/{user_id}/x.ogg", raw_text=None,
                          processed_at=datetime.now(UTC),
                          document_metadata={"diary_date": today, "telegram_chat_id": chat_id})
        session.add(failed)
        await session.commit()
        assert await diary.has_diary_for(session, user_id, today) is False
        failed.processed_at = None  # still transcribing: counts
        await session.commit()
        assert await diary.has_diary_for(session, user_id, today) is True
        failed.processed_at = datetime.now(UTC)
        await session.commit()

    await diary.send_daily_reminders()
    assert chat_id in {c for c, _ in fake_bot}

    from adelia.agent.suggestions import _gather_state
    state = await _gather_state(user_id=user_id, profile_id=None)
    assert state.diary_today is False and state.telegram_linked is True


async def test_has_diary_for_is_per_profile(linked_user):
    user_id = await linked_user(None, profiles=(("Adel", "child", True), ("Nora", "child", False)))
    async with AsyncSessionLocal() as session:
        adel, nora = (await session.execute(
            sa.select(Profile).where(Profile.user_id == user_id).order_by(Profile.display_name)
        )).scalars().all()
        today = diary.today_iso()
        session.add(Document(id=uuid.uuid4(), user_id=user_id, profile_id=adel.id, source="manual",
                             mime_type="text/plain", s3_key="k", raw_text="Diario de Adel",
                             processed_at=datetime.now(UTC), document_metadata={"diary_date": today}))
        await session.commit()
        assert await diary.has_diary_for(session, user_id, today, profile_id=adel.id) is True
        assert await diary.has_diary_for(session, user_id, today, profile_id=nora.id) is False
        assert await diary.has_diary_for(session, user_id, today) is True


# --- Forwarded .txt is read (finding 13) --------------------------------------

async def test_forwarded_txt_is_read_and_filed_in_history(fake_bot, linked_user, monkeypatch):
    chat_id = _chat()
    user_id = await linked_user(chat_id)
    note = b"Hoy ha comido bien en la guarder\xc3\xada."

    async def _download(file_id, mime_hint=None):
        return note, "text/plain"

    monkeypatch.setattr(diary, "tg_download", _download)
    out = await telegram_bot.handle_update(
        _msg(chat_id, document={"file_id": "d1", "file_name": "notas.txt", "mime_type": "text/plain"}))
    assert out["action"] == "file_received"
    doc = (await _docs_for(user_id))[0]
    assert doc.raw_text is None and "diary_date" not in doc.document_metadata

    _stub_pipeline(monkeypatch, body=note)
    await docs_mod._process_document_inner(doc.id, "text/plain")

    doc = (await _docs_for(user_id))[0]
    assert "guardería" in doc.raw_text and doc.processed_at is not None
    assert "historial" in fake_bot[-1][1] and "diario" not in fake_bot[-1][1].lower()


# --- Text diary survives extract/embed failure (findings 16/23) ---------------

async def test_text_diary_survives_pipeline_failure(fake_bot, linked_user, monkeypatch):
    chat_id = _chat()
    user_id = await linked_user(chat_id)
    await telegram_bot.handle_update(_msg(chat_id, text="Ha dormido fatal y ha comido poco"))
    doc = (await _docs_for(user_id))[0]
    original = doc.raw_text

    async def _boom(text, *, diary_date=None):
        raise RuntimeError("MISTRAL_API_KEY not set")

    _stub_pipeline(monkeypatch, extract=_boom)
    fake_bot.clear()
    await docs_mod._process_document_inner(doc.id, "text/plain")

    doc = (await _docs_for(user_id))[0]
    assert doc.raw_text == original and doc.processed_at is not None
    assert fake_bot == []  # the sync "Anotado" reply was the confirmation; no second message
    async with AsyncSessionLocal() as session:
        n = await session.scalar(sa.select(sa.func.count()).select_from(Chunk).where(Chunk.document_id == doc.id))
    assert n == 0


# --- Voice diary header + caption + diary extraction (findings 4/5/21) --------

async def test_voice_diary_gets_header_and_diary_extraction(fake_bot, linked_user, monkeypatch):
    chat_id = _chat()
    user_id = await linked_user(chat_id)

    async def _download(file_id, mime_hint=None):
        return b"OggS", "audio/ogg"

    monkeypatch.setattr(diary, "tg_download", _download)
    await telegram_bot.handle_update(_msg(chat_id, voice={"file_id": "v1", "duration": 5}))
    doc = (await _docs_for(user_id))[0]
    seen = {}

    async def _extract(text, *, diary_date=None):
        seen["diary_date"] = diary_date
        seen["text"] = text
        return []

    _stub_pipeline(monkeypatch, transcript="Ha comido medio plátano y ha dormido dos horas.",
                   extract=_extract)
    fake_bot.clear()
    await docs_mod._process_document_inner(doc.id, "audio/ogg")

    doc = (await _docs_for(user_id))[0]
    today = diary.today_iso()
    header = f"Diario de Adel, {diary.long_date(today)}."
    assert doc.raw_text.startswith(header)
    assert seen["diary_date"] == today and seen["text"].startswith(header)
    async with AsyncSessionLocal() as session:
        first = (await session.execute(
            sa.select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.chunk_index))).scalars().first()
    assert first is not None and header in first.content
    assert "He entendido" in fake_bot[-1][1] and "Adel" in fake_bot[-1][1]


async def test_extract_diary_mode_stamps_event_date(monkeypatch):
    from adelia.workers import extract as extract_mod

    seen = {}

    class _Chat:
        async def complete_async(self, **kwargs):
            seen["system"] = kwargs["messages"][0]["content"]
            payload = {"entities": [{"entity_type": "observation", "name": "feeding",
                                     "raw_quote": "medio plátano", "confidence": 0.9,
                                     "value": {"category": "feeding"}}]}
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps(payload)))])

    monkeypatch.setattr(extract_mod, "get_mistral_client", lambda: SimpleNamespace(chat=_Chat()))
    out = await extract_mod.extract_entities("Diario de Adel.\n\nHa comido medio plátano.",
                                             diary_date="2026-08-27")
    assert len(out) == 1 and out[0].event_date.isoformat() == "2026-08-27"
    assert "DAILY DIARY" in seen["system"] and "2026-08-27" in seen["system"]

    seen.clear()
    await extract_mod.extract_entities("Ha comido medio plátano.")
    assert "DAILY DIARY" not in seen["system"]


async def test_photo_caption_is_prepended_to_ocr_text(fake_bot, linked_user, monkeypatch):
    chat_id = _chat()
    user_id = await linked_user(chat_id)

    async def _download(file_id, mime_hint=None):
        return b"\x89PNG", "image/png"

    monkeypatch.setattr(diary, "tg_download", _download)
    await telegram_bot.handle_update(
        _msg(chat_id, photo=[{"file_id": "p1"}], caption="Analítica 12/08, Dra. X"))
    doc = (await _docs_for(user_id))[0]
    _stub_pipeline(monkeypatch, ocr="Hemoglobina 11.2 g/dL")
    await docs_mod._process_document_inner(doc.id, "image/png")
    doc = (await _docs_for(user_id))[0]
    assert doc.raw_text.startswith("Analítica 12/08, Dra. X\n\nHemoglobina 11.2")


# --- notify_processed wording by document kind (findings 22/24) ---------------

async def _doc(user_id, chat_id, *, mime, raw_text, extra=None, profile_id=None):
    async with AsyncSessionLocal() as session:
        d = Document(id=uuid.uuid4(), user_id=user_id, profile_id=profile_id, source="manual",
                     mime_type=mime, s3_key=f"users/{user_id}/{uuid.uuid4()}", raw_text=raw_text,
                     processed_at=datetime.now(UTC),
                     document_metadata={"telegram_chat_id": chat_id, **(extra or {})})
        session.add(d)
        await session.commit()
        return d.id


async def test_notify_wording_matches_document_kind(fake_bot, linked_user):
    chat_id = _chat()
    user_id = await linked_user(chat_id)
    today = diary.today_iso()

    await diary.notify_processed(await _doc(user_id, chat_id, mime="application/pdf", raw_text="Informe"))
    assert "historial" in fake_bot[-1][1] and "diario" not in fake_bot[-1][1].lower()

    await diary.notify_processed(await _doc(user_id, chat_id, mime="application/pdf", raw_text=None))
    assert "audio" not in fake_bot[-1][1].lower() and "historial" in fake_bot[-1][1]

    await diary.notify_processed(await _doc(user_id, chat_id, mime="audio/ogg", raw_text=None,
                                            extra={"diary_date": today}))
    assert "audio" in fake_bot[-1][1] and "no lo he guardado" in fake_bot[-1][1]

    n = len(fake_bot)
    await diary.notify_processed(await _doc(user_id, chat_id, mime="text/plain", raw_text="Diario…",
                                            extra={"diary_date": today}))
    assert len(fake_bot) == n  # text diary: already confirmed synchronously

    await diary.notify_processed(await _doc(user_id, chat_id, mime="application/pdf", raw_text="Rapport",
                                            extra={"locale": "fr"}))
    assert "historique" in fake_bot[-1][1] and "/fr/dashboard/documents/" in fake_bot[-1][1]


# --- Short acks are not diary entries (finding 25) ----------------------------

@pytest.mark.parametrize("text", ["hola", "👍", "ok", "Vale!", "Gracias", "..."])
async def test_short_acks_are_not_diary_entries(fake_bot, linked_user, text):
    chat_id = _chat()
    user_id = await linked_user(chat_id)
    out = await telegram_bot.handle_update(_msg(chat_id, text=text))
    assert out["action"] == "diary_ack"
    assert await _docs_for(user_id) == []
    fake_bot.clear()
    await diary.send_daily_reminders()
    assert chat_id in {c for c, _ in fake_bot}


def test_short_real_entries_are_kept():
    assert telegram_bot.is_ack("Día tranquilo") is False
    assert telegram_bot.is_ack("Ha vomitado") is False
    assert telegram_bot.is_ack("no ha comido") is False


# --- Suggestions gated on the bot token (finding 27) --------------------------

async def test_suggestions_hide_diary_cards_without_bot_token(linked_user, monkeypatch):
    from adelia.agent.suggestions import build_suggestions

    user_id = await linked_user(None)
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    intents = {a["intent"] for c in await build_suggestions(user_id=user_id, profile_id=None)
               for a in c["actions"]}
    assert not intents & {"link_telegram", "daily_diary"}

    monkeypatch.setattr(settings, "telegram_bot_token", "x")
    cards_out = await build_suggestions(user_id=user_id, profile_id=None)
    link_cards = [c for c in cards_out if any(a["intent"] == "link_telegram" for a in c["actions"])]
    assert len(link_cards) == 1 and link_cards[0]["payload"]["title"] == "Diario por Telegram"


# --- Locale (finding 28) --------------------------------------------------------

async def test_french_user_gets_french_bot(fake_bot, linked_user):
    chat_id = _chat()
    user_id = await linked_user(chat_id, locale="fr")
    out = await telegram_bot.handle_update(_msg(chat_id, text="Il a bien dormi et bien mangé"))
    assert out["action"] == "diary_text"
    doc = (await _docs_for(user_id))[0]
    today = diary.today_iso()
    assert doc.raw_text.startswith(f"Journal d'Adel, {diary.long_date(today, 'fr')}.")
    assert doc.document_metadata["locale"] == "fr"
    assert "journal" in fake_bot[-1][1].lower() and f"/fr/dashboard/documents/{doc.id}" in fake_bot[-1][1]
    # A French chat without today's entry is reminded in French.
    pending = _chat()
    await linked_user(pending, locale="fr")
    fake_bot.clear()
    await diary.send_daily_reminders()
    assert any(c == pending and "journée" in m for c, m in fake_bot)
    assert chat_id not in {c for c, _ in fake_bot}


def test_long_date_and_headers_per_locale():
    assert diary.long_date("2026-08-27", "es") == "27 de agosto de 2026"
    assert diary.long_date("2026-08-27", "en") == "27 August 2026"
    assert diary.long_date("2026-08-01", "fr") == "1er août 2026"
    assert diary.render_diary_text("x", "2026-08-27", "Nora", "fr").startswith("Journal de Nora, 27 août 2026.")
    assert diary.render_diary_text("x", "2026-08-27", None, "en").startswith("Diary of the baby, 27 August 2026.")
    assert diary.render_diary_text("x", "2026-08-27", "Adel").startswith("Diario de Adel, 27 de agosto de 2026.")
    assert diary.normalize_locale("fr-FR") == "fr" and diary.normalize_locale("de") == "es"


# --- Two children (finding 29) --------------------------------------------------

async def test_two_children_entry_goes_to_named_child(fake_bot, linked_user):
    chat_id = _chat()
    user_id = await linked_user(chat_id, profiles=(("Adel", "child", True), ("Nora", "child", False)))

    out = await telegram_bot.handle_update(_msg(chat_id, text="Nora: ha vomitado dos veces"))
    doc = (await _docs_for(user_id))[0]
    async with AsyncSessionLocal() as session:
        nora = await session.get(Profile, doc.profile_id)
    assert nora.display_name == "Nora"
    assert doc.raw_text.startswith("Diario de Nora,") and "ha vomitado dos veces" in doc.raw_text
    assert "Nora:" not in doc.raw_text
    assert "Nora" in fake_bot[-1][1] and out["profile_id"] == str(nora.id)

    fake_bot.clear()
    await telegram_bot.handle_update(_msg(chat_id, text="Hoy ha comido de todo en la guardería"))
    docs = sorted(await _docs_for(user_id), key=lambda d: d.created_at)
    async with AsyncSessionLocal() as session:
        adel = await session.get(Profile, docs[-1].profile_id)
    assert adel.display_name == "Adel"
    assert "Adel" in fake_bot[-1][1] and "Nora" in fake_bot[-1][1]  # hint how to address the other child


async def test_self_profile_is_not_preferred_over_child(fake_bot, linked_user):
    chat_id = _chat()
    user_id = await linked_user(chat_id, profiles=(("Mi perfil", "self", True), ("Adel", "child", False)))
    await telegram_bot.handle_update(_msg(chat_id, text="Ha dormido toda la noche"))
    doc = (await _docs_for(user_id))[0]
    async with AsyncSessionLocal() as session:
        p = await session.get(Profile, doc.profile_id)
    assert p.display_name == "Adel" and doc.raw_text.startswith("Diario de Adel,")


# --- Reminder loop: DST-safe sleep (findings 14/20/30) --------------------------

def test_reminder_sleep_respects_dst_transitions():
    tz = ZoneInfo("Europe/Madrid")
    october = datetime(2026, 10, 24, 20, 0, 5, tzinfo=tz)   # CEST → CET that night: 25 h
    march = datetime(2026, 3, 28, 20, 0, 5, tzinfo=tz)      # CET → CEST that night: 23 h
    normal = datetime(2026, 8, 27, 20, 0, 5, tzinfo=tz)
    assert seconds_until_next_reminder(october, 20) == 25 * 3600 - 5
    assert seconds_until_next_reminder(march, 20) == 23 * 3600 - 5
    assert seconds_until_next_reminder(normal, 20) == 24 * 3600 - 5
    assert seconds_until_next_reminder(datetime(2026, 8, 27, 19, 59, 0, tzinfo=tz), 20) == 60


# --- Webhook secret with non-ASCII bytes (finding 15) ---------------------------

async def test_non_ascii_secret_header_is_401(client, monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "shared-secret-abc")
    assert telegram_bot.validate_telegram_secret("é") is False
    assert telegram_bot.validate_telegram_secret("shared-secret-abc") is True
    resp = await client.post("/ingestion/telegram/webhook", json={"update_id": 1},
                             headers={b"X-Telegram-Bot-Api-Secret-Token": "é".encode("utf-8")})
    assert resp.status_code == 401
