"""`GET /history`: one child's record, a month at a time, for Historial.

First in the order of work of docs/specs/ADELIA_SIMPLE.md: what she noted, her
documents and her recordings in one list, per child, since birth. Until this
route Historial (/dashboard/overview) listed the account's documents only. A
note she confirmed in the panel ("Anotado") came back through a question and
nowhere else, and after four of them the page still said "Bienvenida a AdelIA,
sube tu primer informe" (QA 2026-11-12; the fix stayed uncommitted, five lines
of GET /observations/recent, on claude/rescue-2026-11-13).

A month per request. A month of feeds is a few hundred lines at most; a month
needs no cursor (notes with a day and no hour all sit at 12:00, and a timestamp
cursor would skip some of them at a page break); and `months` names the ones
that hold something, so the month she was born is one tap away instead of a
page per empty month.

Days and times are Madrid's (agent/graph.LOCAL_TZ), the zone the web prints
every date in (lib/dates APP_TIME_ZONE): a note at 00:30 sits on its own day on
the server and on her phone.

Scoped like every read (services/scope). Without `profile_id` it is the default
child, the one she picked last (the home's ProfileSwitcher stores her pick as
the default), never the whole account. A profile id that is not hers reads
nothing rather than widening to her account. Documents filed before profiles
existed (profile_id NULL) show under every child, as in GET /documents.

Free, like GET /documents and GET /today: it spends nothing and it is her own
record, which a lapsed subscription must not lock (GDPR art. 15;
tests/test_subscription_gate FREE_ROUTES).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query

from adelia.agent import record
from adelia.agent.graph import LOCAL_TZ
from adelia.auth import get_current_user_id
from adelia.db import AsyncSessionLocal
from adelia.enrichment.profile_service import get_profile_facts
from adelia.models import Document, Observation
from adelia.routers.documents import _doc_to_out
from adelia.services.scope import Scope

router = APIRouter(prefix="/history", tags=["history"])

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
#: A ceiling per month and kind, not a page: ten feeds a day for 31 days is 310.
MONTH_CAP = 2000
#: What a document row shows (components/document-card): a title, an icon, a
#: status. Its text stays on its own page; a month of transcripts weighs MBs.
DOCUMENT_FIELDS = {"id", "source", "mime_type", "file_name", "created_at", "status",
                   "diary_date"}


def _month_of(column):
    """'YYYY-MM' of a timestamptz column, read in Madrid."""
    return sa.func.to_char(sa.func.timezone(LOCAL_TZ.key, column), "YYYY-MM")


def _bounds(month: str) -> tuple[datetime, datetime]:
    year, mon = int(month[:4]), int(month[5:])
    start = datetime(year, mon, 1, tzinfo=LOCAL_TZ)
    end = datetime(year + mon // 12, mon % 12 + 1, 1, tzinfo=LOCAL_TZ)
    return start, end


@router.get("")
async def history(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    profile_id: uuid.UUID | None = None,
    month: Annotated[str | None, Query(pattern=MONTH_PATTERN)] = None,
    locale: str = "es",
):
    async with AsyncSessionLocal() as session:
        facts = await get_profile_facts(session, user_id=user_id, profile_id=profile_id)
        if profile_id is not None and facts.profile_id is None:
            return {"profile_id": None, "name": None, "month": month, "months": [], "days": []}
        scope = Scope(user_id=user_id, profile_id=facts.profile_id)
        documents = (*scope.where(Document), Document.deleted_at.is_(None))
        noted = await session.scalars(
            sa.select(_month_of(Observation.observed_at))
            .where(*scope.where(Observation)).distinct()
        )
        filed = await session.scalars(
            sa.select(_month_of(Document.created_at)).where(*documents).distinct()
        )
        months = sorted(set(noted) | set(filed), reverse=True)
        shown = month or (months[0] if months else datetime.now(LOCAL_TZ).strftime("%Y-%m"))
        start, end = _bounds(shown)
        notes = (await session.scalars(
            sa.select(Observation)
            .where(*scope.where(Observation),
                   Observation.observed_at >= start, Observation.observed_at < end)
            .order_by(Observation.observed_at.desc(), Observation.created_at.desc())
            .limit(MONTH_CAP)
        )).all()
        docs = (await session.scalars(
            sa.select(Document)
            .where(*documents, Document.created_at >= start, Document.created_at < end)
            .order_by(Document.created_at.desc())
            .limit(MONTH_CAP)
        )).all()

    days: dict[str, dict] = {}

    def day_of(at: datetime) -> dict:
        key = at.astimezone(LOCAL_TZ).date().isoformat()
        return days.setdefault(key, {"day": key, "notes": [], "documents": []})

    # A note she gave an hour reads with it; a day she named without one ("a los
    # 2 meses pesó 5,1") reads without, after the day's timed ones: its 12:00 is
    # where it is stored, not when it happened.
    for row in sorted(notes, key=lambda r: not r.timed):
        local = row.observed_at.astimezone(LOCAL_TZ)
        day_of(local)["notes"].append({
            "id": str(row.id),
            "kind": row.kind,
            "time": local.strftime("%H:%M") if row.timed else None,
            "text": record.entry_text(record.as_draft(row), locale=locale),
        })
    for doc in docs:
        out = _doc_to_out(doc).model_dump(mode="json", include=DOCUMENT_FIELDS)
        day_of(doc.created_at)["documents"].append(out)

    return {
        "profile_id": str(facts.profile_id) if facts.profile_id else None,
        "name": facts.display_name,
        "month": shown,
        "months": months,
        "days": [days[key] for key in sorted(days, reverse=True)],
    }
