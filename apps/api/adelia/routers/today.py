"""`GET /today`: the home card's content, computed server-side (services/today).

Not behind the paywall on purpose, like the suggestions read in routers/agent:
it spends no money and shows a mother her own record.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from adelia.agent.graph import LOCAL_TZ
from adelia.auth import get_current_user_id
from adelia.services.today import build_today

router = APIRouter(prefix="/today", tags=["today"])


@router.get("")
async def get_today(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    profile_id: uuid.UUID | None = None,
    locale: str = "es",
):
    return await build_today(
        user_id=user_id, profile_id=profile_id, locale=locale, now=datetime.now(LOCAL_TZ)
    )
