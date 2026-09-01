"""The funnel, measured without tracking anybody (audit 4.8).

Four numbers per day, which is the smallest set that can tell "nobody arrives"
apart from "they arrive and leave at the card":

    visit       a public page was rendered in a browser
    start       "Empezar" was pressed on the landing
    signup      an account row appeared
    activation  that account got past the baby screen and into the panel

The first two are counted; the last two are derived. That split is the whole
privacy design:

* `bump()` writes to `funnel_counters`, a table of (date, event, integer). No
  IP, no user agent, no session, no referrer, no cookie, nothing that could be
  joined back to a person. The browser call that triggers it sends
  `credentials: "omit"` so not even the session cookie reaches the server
  (apps/web/components/funnel.tsx).
* `summary()` reads signups and activations straight off `users.created_at`
  and `users.onboarded_at` with a GROUP BY. Counting them a second time in
  `funnel_counters` would add a write, a drift risk and no information.

This is aggregate from the first line: there is no raw event table to
aggregate later, and no version of this module can answer "did SHE visit?".
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from adelia.db import AsyncSessionLocal
from adelia.models import FunnelCounter, User

logger = logging.getLogger(__name__)

# The only event names that may be written. An open string column plus a
# public endpoint is an invitation to fill the table with junk (or with a
# 40 KB "event name" carrying whatever the caller wants to log about a
# visitor), so the allowlist is the validation.
COUNTED_EVENTS = ("visit", "start", "demo_ask")

# Derived at read time, never written. Kept here so the API contract lists
# the four columns of the funnel in one place.
DERIVED_EVENTS = ("signup", "activation")

MAX_SUMMARY_DAYS = 365


def utc_today() -> date:
    """The day a row belongs to, in UTC, everywhere in this module.

    It has to be one clock. The counters are stamped by Python and the
    signups/activations are grouped by Postgres, and if the two disagree the
    funnel silently splits a single evening across two rows: measured on this
    machine at 01:58 local (23:58 UTC), a visit landed on 2026-09-01 and the
    account it created landed on 2026-08-31. UTC rather than the server's
    local zone because it is the one clock a Docker container, a laptop and a
    Postgres session all already agree on.
    """
    return datetime.now(timezone.utc).date()


def _utc_date(column):
    """`column`, a timestamptz, as its UTC calendar date.

    `date(ts)` alone converts in the session's TimeZone setting, which is
    whatever the connection happens to carry.
    """
    return sa.cast(sa.func.timezone("UTC", column), sa.Date)


async def bump(event: str, *, day: date | None = None) -> int:
    """Add 1 to today's counter for `event`; return the new value.

    Atomic upsert: concurrent visitors race on the same (day, event) row and
    `count = funnel_counters.count + 1` is evaluated by Postgres, so no read-
    modify-write in Python can lose a count.

    Returns the post-increment value so a caller can also use it as a daily
    budget (routers/demo does exactly that with "demo_ask").
    """
    if event not in COUNTED_EVENTS:
        raise ValueError(f"unknown funnel event: {event!r}")
    today = day or utc_today()
    stmt = (
        pg_insert(FunnelCounter)
        .values(day=today, event=event, count=1)
        .on_conflict_do_update(
            index_elements=[FunnelCounter.day, FunnelCounter.event],
            set_={"count": FunnelCounter.count + 1},
        )
        .returning(FunnelCounter.count)
    )
    async with AsyncSessionLocal() as session:
        value = await session.scalar(stmt)
        await session.commit()
    return int(value or 0)


async def bump_quietly(event: str) -> None:
    """`bump` that can never break the request it rides along with.

    A counter is not worth a 500 on a landing page or a failed demo answer,
    so the exception is logged and swallowed.
    """
    try:
        await bump(event)
    except Exception:  # noqa: BLE001 — a missed count is not an incident
        logger.warning("funnel: could not record %r", event, exc_info=True)


async def summary(days: int = 30, *, today: date | None = None) -> list[dict]:
    """One row per day, newest first, with the four funnel numbers.

    Days with no activity at all are present with zeros: a gap in a funnel
    table reads as "we lost the data" and this way it reads as "nobody came".
    """
    days = max(1, min(days, MAX_SUMMARY_DAYS))
    end = today or utc_today()
    start = end - timedelta(days=days - 1)

    async with AsyncSessionLocal() as session:
        counter_rows = (
            await session.execute(
                sa.select(FunnelCounter.day, FunnelCounter.event, FunnelCounter.count)
                .where(FunnelCounter.day >= start, FunnelCounter.day <= end)
            )
        ).all()
        created_day = _utc_date(User.created_at)
        signup_rows = (
            await session.execute(
                sa.select(created_day.label("day"), sa.func.count().label("n"))
                .where(created_day >= start)
                .where(created_day <= end)
                .group_by(created_day)
            )
        ).all()
        onboarded_day = _utc_date(User.onboarded_at)
        activation_rows = (
            await session.execute(
                sa.select(onboarded_day.label("day"), sa.func.count().label("n"))
                .where(User.onboarded_at.is_not(None))
                .where(onboarded_day >= start)
                .where(onboarded_day <= end)
                .group_by(onboarded_day)
            )
        ).all()

    counted: dict[date, dict[str, int]] = {}
    for row_day, event, count in counter_rows:
        counted.setdefault(row_day, {})[event] = int(count)
    signups = {row_day: int(n) for row_day, n in signup_rows}
    activations = {row_day: int(n) for row_day, n in activation_rows}

    out: list[dict] = []
    for offset in range(days):
        d = end - timedelta(days=offset)
        row = counted.get(d, {})
        out.append(
            {
                "day": d.isoformat(),
                "visit": row.get("visit", 0),
                "start": row.get("start", 0),
                "signup": signups.get(d, 0),
                "activation": activations.get(d, 0),
                "demo_ask": row.get("demo_ask", 0),
            }
        )
    return out
