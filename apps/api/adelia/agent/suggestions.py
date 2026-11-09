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
    # A guest of the landing (users.is_guest) is trying AdelIA with Lucía: a
    # diary bot for a sample child is a promise she cannot use, and the link
    # would tie her Telegram to an account she may never keep (2026-11-09).
    is_guest: bool = False
    # Card kinds she closed (services/dismissals): never built again for her.
    dismissed: frozenset[str] = frozenset()

def _cid() -> str:
    return uuid4().hex[:12]

async def _gather_state(*, user_id: UUID, profile_id: UUID | None) -> ProfileState:
    from adelia.db import AsyncSessionLocal
    from sqlalchemy import select, func
    from adelia.models import Document
    from adelia.enrichment import profile_service
    from adelia.models import User
    from adelia.services.dismissals import dismissed_keys
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
        # Per profile only when the active profile is a child (the bot files
        # entries under children): with two children, Nora's card stays while
        # Adel's entry is written. For the parent's own "Mi perfil" (self) or
        # no profile, any entry of the day counts, otherwise the card would
        # never clear when the default profile is the parent's.
        scope = profile_id if (prof is not None and prof.relationship == "child") else None
        diary_today = await has_diary_for(session, user_id, today_iso(), profile_id=scope)
        is_guest = await session.scalar(select(User.is_guest).where(User.id == user_id))
        dismissed = await dismissed_keys(session, user_id)
        return ProfileState(
            has_dob=bool(prof and prof.date_of_birth),
            unprocessed_docs=int(unprocessed or 0),
            stale_briefing=False,
            is_child=bool(prof and prof.relationship == "child"),
            telegram_linked=bool(linked),
            diary_today=bool(diary_today),
            telegram_enabled=bool(settings.telegram_bot_token),
            is_guest=bool(is_guest),
            dismissed=dismissed)

# Every word a suggestion card shows, per locale. The router has always passed
# `locale`, but the cards were written in Spanish only, so a French or English
# mother read "Diario por Telegram ... Enlazar" under every answer
# (docs/design/RECORRIDO_POC.md). Unknown locales fall back to Spanish.
_NB = "\u00a0"  # French puts a no-break space before "?" (same as messages/fr.json)
_TEXT: dict[str, dict[str, str]] = {
    "es": {
        "dob": "¿Cuál es la fecha de nacimiento del bebé?", "save": "Guardar",
        "diary_title": "¿Cómo ha ido hoy?",
        "diary_body": "Cuéntamelo por Telegram, en texto o con un audio, y lo guardo en su diario.",
        "diary_cta": "Abrir Telegram",
        "link_title": "Diario por Telegram",
        "link_body": "Enlaza Telegram y cada tarde te preguntaré cómo ha ido el día. "
                     "Respondes con un audio y listo.",
        "link_cta": "Enlazar",
        "docs_title": "Documentos sin procesar",
        "docs_body": "Tienes {n} documento(s) por procesar.", "docs_cta": "Procesar",
        "stale_title": "Briefing desactualizado",
        "stale_body": "Tu briefing tiene datos nuevos sin incluir.", "stale_cta": "Regenerar",
        "ok_title": "Todo al día",
        "ok_body": "Pregúntame lo que quieras sobre la salud de tu bebé.",
    },
    "en": {
        "dob": "What is the baby's date of birth?", "save": "Save",
        "diary_title": "How did today go?",
        "diary_body": "Tell me on Telegram, in text or a voice note, and I'll add it to the diary.",
        "diary_cta": "Open Telegram",
        "link_title": "Diary on Telegram",
        "link_body": "Link Telegram and every evening I'll ask how the day went. "
                     "Reply with a voice note and that's it.",
        "link_cta": "Link",
        "docs_title": "Documents waiting",
        "docs_body": "You have {n} document(s) to process.", "docs_cta": "Process",
        "stale_title": "Report out of date",
        "stale_body": "Your report has new data it does not include yet.", "stale_cta": "Update",
        "ok_title": "All up to date",
        "ok_body": "Ask me anything about your baby's health.",
    },
    "fr": {
        "dob": f"Quelle est la date de naissance du bébé{_NB}?", "save": "Enregistrer",
        "diary_title": f"Comment s’est passée la journée{_NB}?",
        "diary_body": "Raconte-le-moi sur Telegram, par écrit ou en audio, "
                      "et je l’ajoute à son journal.",
        "diary_cta": "Ouvrir Telegram",
        "link_title": "Journal sur Telegram",
        "link_body": "Lie Telegram et chaque soir je te demanderai comment s’est passée "
                     "la journée. Tu réponds par un audio, c’est tout.",
        "link_cta": "Lier",
        "docs_title": "Documents à traiter",
        "docs_body": "Tu as {n} document(s) à traiter.", "docs_cta": "Traiter",
        "stale_title": "Résumé à mettre à jour",
        "stale_body": "Ton résumé a de nouvelles données qu’il n’inclut pas encore.",
        "stale_cta": "Mettre à jour",
        "ok_title": "Tout est à jour",
        "ok_body": "Demande-moi ce que tu veux sur la santé de ton bébé.",
    },
}


def _closable(card: dict, key: str) -> dict:
    """Name the kind she can close: the card id is random on every request."""
    card["payload"]["dismiss_key"] = key
    return card


async def build_suggestions(*, user_id: UUID, profile_id: UUID | None, locale: str = "es") -> list[dict]:
    state = await _gather_state(user_id=user_id, profile_id=profile_id)
    tx = _TEXT.get(locale, _TEXT["es"])
    out: list[dict] = []
    if state.is_child and not state.has_dob and "date_of_birth" not in state.dismissed:
        out.append(_closable(cards.card_question(_cid(), "date_of_birth", tx["dob"],
                                                 input_type="date", action_label=tx["save"]),
                             "date_of_birth"))
    if state.telegram_enabled and not state.diary_today and not state.is_guest:
        # Linking replaces the link card with the daily one: no state to clear.
        if state.telegram_linked:
            if "daily_diary" not in state.dismissed:
                out.append(_closable(cards.card_action(_cid(), tx["diary_title"], tx["diary_body"],
                                                       tx["diary_cta"], "daily_diary"),
                                     "daily_diary"))
        elif "link_telegram" not in state.dismissed:
            out.append(_closable(cards.card_action(_cid(), tx["link_title"], tx["link_body"],
                                                   tx["link_cta"], "link_telegram"),
                                 "link_telegram"))
    if state.unprocessed_docs and "process_docs" not in state.dismissed:
        out.append(_closable(cards.card_action(_cid(), tx["docs_title"],
                                               tx["docs_body"].format(n=state.unprocessed_docs),
                                               tx["docs_cta"], "process_docs"),
                             "process_docs"))
    if state.stale_briefing and "regen_briefing" not in state.dismissed:
        out.append(_closable(cards.card_action(_cid(), tx["stale_title"], tx["stale_body"],
                                               tx["stale_cta"], "regen_briefing"),
                             "regen_briefing"))
    if not out:
        out.append(cards.card_insight(_cid(), tx["ok_title"], tx["ok_body"], tone="positive"))
    return out
