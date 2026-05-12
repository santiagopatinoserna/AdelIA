from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

import sqlalchemy as sa

from adelia.db import AsyncSessionLocal
from adelia.models import ChatMessage, ChatSession
from adelia.schemas import ChatMessageOut, ChatSessionDetailOut, ChatSessionOut, Citation


async def create_session(*, user_id: UUID, title: str | None = None) -> ChatSessionOut:
    async with AsyncSessionLocal() as session:
        chat = ChatSession(user_id=user_id, title=title or "Nueva conversación")
        session.add(chat)
        await session.commit()
        await session.refresh(chat)
        return ChatSessionOut.model_validate(chat)


async def list_sessions(*, user_id: UUID) -> list[ChatSessionOut]:
    async with AsyncSessionLocal() as session:
        stmt = (
            sa.select(ChatSession)
            .where(
                ChatSession.user_id == user_id,
                ChatSession.deleted_at.is_(None),
            )
            .order_by(ChatSession.updated_at.desc())
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [ChatSessionOut.model_validate(r) for r in rows]


async def get_session_with_messages(
    *, session_id: UUID, user_id: UUID
) -> ChatSessionDetailOut | None:
    async with AsyncSessionLocal() as session:
        chat = await session.get(ChatSession, session_id)
        if chat is None or chat.user_id != user_id or chat.deleted_at is not None:
            return None
        msg_stmt = (
            sa.select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        msg_result = await session.execute(msg_stmt)
        msgs = msg_result.scalars().all()
        message_outs = [
            ChatMessageOut(
                id=m.id,
                session_id=m.session_id,
                role=m.role,
                content=m.content,
                citations=[Citation(**c) for c in (m.citations or [])],
                created_at=m.created_at,
            )
            for m in msgs
        ]
        return ChatSessionDetailOut(
            id=chat.id,
            title=chat.title,
            created_at=chat.created_at,
            updated_at=chat.updated_at,
            messages=message_outs,
        )


async def persist_message(
    *,
    session_id: UUID,
    user_id: UUID,
    role: Literal["user", "assistant"],
    content: str,
    citations: list[Citation] | None,
) -> ChatMessageOut:
    async with AsyncSessionLocal() as session:
        msg = ChatMessage(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            citations=[c.model_dump(mode="json") for c in citations] if citations else None,
        )
        session.add(msg)
        # Touch session.updated_at so list_sessions ordering reflects recency
        chat = await session.get(ChatSession, session_id)
        if chat is not None:
            chat.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(msg)
        return ChatMessageOut(
            id=msg.id,
            session_id=msg.session_id,
            role=msg.role,
            content=msg.content,
            citations=[Citation(**c) for c in (msg.citations or [])],
            created_at=msg.created_at,
        )


async def delete_session(*, session_id: UUID, user_id: UUID) -> bool:
    """Soft-delete a session. Returns True on success, False if not found/not owned."""
    async with AsyncSessionLocal() as session:
        chat = await session.get(ChatSession, session_id)
        if chat is None or chat.user_id != user_id or chat.deleted_at is not None:
            return False
        chat.deleted_at = datetime.now(timezone.utc)
        await session.commit()
        return True
