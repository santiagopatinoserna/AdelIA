"""What is due today with this child, for the home card (vision note 2026-10-22).

A mother wants to feel accompanied: one glance at the home screen answers
"what is due today, what must I not forget". The card is read-only and
computed here from three sources, nothing invented and nothing phrased as
advice:

1. Vaccines overdue or due within a month, from the country calendar
   (`agent/pediatrics`) against the child's age, her vaccination card
   (`immunization` entities) and the doses she noted in the chat
   (`observations` of kind `vaccine`).
2. The latest observation of today or yesterday, with the previous
   comparable reading ("ayer 37,2 °C, hoy 37,8 °C").
3. The "No olvides" line of the last plan the chat stored in the last 7 days.

Every read is scoped (`services/scope`): a mother of two never sees Adel's
temperature under "Hoy con Nora". `chat_messages` carry no profile, so the
plan line is only shown when the account has a single child; with two it
cannot be attributed and is skipped rather than guessed.

Nothing applies: `items` is empty and the web renders no card. No empty
state and no filler, by design.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

# record's label, number and clock helpers: the card must read exactly like
# the line the record node answered with when she noted the value.
from adelia.agent import record
from adelia.agent.pediatrics import VaccineStatus, resolve_country, vaccine_status
from adelia.db import AsyncSessionLocal
from adelia.enrichment.profile_service import age_in_months, get_profile_facts
from adelia.models import ChatMessage, Entity, Observation, Profile
from adelia.services.answer_contract import PLAN_HEADINGS
from adelia.services.observations import previous_comparable
from adelia.services.scope import Scope

#: "Due soon" on the home card is one month, not the tool's two: the card
#: answers "today", and a dose six weeks away is noise next to a temperature.
DUE_WINDOW_MONTHS = 1

_LANG = ("es", "en", "fr")

_VACCINE_DUE = {
    "es": "Le toca pronto: {names}.",
    "en": "Due soon: {names}.",
    "fr": "Bientôt à faire : {names}.",
}
_VACCINE_OVERDUE = {
    "es": "Sin anotar y ya tocaba: {names}. Si está puesta, dímelo y lo apunto.",
    "en": "Not noted and already due: {names}. If it was given, tell me and I will note it.",
    "fr": "Pas notée et déjà due : {names}. Si elle est faite, dites-le-moi et je la note.",
}
_AT_MONTHS = {"es": "a los {m} meses", "en": "at {m} months", "fr": "à {m} mois"}


def _lang(locale: str) -> str:
    return locale if locale in _LANG else "es"


async def _administered(session: AsyncSession, scope: Scope) -> list[str]:
    """Every dose the record shows: her card's entities and the ones she noted."""
    entities = await session.scalars(
        sa.select(Entity.name)
        .where(*scope.where(Entity), Entity.entity_type == "immunization",
               Entity.deleted_at.is_(None))
        .limit(200)
    )
    noted = await session.scalars(
        sa.select(Observation.text)
        .where(*scope.where(Observation), Observation.kind == "vaccine")
        .limit(200)
    )
    return [*entities, *noted]


def _vaccine_item(statuses: list[VaccineStatus], age_months: int, lang: str) -> dict | None:
    soon = [s for s in statuses if s.overdue or s.due_month <= age_months + DUE_WINDOW_MONTHS]
    if not soon:
        return None
    late = [s for s in soon if s.overdue]
    shown = late or soon
    names = ", ".join(f"{s.name} ({_AT_MONTHS[lang].format(m=s.due_month)})" for s in shown)
    template = _VACCINE_OVERDUE if late else _VACCINE_DUE
    return {"kind": "vaccine", "text": template[lang].format(names=names),
            "tone": "warn" if late else "neutral"}


async def _latest_reading(session: AsyncSession, scope: Scope, now: datetime) -> Observation | None:
    """The newest observation with a value, noted today or yesterday (in `now`'s zone)."""
    start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return await session.scalar(
        sa.select(Observation)
        .where(*scope.where(Observation), Observation.value.is_not(None),
               Observation.observed_at >= start)
        .order_by(Observation.observed_at.desc())
        .limit(1)
    )


_DAY = {
    "es": {0: "hoy", 1: "ayer", "on": "el", "at": "a las"},
    "en": {0: "today", 1: "yesterday", "on": "on", "at": "at"},
    "fr": {0: "aujourd’hui", 1: "hier", "on": "le", "at": "à"},
}


def _day_word(at: datetime, now: datetime, lang: str, *, with_time: bool) -> str:
    """"ayer", "hoy", "el 17/10", and the clock when two readings share a day."""
    local = at.astimezone(now.tzinfo)
    days = (now.date() - local.date()).days
    word = _DAY[lang].get(days) or f"{_DAY[lang]['on']} {local.day:02d}/{local.month:02d}"
    return f"{word} {_DAY[lang]['at']} {record._clock(local, lang)}" if with_time else word


def _observation_item(latest: Observation, previous: Observation | None, lang: str,
                      now: datetime) -> dict:
    """"Temperatura: ayer 37,2 °C, hoy 37,8 °C." Same words the record node answers with."""
    last = record.as_draft(latest)
    same_day = (previous is not None
                and previous.observed_at.astimezone(now.tzinfo).date()
                == latest.observed_at.astimezone(now.tzinfo).date())
    parts = []
    if previous is not None and previous.unit == latest.unit:
        prev = record.as_draft(previous)
        parts.append(f"{_day_word(prev.observed_at, now, lang, with_time=same_day)} "
                     f"{record._value_text(prev, lang)}")
    parts.append(f"{_day_word(last.observed_at, now, lang, with_time=same_day)} "
                 f"{record._value_text(last, lang)}")
    colon = " : " if lang == "fr" else ": "
    return {"kind": "observation", "tone": "neutral",
            "text": f"{record._KIND_LABEL[lang][last.kind]}{colon}{', '.join(parts)}."}


#: How far back the last plan counts as "the last plan". A line she read a
#: fortnight ago is not what she must not forget today.
PLAN_MAX_AGE = timedelta(days=7)
_CITATION = re.compile(r"\s*\[[^\]]*\]")
_HEADING = re.compile(r"^##\s+(.*?)\s*$", re.MULTILINE)


def remember_line(plan: str, lang: str) -> str | None:
    """The first bullet under the locale's "No olvides" heading, markers stripped.

    Same headings the plan contract writes (PLAN_HEADINGS), so the parser and
    the prompt cannot drift apart. The citation markers go: the card has no
    source list to point at, and "[ev_2]" on the home screen is noise.
    """
    heading = PLAN_HEADINGS[lang]["remember"]
    inside = False
    for line in plan.splitlines():
        if (m := _HEADING.match(line)) is not None:
            inside = m.group(1) == heading
            continue
        if inside and line.lstrip().startswith(("-", "*")):
            text = _CITATION.sub("", line.lstrip()[1:]).strip()
            if text:
                return text if text.endswith((".", "!", "?")) else text + "."
    return None


async def _last_plan_line(session: AsyncSession, user_id: UUID, lang: str,
                          now: datetime) -> str | None:
    """`chat_messages` carry no profile, so with two children the line is not attributable."""
    children = await session.scalar(
        sa.select(sa.func.count()).select_from(Profile)
        .where(Profile.user_id == user_id, Profile.relationship == "child",
               Profile.deleted_at.is_(None))
    )
    if (children or 0) > 1:
        return None
    heading = PLAN_HEADINGS[lang]["remember"]
    content = await session.scalar(
        sa.select(ChatMessage.content)
        .where(ChatMessage.user_id == user_id, ChatMessage.role == "assistant",
               ChatMessage.created_at >= now - PLAN_MAX_AGE,
               ChatMessage.content.contains(f"## {heading}"))
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    return remember_line(content, lang) if content else None


async def build_today(
    *, user_id: UUID, profile_id: UUID | None, locale: str, now: datetime
) -> dict:
    lang = _lang(locale)
    items: list[dict] = []
    async with AsyncSessionLocal() as session:
        facts = await get_profile_facts(session, user_id=user_id, profile_id=profile_id)
        if profile_id is not None and facts.profile_id is None:
            # Not her child (or deleted): an unknown profile must not widen the
            # read to her whole record, the fallback UNKNOWN_PROFILE would imply.
            return {"name": None, "items": []}
        scope = Scope(user_id=user_id, profile_id=facts.profile_id)
        age = age_in_months(facts.date_of_birth, today=now.date())
        if age is not None:
            statuses = vaccine_status(
                age_months=age, country=resolve_country(None, lang),
                administered=await _administered(session, scope),
            )
            if (item := _vaccine_item(statuses, age, lang)) is not None:
                items.append(item)
        latest = await _latest_reading(session, scope, now)
        if latest is not None:
            previous = await previous_comparable(
                session, scope=scope, kind=latest.kind, before=latest.observed_at
            )
            items.append(_observation_item(latest, previous, lang, now))
        if (line := await _last_plan_line(session, user_id, lang, now)) is not None:
            items.append({"kind": "remember", "text": line, "tone": "neutral"})
    return {"name": facts.display_name, "items": items}
