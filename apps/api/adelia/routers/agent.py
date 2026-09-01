from __future__ import annotations
import json
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sse_starlette.sse import EventSourceResponse

from adelia import ratelimit
from adelia.auth import get_current_user_id, require_active_subscription
from adelia.agent.events import AgentEvent
from adelia.agent.orchestrator import run_agent_turn
from adelia.agent.suggestions import build_suggestions

router = APIRouter(prefix="/agent", tags=["agent"])
# A turn is up to MAX_STEPS model calls plus a full RAG answer per tool call;
# the suggestion cards on the dashboard are a cheap read of her own state.
# The paywall (adelia/auth.require_active_subscription) is applied PER ROUTE,
# not on the APIRouter, so it covers what spends money and nothing else.
# Router-level it also covered the reads and the deletes: a mother who
# cancelled saw her baby's records, transcripts and briefings answer 402 and
# could not erase a single document. GDPR art. 15 (access), 17 (erasure) and
# 20 (portability) are not features one stops paying for.
PAID = Depends(require_active_subscription)

# Conversation memory the browser is allowed to hand back. The same numbers
# routers/chat.py:30-31 has always used — the comment here used to claim it
# "mirrors" chat.py while carrying 24 x 4000, four times chat's 12 x 2000, on
# the endpoint whose loop re-sends the whole transcript up to MAX_STEPS times
# per turn (~96.000 characters per step, now ~24.000).
HISTORY_MAX_MESSAGES = 12
HISTORY_MAX_CHARS_PER_MESSAGE = 2000

# The anti-abuse ceiling, deliberately far above the cap: past it the request
# is refused, below it the excess is TRIMMED, never refused. The bounds used
# to reject with 422 at exactly the cap while the shipped web client sent the
# entire React transcript untrimmed, so the dashboard agent died silently on
# the 13th exchange — streamAgent threw, the canvas swallowed it, and the
# parent watched an empty bubble for the rest of the session. chat.py does the
# opposite and truncates (`existing.messages[-HISTORY_MAX_MESSAGES:]`), which
# is also what orchestrator.sanitize_history was already written to do.
HISTORY_HARD_LIMIT_MESSAGES = HISTORY_MAX_MESSAGES * 8
HISTORY_HARD_LIMIT_CHARS = HISTORY_MAX_CHARS_PER_MESSAGE * 8


class CardAction(BaseModel):
    intent: str
    tool_name: str | None = None
    tool_args: dict | None = None

class AgentMessage(BaseModel):
    """One prior turn. `system` is not a value a client may send: the system
    prompt is rebuilt server-side on every turn (agent/orchestrator)."""

    role: Literal["user", "assistant"]
    content: str = Field(max_length=HISTORY_HARD_LIMIT_CHARS)

    @field_validator("content")
    @classmethod
    def _truncate(cls, v: str) -> str:
        return v[:HISTORY_MAX_CHARS_PER_MESSAGE]

class AgentTurnRequest(BaseModel):
    message: str = Field(default="", max_length=4000)
    profile_id: uuid.UUID | None = None
    locale: str = "es"
    card_action: CardAction | None = None
    history: list[AgentMessage] | None = Field(
        default=None, max_length=HISTORY_HARD_LIMIT_MESSAGES
    )

    @field_validator("history")
    @classmethod
    def _keep_last(cls, v: list[AgentMessage] | None) -> list[AgentMessage] | None:
        return v[-HISTORY_MAX_MESSAGES:] if v else v

def _map_event(event: AgentEvent) -> dict:
    if event.type == "token":
        return {"event": "token", "data": json.dumps({"content": event.content})}
    if event.type == "tool_call":
        return {"event": "tool_call", "data": json.dumps({"tool_name": event.tool_name})}
    if event.type == "card":
        return {"event": "card", "data": json.dumps({"card": event.card})}
    if event.type == "error":
        return {"event": "error", "data": json.dumps({"content": event.content})}
    # The terminal frame carries both citation namespaces (audit 3.7): the
    # canvas needs them to draw the source card under the answer, and until
    # it had them every [ev_N] the model wrote was an orphan marker.
    return {
        "event": "final",
        "data": json.dumps(
            {
                "citations": event.citations,
                "evidence_citations": event.evidence_citations,
            }
        ),
    }

@router.post("/turn", dependencies=[PAID])
async def post_turn(payload: AgentTurnRequest,
                    request: Request,
                    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)]):
    card_action = payload.card_action.model_dump() if payload.card_action else None
    # A `generar_briefing` confirm runs briefing_orchestrator.run inline
    # (agent/orchestrator._run_write_tool), the very 5-stage pipeline
    # ratelimit.py caps at 6/min on POST /briefings. Entering through here it
    # was reachable 20 times a minute, so the narrower budget was bypassable
    # by picking the other door. Charge the same bucket.
    if (
        card_action
        and card_action.get("intent") == "confirm"
        and card_action.get("tool_name") == "generar_briefing"
    ):
        identity = ratelimit.identity_from(
            request.headers.get("authorization"),
            request.client.host if request.client else "unknown",
        )
        allowed, retry_after = ratelimit.check("POST", "/briefings", identity)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
    history = [m.model_dump() for m in payload.history] if payload.history else None

    async def event_publisher():
        yield {"event": "start", "data": json.dumps({})}
        async for event in run_agent_turn(user_id=user_id, profile_id=payload.profile_id,
                                          message=payload.message, card_action=card_action,
                                          history=history, locale=payload.locale):
            yield _map_event(event)

    return EventSourceResponse(event_publisher())

@router.get("/suggestions")
async def get_suggestions(user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
                          profile_id: uuid.UUID | None = None, locale: str = "es"):
    return {"cards": await build_suggestions(user_id=user_id, profile_id=profile_id, locale=locale)}
