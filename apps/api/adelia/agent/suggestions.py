from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID, uuid4

from adelia.agent import cards

@dataclass
class ProfileState:
    has_dob: bool
    unprocessed_docs: int
    stale_briefing: bool
    is_child: bool

def _cid() -> str:
    return uuid4().hex[:12]

async def _gather_state(*, user_id: UUID, profile_id: UUID | None) -> ProfileState:
    from adelia.db import AsyncSessionLocal
    from sqlalchemy import select, func
    from adelia.models import Document, Profile
    async with AsyncSessionLocal() as session:
        prof = None
        if profile_id is not None:
            prof = await session.get(Profile, profile_id)
        unprocessed = await session.scalar(
            select(func.count()).select_from(Document)
            .where(Document.user_id == user_id, Document.deleted_at.is_(None),
                   Document.processed_at.is_(None)))
        return ProfileState(
            has_dob=bool(prof and prof.date_of_birth),
            unprocessed_docs=int(unprocessed or 0),
            stale_briefing=False,
            is_child=bool(prof and prof.relationship == "child"))

async def build_suggestions(*, user_id: UUID, profile_id: UUID | None, locale: str = "es") -> list[dict]:
    state = await _gather_state(user_id=user_id, profile_id=profile_id)
    out: list[dict] = []
    if state.is_child and not state.has_dob:
        out.append(cards.card_question(_cid(), "date_of_birth",
                                       "¿Cuál es la fecha de nacimiento del bebé?", input_type="date"))
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
