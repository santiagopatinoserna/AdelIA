from __future__ import annotations
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from adelia.auth import get_current_user_id
from adelia.agent.events import AgentEvent
from adelia.agent.orchestrator import run_agent_turn
from adelia.agent.suggestions import build_suggestions

router = APIRouter(prefix="/agent", tags=["agent"])

class CardAction(BaseModel):
    intent: str
    tool_name: str | None = None
    tool_args: dict | None = None

class AgentTurnRequest(BaseModel):
    message: str = Field(default="", max_length=4000)
    profile_id: uuid.UUID | None = None
    locale: str = "es"
    card_action: CardAction | None = None

def _map_event(event: AgentEvent) -> dict:
    if event.type == "token":
        return {"event": "token", "data": json.dumps({"content": event.content})}
    if event.type == "tool_call":
        return {"event": "tool_call", "data": json.dumps({"tool_name": event.tool_name})}
    if event.type == "card":
        return {"event": "card", "data": json.dumps({"card": event.card})}
    if event.type == "error":
        return {"event": "error", "data": json.dumps({"content": event.content})}
    return {"event": "final", "data": json.dumps({})}

@router.post("/turn")
async def post_turn(payload: AgentTurnRequest,
                    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)]):
    card_action = payload.card_action.model_dump() if payload.card_action else None

    async def event_publisher():
        yield {"event": "start", "data": json.dumps({})}
        async for event in run_agent_turn(user_id=user_id, profile_id=payload.profile_id,
                                          message=payload.message, card_action=card_action,
                                          locale=payload.locale):
            yield _map_event(event)

    return EventSourceResponse(event_publisher())

@router.get("/suggestions")
async def get_suggestions(user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
                          profile_id: uuid.UUID | None = None, locale: str = "es"):
    return {"cards": await build_suggestions(user_id=user_id, profile_id=profile_id, locale=locale)}
