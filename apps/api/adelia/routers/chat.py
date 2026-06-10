import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from adelia.auth import get_current_user_id
from adelia.schemas import ChatCitation, ChatRequest, ChatSessionDetailOut, ChatSessionOut
from adelia.services.chat_orchestrator import answer_question_streaming
from adelia.services.chat_repo import (
    create_session,
    delete_session,
    get_session_with_messages,
    list_sessions,
    persist_message,
)


router = APIRouter(prefix="/chat", tags=["chat"])

# Conversation memory passed to the LLM: last N turns, each truncated. Bounds
# prompt size; RAG context is re-retrieved fresh per question anyway.
HISTORY_MAX_MESSAGES = 12
HISTORY_MAX_CHARS_PER_MESSAGE = 2000


@router.get("/sessions", response_model=list[ChatSessionOut])
async def list_chat_sessions(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
    return await list_sessions(user_id=user_id)


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailOut)
async def get_chat_session(
    session_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
    detail = await get_session_with_messages(session_id=session_id, user_id=user_id)
    if detail is None:
        raise HTTPException(status_code=404)
    return detail


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(
    session_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
    ok = await delete_session(session_id=session_id, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=404)
    return None


@router.post("")
async def post_chat(
    payload: ChatRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
    """SSE endpoint: streams ChatEvent JSON payloads back to the client."""
    # Create or load session
    history: list[dict] = []
    if payload.session_id is None:
        new_session = await create_session(user_id=user_id)
        session_id = new_session.id
    else:
        existing = await get_session_with_messages(
            session_id=payload.session_id, user_id=user_id
        )
        if existing is None:
            raise HTTPException(status_code=404)
        session_id = existing.id
        history = [
            {
                "role": m.role,
                "content": m.content[:HISTORY_MAX_CHARS_PER_MESSAGE],
            }
            for m in existing.messages[-HISTORY_MAX_MESSAGES:]
            if m.content
        ]

    # Persist user message before streaming begins
    await persist_message(
        session_id=session_id,
        user_id=user_id,
        role="user",
        content=payload.question,
        citations=None,
    )

    async def event_publisher():
        assistant_content_parts: list[str] = []
        final_citations: list[ChatCitation] = []
        # session_id sent once at start; subsequent token events carry only content
        yield {
            "event": "start",
            "data": json.dumps({"session_id": str(session_id)}),
        }
        try:
            async for event in answer_question_streaming(
                user_id=user_id, question=payload.question, history=history
            ):
                if event.type == "token":
                    assistant_content_parts.append(event.content)
                    yield {
                        "event": "token",
                        "data": json.dumps({"content": event.content}),
                    }
                elif event.type == "final":
                    final_citations = event.citations
                    yield {
                        "event": "final",
                        "data": json.dumps(
                            {
                                "session_id": str(session_id),
                                "citations": [c.model_dump(mode="json") for c in event.citations],
                            }
                        ),
                    }
                elif event.type == "error":
                    yield {
                        "event": "error",
                        "data": json.dumps({"content": event.content}),
                    }
        finally:
            # Persist assistant message even on partial failure
            assistant_content = "".join(assistant_content_parts)
            await persist_message(
                session_id=session_id,
                user_id=user_id,
                role="assistant",
                content=assistant_content,
                citations=final_citations,
            )

    return EventSourceResponse(event_publisher())
