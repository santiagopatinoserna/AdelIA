"""The agent's conversation, kept on the server (decision of 2026-11-06).

The /dashboard agent held its transcript only in React state: a reload lost
it, and nothing she asked was in her history. "Lo que se va diciendo, ve
grabándolo": each turn is now stored in the chat's own tables, under a session
whose `surface` is 'agent' (migration 0025), so the history lists it and the
panel can pick the conversation up again after a reload.

What is stored is what she saw: her message and the answer's full text with
both citation lists. A turn that failed is not stored (she is offered to ask
again, and a stored half would replay as history). A clarify press re-sends
her question with the value, so only its answer is stored, not the question a
second time. Sessions are opened per write and never held across the stream.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from adelia.db import AsyncSessionLocal
from adelia.models import ChatMessage, ChatSession

#: How long after its last turn a conversation is still "the one she is in".
#: Past it the panel opens on the greeting and "Hoy" again, as every morning;
#: the conversation itself stays in the history.
RESUME_WINDOW = timedelta(hours=12)
_TITLE_CHARS = 80


async def record_turn(
    *,
    user_id: uuid.UUID,
    thread_id: uuid.UUID | None,
    profile_id: uuid.UUID | None,
    message: str | None,
    answer: str,
    citations: list[dict],
    evidence_citations: list[dict],
) -> uuid.UUID | None:
    """Store one turn; returns the thread it went to (None when nothing to store).

    A `thread_id` that is not one of HER agent sessions is ignored and a new
    thread is opened: the id comes from the browser.
    """
    question = (message or "").strip()
    if not question and not answer:
        return None
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        chat = None
        if thread_id is not None:
            chat = await session.scalar(
                sa.select(ChatSession).where(
                    ChatSession.id == thread_id, ChatSession.user_id == user_id,
                    ChatSession.surface == "agent", ChatSession.deleted_at.is_(None))
            )
        if chat is None:
            chat = ChatSession(user_id=user_id, surface="agent", profile_id=profile_id,
                               title=(question or answer)[:_TITLE_CHARS])
            session.add(chat)
            await session.flush()
        if question:
            session.add(ChatMessage(session_id=chat.id, user_id=user_id, role="user",
                                    content=question, created_at=now))
        if answer:
            session.add(ChatMessage(session_id=chat.id, user_id=user_id, role="assistant",
                                    content=answer, citations=citations or None,
                                    evidence_citations=evidence_citations or None,
                                    created_at=now + timedelta(microseconds=1)))
        chat.updated_at = now
        if profile_id is not None:
            chat.profile_id = profile_id
        await session.commit()
        return chat.id


async def latest_thread(
    *, user_id: uuid.UUID, profile_id: uuid.UUID | None, now: datetime | None = None
) -> dict | None:
    """Her newest agent conversation about this child, if it is recent."""
    now = now or datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        stmt = sa.select(ChatSession).where(
            ChatSession.user_id == user_id, ChatSession.surface == "agent",
            ChatSession.deleted_at.is_(None), ChatSession.updated_at >= now - RESUME_WINDOW,
        )
        if profile_id is not None:
            stmt = stmt.where(ChatSession.profile_id == profile_id)
        chat = await session.scalar(stmt.order_by(ChatSession.updated_at.desc()).limit(1))
        if chat is None:
            return None
        rows = (await session.execute(
            sa.select(ChatMessage).where(ChatMessage.session_id == chat.id)
            .order_by(ChatMessage.created_at.asc())
        )).scalars().all()
    return {
        "id": str(chat.id),
        "profile_id": str(chat.profile_id) if chat.profile_id else None,
        "messages": [
            {"role": m.role, "content": m.content, "citations": m.citations or [],
             "evidence_citations": m.evidence_citations or []}
            for m in rows
        ],
    }
