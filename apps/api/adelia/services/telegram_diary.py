"""Telegram-first daily diary.

The parent tells the bot how the day went, in text or as a voice note; it
lands as a diary Document (source="manual", metadata.diary_date) and runs
through the normal pipeline (voice → Voxtral transcript → entities → RAG),
so the chat and the briefings can answer "how has feeding gone this week"
with citations to concrete days. Anything better seen on the web is sent
back as a link, never crammed into Telegram.

Every user-facing string lives in MSG (es/en/fr) so the bot answers in the
language the parent uses the app in (TelegramLink.locale, set at /start).
"""
from __future__ import annotations

import asyncio
import io
import logging
import mimetypes
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import sqlalchemy as sa

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import Document, Profile, TelegramLink
from adelia.storage import S3Storage

logger = logging.getLogger(__name__)
storage = S3Storage()

BOT_API = "https://api.telegram.org"
_VOICE_MIME = "audio/ogg"  # Telegram voice notes are OGG/Opus

SUPPORTED_LOCALES = ("es", "en", "fr")
DEFAULT_LOCALE = "es"


def normalize_locale(value: str | None) -> str:
    """'fr-FR' / 'FR' / None → one of SUPPORTED_LOCALES (default es)."""
    code = (value or "").strip().lower()[:2]
    return code if code in SUPPORTED_LOCALES else DEFAULT_LOCALE


# --- Messages (es/en/fr) ---------------------------------------------------
# Plain text or Telegram HTML. Placeholders are filled with str.format.

MSG: dict[str, dict[str, str]] = {
    "es": {
        "start_no_token": ("Para enlazar tu cuenta, copia el token de tu panel AdelIA "
                           "(Importar → Telegram) y envía: /start TOKEN"),
        "start_invalid_token": "Token inválido o caducado. Genera uno nuevo desde tu panel AdelIA.",
        "start_token_used": "Ese token ya se ha usado. Genera uno nuevo desde tu panel AdelIA (Importar → Telegram).",
        "start_chat_taken": ("Este Telegram ya está enlazado a otra cuenta AdelIA. "
                             "Desenlázalo desde esa cuenta o usa otro Telegram."),
        "start_private_only": "Escríbeme en privado ({bot_url}) para enlazar tu cuenta.",
        "linked": ("✅ Cuenta enlazada. Cada tarde te preguntaré cómo ha ido el día: "
                   "respóndeme en texto o con un audio y lo guardo en su diario. "
                   "También puedes reenviarme informes, fotos o PDFs."),
        "relinked_notice": ("Tu cuenta AdelIA se ha enlazado a otro chat de Telegram y este ha dejado de estar "
                            "enlazado. Si no has sido tú, genera un token nuevo desde tu panel (Importar → Telegram)."),
        "no_link": ("Aún no has enlazado tu cuenta. En AdelIA: Importar → Telegram → copia el token "
                    "y envíame: /start TOKEN"),
        "subscription_inactive": ("Tu suscripción a AdelIA no está activa, así que de momento no puedo "
                                  "guardar nada nuevo en el historial. Reactívala aquí y seguimos: {link}"),
        "diary_ack": ("Cuéntame cómo ha ido el día (guardería, comida, sueño, cómo estaba) "
                      "y lo anoto en el diario."),
        "diary_saved": "Anotado en el diario de {name} ({date}) ✓\n{link}",
        "diary_saved_no_profile": "Anotado en el diario de hoy ({date}) ✓\n{link}",
        "diary_other_profile_hint": "Si era de otro, empieza el mensaje con su nombre: \"{example}: ...\"",
        "diary_error": "No he podido guardarlo. ¿Me lo repites?",
        "unsupported": "Cuéntame el día en texto o con un audio, o reenvíame un informe, foto o PDF.",
        "unsupported_file": "Ese tipo de archivo no lo puedo leer. Envíamelo como PDF, foto, audio o texto.",
        "file_too_large": "Ese archivo es demasiado grande (máximo 20 MB, 1 MB si es texto). Envíamelo más pequeño o súbelo desde la web.",
        "file_error": "No he podido descargar el archivo. ¿Me lo envías otra vez?",
        "voice_received": "🎙 Recibido. Lo transcribo y te digo qué he entendido en un momento.",
        "file_received": "📥 Recibido. Lo proceso y lo añado al historial.",
        "reminder": ("¿Cómo ha ido hoy? Cuéntamelo aquí, en texto o con un audio 🎙: "
                     "guardería, comida, sueño, cómo estaba. Lo guardo en su diario."),
        "notify_unreadable_audio": ("No he entendido el audio, así que no lo he guardado en el diario de hoy. "
                                    "Prueba con uno más claro o escríbemelo. Lo tienes aquí: {link}"),
        "notify_unreadable_doc": ("No he encontrado texto legible. Si es un informe, envía una foto más nítida "
                                  "o el PDF. Lo tienes igualmente en el historial: {link}"),
        "notify_unreadable_other": ("No puedo leer ese tipo de archivo. Envíamelo en PDF o como foto. "
                                    "Lo tienes igualmente en el historial: {link}"),
        "notify_voice": "He entendido:\n<i>{snippet}</i>\n\nGuardado en el diario de {name} ✓\nVerlo completo: {link}",
        "notify_diary": "Anotado en el diario de {name} ✓  {link}",
        "notify_history": "Añadido al historial ✓  {link}",
        "essentials": "Lo esencial",
        "baby": "el bebé",
        "today": "hoy",
    },
    "en": {
        "start_no_token": ("To link your account, copy the token from your AdelIA dashboard "
                           "(Import → Telegram) and send: /start TOKEN"),
        "start_invalid_token": "Invalid or expired token. Generate a new one from your AdelIA dashboard.",
        "start_token_used": "That token has already been used. Generate a new one from your AdelIA dashboard (Import → Telegram).",
        "start_chat_taken": ("This Telegram is already linked to another AdelIA account. "
                             "Unlink it from that account or use another Telegram."),
        "start_private_only": "Message me privately ({bot_url}) to link your account.",
        "linked": ("✅ Account linked. Every evening I will ask how the day went: "
                   "answer in text or with a voice note and I save it in the diary. "
                   "You can also forward me reports, photos or PDFs."),
        "relinked_notice": ("Your AdelIA account was linked to another Telegram chat and this one is no longer "
                            "linked. If that was not you, generate a new token from your dashboard (Import → Telegram)."),
        "no_link": ("Your account is not linked yet. In AdelIA: Import → Telegram → copy the token "
                    "and send me: /start TOKEN"),
        "subscription_inactive": ("Your AdelIA subscription is not active, so I cannot save anything "
                                  "new to the history right now. Reactivate it here and we carry on: {link}"),
        "diary_ack": ("Tell me how the day went (daycare, food, sleep, mood) "
                      "and I will write it in the diary."),
        "diary_saved": "Saved in {name}'s diary ({date}) ✓\n{link}",
        "diary_saved_no_profile": "Saved in today's diary ({date}) ✓\n{link}",
        "diary_other_profile_hint": "If it was about someone else, start the message with their name: \"{example}: ...\"",
        "diary_error": "I could not save that. Could you send it again?",
        "unsupported": "Tell me about the day in text or with a voice note, or forward me a report, photo or PDF.",
        "unsupported_file": "I cannot read that kind of file. Send it as a PDF, photo, audio or text.",
        "file_too_large": "That file is too large (max 20 MB, 1 MB for text). Send a smaller one or upload it from the web app.",
        "file_error": "I could not download the file. Could you send it again?",
        "voice_received": "🎙 Got it. I am transcribing it and will tell you what I understood in a moment.",
        "file_received": "📥 Got it. I am processing it and adding it to the history.",
        "reminder": ("How did today go? Tell me here, in text or with a voice note 🎙: "
                     "daycare, food, sleep, mood. I save it in the diary."),
        "notify_unreadable_audio": ("I could not understand the audio, so it is not in today's diary. "
                                    "Try a clearer one or write it to me. It is here: {link}"),
        "notify_unreadable_doc": ("I could not find readable text. If it is a report, send a sharper photo "
                                  "or the PDF. It is still in the history: {link}"),
        "notify_unreadable_other": ("I cannot read that kind of file. Send it as a PDF or a photo. "
                                    "It is still in the history: {link}"),
        "notify_voice": "I understood:\n<i>{snippet}</i>\n\nSaved in {name}'s diary ✓\nFull entry: {link}",
        "notify_diary": "Saved in {name}'s diary ✓  {link}",
        "notify_history": "Added to the history ✓  {link}",
        "essentials": "Key points",
        "baby": "the baby",
        "today": "today",
    },
    "fr": {
        "start_no_token": ("Pour lier ton compte, copie le jeton depuis ton espace AdelIA "
                           "(Importer → Telegram) et envoie : /start JETON"),
        "start_invalid_token": "Jeton invalide ou expiré. Génère-en un nouveau depuis ton espace AdelIA.",
        "start_token_used": "Ce jeton a déjà été utilisé. Génère-en un nouveau depuis ton espace AdelIA (Importer → Telegram).",
        "start_chat_taken": ("Ce Telegram est déjà lié à un autre compte AdelIA. "
                             "Délie-le depuis ce compte ou utilise un autre Telegram."),
        "start_private_only": "Écris-moi en privé ({bot_url}) pour lier ton compte.",
        "linked": ("✅ Compte lié. Chaque soir je te demanderai comment s'est passée la journée : "
                   "réponds par texte ou par vocal et je l'enregistre dans le journal. "
                   "Tu peux aussi me transférer des comptes rendus, photos ou PDF."),
        "relinked_notice": ("Ton compte AdelIA a été lié à un autre chat Telegram et celui-ci n'est plus lié. "
                            "Si ce n'était pas toi, génère un nouveau jeton depuis ton espace (Importer → Telegram)."),
        "no_link": ("Ton compte n'est pas encore lié. Dans AdelIA : Importer → Telegram → copie le jeton "
                    "et envoie-moi : /start JETON"),
        "subscription_inactive": ("Ton abonnement AdelIA n’est pas actif, je ne peux donc rien enregistrer "
                                  "de nouveau dans l’historique pour le moment. Réactive-le ici et on continue : {link}"),
        "diary_ack": ("Raconte-moi la journée (crèche, repas, sommeil, humeur) "
                      "et je la note dans le journal."),
        "diary_saved": "Noté dans le journal de {name} ({date}) ✓\n{link}",
        "diary_saved_no_profile": "Noté dans le journal du jour ({date}) ✓\n{link}",
        "diary_other_profile_hint": "Si c'était pour un autre enfant, commence le message par son prénom : \"{example} : ...\"",
        "diary_error": "Je n'ai pas pu l'enregistrer. Tu peux me le renvoyer ?",
        "unsupported": "Raconte-moi la journée par texte ou par vocal, ou transfère-moi un compte rendu, une photo ou un PDF.",
        "unsupported_file": "Je ne sais pas lire ce type de fichier. Envoie-le en PDF, photo, audio ou texte.",
        "file_too_large": "Ce fichier est trop volumineux (20 Mo maximum, 1 Mo pour du texte). Envoie-m’en un plus petit ou téléverse-le depuis l’appli web.",
        "file_error": "Je n'ai pas pu télécharger le fichier. Tu peux me le renvoyer ?",
        "voice_received": "🎙 Bien reçu. Je le transcris et je te dis ce que j'ai compris dans un instant.",
        "file_received": "📥 Bien reçu. Je le traite et je l'ajoute à l'historique.",
        "reminder": ("Comment s'est passée la journée ? Raconte-moi ici, par texte ou par vocal 🎙 : "
                     "crèche, repas, sommeil, humeur. Je l'enregistre dans le journal."),
        "notify_unreadable_audio": ("Je n'ai pas compris le vocal, il n'est donc pas dans le journal du jour. "
                                    "Essaie avec un vocal plus clair ou écris-le-moi. Il est ici : {link}"),
        "notify_unreadable_doc": ("Je n'ai pas trouvé de texte lisible. Si c'est un compte rendu, envoie une photo "
                                  "plus nette ou le PDF. Il reste dans l'historique : {link}"),
        "notify_unreadable_other": ("Je ne sais pas lire ce type de fichier. Envoie-le en PDF ou en photo. "
                                    "Il reste dans l'historique : {link}"),
        "notify_voice": "J'ai compris :\n<i>{snippet}</i>\n\nEnregistré dans le journal de {name} ✓\nVoir en entier : {link}",
        "notify_diary": "Noté dans le journal de {name} ✓  {link}",
        "notify_history": "Ajouté à l'historique ✓  {link}",
        "essentials": "L'essentiel",
        "baby": "le bébé",
        "today": "aujourd'hui",
    },
}


def t(locale: str | None, key: str, **fmt: Any) -> str:
    """Localized bot string; unknown locale falls back to Spanish."""
    table = MSG.get(normalize_locale(locale), MSG[DEFAULT_LOCALE])
    template = table.get(key) or MSG[DEFAULT_LOCALE][key]
    return template.format(**fmt) if fmt else template


# --- Log hygiene -------------------------------------------------------------

_TOKEN_URL_RE = re.compile(r"/bot\d+:[\w-]+")


class RedactBotToken(logging.Filter):
    """Masks '/bot<TOKEN>' in log records. httpx logs every request URL at
    INFO ('HTTP Request: GET https://api.telegram.org/bot123:abc/getFile'),
    so a root logger configured at INFO would print the token on each call;
    tracebacks that quote a token-bearing URL are masked the same way."""

    @staticmethod
    def _redact(value: Any) -> Any:
        text = str(value)
        return _TOKEN_URL_RE.sub("/bot<redacted>", text) if "/bot" in text else value

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(self._redact(a) for a in record.args)
        if record.exc_info and not record.exc_text:
            text = logging.Formatter().formatException(record.exc_info)
            if "/bot" in text:
                record.exc_text = _TOKEN_URL_RE.sub("/bot<redacted>", text)
        return True


_REDACT = RedactBotToken()


def install_log_redaction() -> None:
    """Redact at LogRecord creation, so every logger and handler (httpx's
    request lines, adelia tracebacks, pytest's caplog) sees a masked record.
    A logger-level Filter would not cover child loggers. Idempotent."""
    current = logging.getLogRecordFactory()
    if getattr(current, "_adelia_redacts_bot_token", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = current(*args, **kwargs)
        _REDACT.filter(record)
        return record

    factory._adelia_redacts_bot_token = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


install_log_redaction()


# --- Bot API ---------------------------------------------------------------

class TelegramApiError(RuntimeError):
    """Bot API failure whose message never carries the token-bearing URL.

    httpx errors embed the full request URL (.../bot<TOKEN>/getFile) in
    str(exc); letting one escape into logger.exception would print the bot
    token in the API log. Everything raised out of tg_download is this type.
    """


def _check(resp: httpx.Response, what: str) -> None:
    if resp.is_success:
        return
    try:
        desc = str(resp.json().get("description", ""))[:200]
    except Exception:  # noqa: BLE001 — body is not JSON
        desc = ""
    raise TelegramApiError(f"telegram {what} failed: HTTP {resp.status_code} {desc}".rstrip())


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
    except httpx.HTTPError as exc:
        # str(exc) may carry the token URL: log the type only.
        logger.error("telegram sendMessage failed: %s", type(exc).__name__)
        return False


# Explicit extension map first: python:3.12-slim has no /etc/mime.types, so
# mimetypes.guess_type() returns None for .m4a (iPhone/WhatsApp voice memos).
_EXT_MIME = {
    "oga": _VOICE_MIME, "ogg": _VOICE_MIME, "opus": _VOICE_MIME,
    "m4a": "audio/mp4", "mp4": "audio/mp4", "aac": "audio/aac", "amr": "audio/amr",
    "mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac",
    "weba": "audio/webm", "webm": "audio/webm",
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "pdf": "application/pdf", "txt": "text/plain", "md": "text/markdown",
}
_HINT_PREFIXES = ("audio/", "image/", "text/", "application/pdf")


def _mime_for(file_path: str, mime_hint: str | None) -> str:
    hint = (mime_hint or "").split(";")[0].strip().lower()
    if hint and hint != "application/octet-stream" and hint.startswith(_HINT_PREFIXES):
        return hint
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    return _EXT_MIME.get(ext) or (mimetypes.guess_type(file_path)[0] or "application/octet-stream")


# Telegram serves bots files up to 20 MB; a text file that big is not a
# note but a prompt bomb, so text/* gets a tighter cap.
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_TEXT_BYTES = 1 * 1024 * 1024


class FileTooLarge(ValueError):
    """The Telegram file exceeds what the pipeline should ingest."""


async def tg_download(file_id: str, mime_hint: str | None = None) -> tuple[bytes, str]:
    """getFile + download. Returns (bytes, mime). Raises TelegramApiError
    (transport/API) or FileTooLarge (refused before downloading)."""
    token = settings.telegram_bot_token
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            meta = await client.get(f"{BOT_API}/bot{token}/getFile", params={"file_id": file_id})
            _check(meta, "getFile")
            result = meta.json()["result"]
            file_path = result["file_path"]
            size = int(result.get("file_size") or 0)
            if size > MAX_DOWNLOAD_BYTES or (
                size > MAX_TEXT_BYTES and _mime_for(file_path, mime_hint).startswith("text/")
            ):
                raise FileTooLarge(str(size))
            blob = await client.get(f"{BOT_API}/file/bot{token}/{file_path}")
            _check(blob, "file download")
    except httpx.HTTPError as exc:
        raise TelegramApiError(f"telegram getFile transport error: {type(exc).__name__}") from None
    return blob.content, _mime_for(file_path, mime_hint)


# --- Diary semantics -----------------------------------------------------

def today_iso() -> str:
    return datetime.now(ZoneInfo(settings.diary_reminder_tz)).date().isoformat()


_MONTHS = {
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
           "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"],
}


def long_date(iso: str, locale: str | None = DEFAULT_LOCALE) -> str:
    d = date.fromisoformat(iso)
    loc = normalize_locale(locale)
    month = _MONTHS[loc][d.month - 1]
    if loc == "en":
        return f"{d.day} {month} {d.year}"
    if loc == "fr":
        day = "1er" if d.day == 1 else str(d.day)
        return f"{day} {month} {d.year}"
    return f"{d.day} de {month} de {d.year}"


def long_date_es(iso: str) -> str:
    return long_date(iso, "es")


def _starts_with_vowel(name: str) -> bool:
    first = unicodedata.normalize("NFD", name.strip()[:1]).lower()
    return bool(first) and first[0] in "aeiouh"


def render_diary_text(
    text: str, diary_date: str, profile_name: str | None, locale: str | None = DEFAULT_LOCALE
) -> str:
    loc = normalize_locale(locale)
    when = long_date(diary_date, loc)
    if loc == "en":
        who = f"{profile_name}'s diary" if profile_name else "Diary of the baby"
        header = f"{who}, {when}."
    elif loc == "fr":
        if not profile_name:
            header = f"Journal du bébé, {when}."
        elif _starts_with_vowel(profile_name):
            header = f"Journal d'{profile_name}, {when}."
        else:
            header = f"Journal de {profile_name}, {when}."
    else:
        header = f"Diario de {profile_name or 'el bebé'}, {when}."
    return f"{header}\n\n{text.strip()}"


def doc_link(document_id: uuid.UUID | str, locale: str | None = DEFAULT_LOCALE) -> str:
    return f"{settings.adelia_app_url.rstrip('/')}/{normalize_locale(locale)}/dashboard/documents/{document_id}"


def billing_link(locale: str | None = DEFAULT_LOCALE) -> str:
    """Where a parent with an inactive subscription is sent from Telegram."""
    return f"{settings.adelia_app_url.rstrip('/')}/{normalize_locale(locale)}/billing"


# --- Profiles --------------------------------------------------------------

def _fold(s: str) -> str:
    """Case- and accent-insensitive comparison key."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn"
    )


def _name_in_text(name: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(_fold(name))}(?!\w)", _fold(text)) is not None


def strip_profile_prefix(text: str, name: str) -> str:
    """'Nora: ha vomitado' / 'Nora, ha vomitado' → 'ha vomitado'."""
    m = re.match(rf"\s*{re.escape(name)}\s*[:,\-]\s*", text, flags=re.IGNORECASE)
    return text[m.end():] if m and text[m.end():].strip() else text


async def list_profiles(session, user_id: uuid.UUID) -> list[Profile]:
    rows = (
        await session.execute(
            sa.select(Profile)
            .where(Profile.user_id == user_id, Profile.deleted_at.is_(None))
            .order_by(
                (Profile.relationship == "child").desc(),
                Profile.is_default.desc(),
                Profile.created_at.asc(),
            )
        )
    ).scalars().all()
    return list(rows)


async def resolve_profile(
    session, user_id: uuid.UUID, hint_text: str | None = None
) -> tuple[Profile | None, list[Profile]]:
    """Which profile a Telegram message is about, plus all the user's profiles.

    With several profiles, a display_name mentioned in the text (or caption)
    wins ("Nora: ha vomitado"). Otherwise a child profile is preferred over
    the parent's own "Mi perfil", then the default, then the oldest.
    """
    try:
        profiles = await list_profiles(session, user_id)
    except Exception:  # noqa: BLE001 — profile is a nicety here
        logger.exception("profile lookup failed")
        return None, []
    if not profiles:
        return None, []
    if len(profiles) > 1 and hint_text:
        folded = _fold(hint_text)
        # The documented form wins first: "Nora: ha vomitado" is about Nora
        # even if the sentence goes on to mention Adel.
        for p in profiles:
            if p.display_name and re.match(rf"\s*{re.escape(_fold(p.display_name))}\s*[:,\-]", folded):
                return p, profiles
        for p in profiles:
            if p.display_name and _name_in_text(p.display_name, hint_text):
                return p, profiles
    return profiles[0], profiles


async def _default_profile(session, user_id: uuid.UUID) -> Profile | None:
    """Backwards-compatible alias: profile without any text hint."""
    profile, _ = await resolve_profile(session, user_id)
    return profile


# --- Ingestion -------------------------------------------------------------

def is_supported_mime(mime: str) -> bool:
    from adelia.routers.documents import ALLOWED_MIME

    return mime in ALLOWED_MIME or mime.startswith("audio/") or mime.startswith("text/")


class UnsupportedFileType(ValueError):
    """The forwarded file is something no pipeline stage can read."""


@dataclass
class DiaryResult:
    """What the bot needs to answer: the stored Document, the profile it
    was filed under and the other profile names (to hint how to address
    another child)."""

    document: Document
    profile: Profile | None
    other_profiles: list[str] = field(default_factory=list)


def _other_names(profiles: list[Profile], chosen: Profile | None) -> list[str]:
    """Other profiles a message could be about: the parent's own "Mi perfil"
    (relationship self) is never a diary subject, so it never appears in the
    "if it was about someone else" hint."""
    return [
        p.display_name for p in profiles
        if p.display_name and p.relationship != "self" and (chosen is None or p.id != chosen.id)
    ]


_BACKGROUND_TASKS: set[asyncio.Task] = set()


async def ingest_bytes(
    *,
    user_id: uuid.UUID,
    body: bytes,
    mime: str,
    filename: str,
    raw_text: str | None = None,
    metadata: dict[str, Any] | None = None,
    profile_id: uuid.UUID | None = None,
) -> Document:
    """Store a blob + Document and schedule the pipeline (no request context,
    so asyncio.create_task instead of FastAPI BackgroundTasks)."""
    from adelia.routers.documents import (
        AUDIO_GRACE_UNPROCESSED,
        process_document,
        schedule_audio_deletion,
    )

    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)[:80]
    s3_key = f"users/{user_id}/{uuid.uuid4()}-{safe}"
    await storage.put_object(s3_key, io.BytesIO(body), content_type=mime)

    async with AsyncSessionLocal() as session:
        doc = Document(
            id=uuid.uuid4(),
            user_id=user_id,
            profile_id=profile_id,
            source="manual",
            mime_type=mime,
            s3_key=s3_key,
            raw_text=raw_text,
            document_metadata=metadata or {},
        )
        session.add(doc)
        try:
            if mime.startswith("audio/"):
                # Same rule as the web upload: a voice note gets its deletion
                # date in the same transaction that records it, so an
                # interrupted pipeline cannot leave the parent's voice in
                # MinIO with nothing scheduled to remove it. The pipeline
                # brings it forward to 48h once the transcript exists.
                await schedule_audio_deletion(session, s3_key, AUDIO_GRACE_UNPROCESSED)
            await session.commit()
        except Exception:
            try:
                await storage.delete_object(s3_key)
            except Exception:  # noqa: BLE001
                logger.exception("orphan blob cleanup failed for %s", s3_key)
            raise
        await session.refresh(doc)
        doc_id, mime_type = doc.id, doc.mime_type
    # Keep a strong reference: the event loop only holds a weak one, so a
    # bare create_task() can be garbage-collected mid-pipeline (asyncio docs).
    task = asyncio.create_task(process_document(doc_id, mime_type, False))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return doc


async def has_diary_for(
    session, user_id: uuid.UUID, diary_date: str, profile_id: uuid.UUID | None = None
) -> bool:
    """True if the day already has an entry: pending (still transcribing) or
    successfully processed. A failed one (processed_at set, no text) does not
    count, so the reminder and the daily card come back for that day.

    With profile_id, entries of that profile count, plus entries without a
    profile (older rows / users without profiles)."""
    conditions = [
        Document.user_id == user_id,
        Document.deleted_at.is_(None),
        Document.document_metadata["diary_date"].astext == diary_date,
        sa.or_(Document.processed_at.is_(None), Document.raw_text.isnot(None)),
    ]
    if profile_id is not None:
        conditions.append(sa.or_(Document.profile_id == profile_id, Document.profile_id.is_(None)))
    n = await session.scalar(sa.select(sa.func.count()).select_from(Document).where(*conditions))
    return bool(n)


async def diary_from_text(
    *, user_id: uuid.UUID, chat_id: int, text: str, locale: str | None = DEFAULT_LOCALE
) -> DiaryResult:
    diary_date = today_iso()
    loc = normalize_locale(locale)
    async with AsyncSessionLocal() as session:
        profile, profiles = await resolve_profile(session, user_id, text)
    body_text = strip_profile_prefix(text, profile.display_name) if profile else text
    rendered = render_diary_text(body_text, diary_date, profile.display_name if profile else None, loc)
    doc = await ingest_bytes(
        user_id=user_id,
        body=rendered.encode("utf-8"),
        mime="text/plain",
        filename=f"diario-{diary_date}.txt",
        raw_text=rendered,
        metadata={"diary_date": diary_date, "channel": "telegram", "telegram_chat_id": chat_id,
                  "locale": loc},
        profile_id=profile.id if profile else None,
    )
    return DiaryResult(doc, profile, _other_names(profiles, profile))


async def diary_from_file(
    *,
    user_id: uuid.UUID,
    chat_id: int,
    file_id: str,
    kind: str,
    filename: str | None,
    mime_hint: str | None = None,
    caption: str | None = None,
    locale: str | None = DEFAULT_LOCALE,
) -> DiaryResult:
    body, mime = await tg_download(file_id, mime_hint)
    is_voice = kind in ("voice", "audio")
    if is_voice and not mime.startswith("audio/"):
        # Never file a voice note as octet-stream: it would skip transcription.
        mime = _VOICE_MIME if kind == "voice" else "audio/mp4"
    if not is_supported_mime(mime):
        raise UnsupportedFileType(mime)
    diary_date = today_iso()
    loc = normalize_locale(locale)
    meta: dict[str, Any] = {"channel": "telegram", "telegram_chat_id": chat_id, "locale": loc}
    if is_voice:
        meta["diary_date"] = diary_date
    if caption:
        meta["caption"] = caption
    async with AsyncSessionLocal() as session:
        profile, profiles = await resolve_profile(session, user_id, caption)
    ext = mime.split("/")[-1].replace("jpeg", "jpg").replace("x-m4a", "m4a").replace("mp4", "m4a")
    name = filename or (f"diario-{diary_date}.{ext}" if is_voice else f"telegram-{diary_date}.{ext}")
    doc = await ingest_bytes(
        user_id=user_id, body=body, mime=mime, filename=name, metadata=meta,
        profile_id=profile.id if profile else None,
    )
    return DiaryResult(doc, profile, _other_names(profiles, profile))


# --- Notifications ---------------------------------------------------------

async def notify_processed(document_id: uuid.UUID) -> None:
    """After the pipeline finishes a Telegram-originated document, tell the
    parent what was understood and link to the web when it reads better.

    Text diary entries were already confirmed synchronously by the bot
    (their text never depends on the pipeline), so they get no second
    message."""
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return
        meta = doc.document_metadata or {}
        chat_id = meta.get("telegram_chat_id")
        if not chat_id:
            return
        is_diary = bool(meta.get("diary_date"))
        mime = doc.mime_type or ""
        if is_diary and mime.startswith("text/"):
            return
        loc = normalize_locale(meta.get("locale"))
        raw = (doc.raw_text or "").strip()
        link = doc_link(doc.id, loc)
        name = t(loc, "baby")
        if doc.profile_id is not None:
            profile = await session.get(Profile, doc.profile_id)
            if profile is not None and profile.display_name:
                name = profile.display_name
        if not raw:
            if mime.startswith("audio/"):
                text = t(loc, "notify_unreadable_audio", link=link)
            elif mime == "application/pdf" or mime.startswith("image/"):
                text = t(loc, "notify_unreadable_doc", link=link)
            else:
                text = t(loc, "notify_unreadable_other", link=link)
        elif is_diary and mime.startswith("audio/"):
            # The pipeline prefixed the transcript with the synthetic diary
            # header; quote only what the parent actually said.
            body = raw
            header = render_diary_text("", meta.get("diary_date"), name if doc.profile_id else None, loc).strip()
            if header and body.startswith(header):
                body = body[len(header):].strip()
            snippet = body[:600] + ("…" if len(body) > 600 else "")
            text = t(loc, "notify_voice", snippet=_html(snippet), name=_html(name), link=link)
        elif is_diary:
            text = t(loc, "notify_diary", name=_html(name), link=link)
        else:
            text = t(loc, "notify_history", link=link)
        summary = meta.get("summary")
        if summary:
            text += f"\n\n<b>{t(loc, 'essentials')}</b>\n{_html(summary)}"
    await tg_send(int(chat_id), text)


def _html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def send_daily_reminders() -> int:
    """Nudge every linked chat of a PAYING parent with no diary entry today.

    The paywall was put on the way in (ingestion/telegram_bot.handle_update)
    and not on the way out: this select had no join against users, so the
    20:00 job kept asking a mother who cancelled months ago "¿Cómo ha ido hoy?"
    every single night, and answering it earned her the payment refusal. One
    statement, not a per-link has_active_subscription call, which would open a
    session per chat. ACTIVE_STATUSES is a set, hence sorted() for .in_();
    both imports are local because routers.billing imports back into this
    graph, the same reason adelia/auth.py defers them.
    """
    from adelia.auth import billing_is_enabled
    from adelia.models import User
    from adelia.routers.billing import ACTIVE_STATUSES

    diary_date = today_iso()
    sent = 0
    async with AsyncSessionLocal() as session:
        stmt = sa.select(TelegramLink)
        if billing_is_enabled():
            # No Stripe key = nothing is sold on this instance and no account
            # can ever leave "none"; filtering would silence the bot entirely
            # on a self-hosted install. Same rule as the HTTP gate.
            # The card-free trial (audit 4.7) is derived, not stored, so an
            # account inside it still reads "none" in this column. Expressing
            # it in SQL keeps this ONE statement: without the second branch
            # the nightly nudge would go silent for exactly the accounts the
            # trial exists to keep, which are every new account there is.
            eligible = User.subscription_status.in_(sorted(ACTIVE_STATUSES))
            if settings.free_trial_days > 0:
                eligible = sa.or_(
                    eligible,
                    sa.and_(
                        User.subscription_status == "none",
                        User.created_at
                        > sa.func.now()
                        - sa.text(f"interval '{int(settings.free_trial_days)} days'"),
                    ),
                )
            stmt = stmt.join(User, User.id == TelegramLink.user_id).where(eligible)
        links = (await session.execute(stmt)).scalars().all()
        targets = [
            (link.chat_id, link.locale)
            for link in links
            if not await has_diary_for(session, link.user_id, diary_date)
        ]
    for chat_id, loc in targets:
        ok = await tg_send(int(chat_id), t(loc, "reminder"))
        sent += int(ok)
    return sent
