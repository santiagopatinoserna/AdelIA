from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID, uuid4

from adelia.agent import cards
from adelia.config import settings

@dataclass
class ProfileState:
    has_dob: bool
    unprocessed_docs: int
    stale_briefing: bool
    is_child: bool
    telegram_linked: bool = False
    diary_today: bool = False
    # False when TELEGRAM_BOT_TOKEN is empty: the bot is dead, so offering
    # "Enlazar" would send the parent to a chat that never answers.
    telegram_enabled: bool = False

def _cid() -> str:
    return uuid4().hex[:12]

async def _gather_state(*, user_id: UUID, profile_id: UUID | None) -> ProfileState:
    from adelia.db import AsyncSessionLocal
    from sqlalchemy import select, func
    from adelia.models import Document
    from adelia.enrichment import profile_service
    async with AsyncSessionLocal() as session:
        prof = None
        if profile_id is not None:
            prof = await profile_service.get_profile(session, profile_id=profile_id, user_id=user_id)
        unprocessed = await session.scalar(
            select(func.count()).select_from(Document)
            .where(Document.user_id == user_id, Document.deleted_at.is_(None),
                   Document.processed_at.is_(None)))
        from adelia.models import TelegramLink
        from adelia.services.telegram_diary import has_diary_for, today_iso
        linked = await session.scalar(
            select(func.count()).select_from(TelegramLink).where(TelegramLink.user_id == user_id))
        # Per profile: with two children, Nora's card stays while Adel's
        # entry is written (entries without profile count for everyone).
        diary_today = await has_diary_for(session, user_id, today_iso(), profile_id=profile_id)
        return ProfileState(
            has_dob=bool(prof and prof.date_of_birth),
            unprocessed_docs=int(unprocessed or 0),
            stale_briefing=False,
            is_child=bool(prof and prof.relationship == "child"),
            telegram_linked=bool(linked),
            diary_today=bool(diary_today),
            telegram_enabled=bool(settings.telegram_bot_token))

async def build_suggestions(*, user_id: UUID, profile_id: UUID | None, locale: str = "es") -> list[dict]:
    state = await _gather_state(user_id=user_id, profile_id=profile_id)
    out: list[dict] = []
    if state.is_child and not state.has_dob:
        out.append(cards.card_question(_cid(), "date_of_birth",
                                       "¿Cuál es la fecha de nacimiento del bebé?", input_type="date"))
    if state.telegram_enabled and not state.diary_today:
        if state.telegram_linked:
            out.append(cards.card_action(_cid(), "¿Cómo ha ido hoy?",
                                         "Cuéntamelo por Telegram, en texto o con un audio, y lo guardo en su diario.",
                                         "Abrir Telegram", "daily_diary"))
        else:
            out.append(cards.card_action(_cid(), "Diario por Telegram",
                                         "Enlaza Telegram y cada tarde te preguntaré cómo ha ido el día. "
                                         "Respondes con un audio y listo.",
                                         "Enlazar", "link_telegram"))
    if state.unprocessed_docs:
        out.append(cards.card_action(_cid(), "Documentos sin procesar",
                                     f"Tienes {state.unprocessed_docs} documento(s) por procesar.",
                                     "Procesar", "process_docs"))
    if state.stale_briefing:
        out.append(cards.card_action(_cid(), "Briefing desactualizado",
                                     "Tu briefing tiene datos nuevos sin incluir.", "Regenerar", "regen_briefing"))
    if not out:
        out.append(cards.card_insight(_cid(), "Todo al día",
                                      "Pregúntame lo que quieras sobre la salud de tu bebé.", tone="positive"))
    return out
