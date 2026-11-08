"""Consented visitor journeys, kept in our own database (decision of 2026-11-07).

Santiago chose the full journey of each visitor, with a consent banner, over
the anonymous counters alone ("guarda lo de quien nos visita, dónde hacen clic,
todo"), and the social media plan needs to know which post brings each visitor
and how far she gets. AdelIA holds health data, so this is not a third-party
script: the browser batches its events to our API and they stay in Postgres.

What makes it safe to keep is decided here, on the server, whatever the
browser sends:

* Nothing is stored unless the latest answer recorded for the browser's
  consent id is "accepted". The banner is the first gate (apps/web
  lib/analytics.ts sends nothing before it); this is the second, so a client
  bug, a stale tab or a forged batch cannot measure someone who said no. The
  GPC header (Sec-GPC: 1) is a refusal too, and bots are not visitors.
* The vocabulary is closed. A batch can only say: a page was viewed, an
  element was pressed, the page was scrolled to 25/50/75/100 %, or a funnel
  step happened. Every field is cut to an allowlisted shape (a path without
  its query, a domain without its URL, a stable element name) and anything
  else in the payload is ignored, so a question typed by a mother has no
  column to land in. tests/test_analytics.py plants one in every field.
* The identifiers are random UUIDs drawn by the browser after she accepts.
  They are not, and cannot be joined to, an account, a guest, an email or an
  IP. The IP is read for the rate limit and, through Cloudflare's header, for
  the country; it is never written.

`funnel_counters` (services/funnel.py, audit 4.8) stays as it is: it counts
every visitor, consenting or not, without storing anything about anybody, and
the demo's daily budget reads it. This module is the consented sample on top.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from adelia import qa_traffic
from adelia.auth import admin_emails
from adelia.db import AsyncSessionLocal, engine
from adelia.models import AnalyticsConsent, AnalyticsEvent, AnalyticsSession

logger = logging.getLogger(__name__)

EVENT_TYPES = ("pageview", "click", "scroll", "step")

#: The funnel, in the order the summary reads it. Two paths share it: the
#: landing's guest (landing_view .. account_saved) and the classic signup
#: (signup .. payment). Each name is emitted by one place in apps/web.
FUNNEL_STEPS = (
    "landing_view",
    "first_interaction",
    "guest_created",
    "question_sent",
    "answer_shown",
    "follow_up",
    "recording_started",
    "recording_finished",
    "save_requested",
    "account_saved",
    "signup",
    "trial_started",
    "payment",
)
CHOICES = ("accepted", "rejected", "withdrawn")
CONSENT_SOURCES = ("banner", "settings", "privacy")
SCROLL_DEPTHS = (25, 50, 75, 100)

MAX_BATCH_EVENTS = 50
MAX_BODY_BYTES = 64_000
MAX_PATH_CHARS = 160
MAX_ELEMENT_CHARS = 64
MAX_UTM_CHARS = 100
RECENT_SESSIONS = 20
MAX_TIMELINE_EVENTS = 200

#: 13 months, the longest the AEPD and the CNIL accept for audience
#: measurement data, counted in days so the purge is one comparison.
EVENT_RETENTION_DAYS = 396
#: The proof of a consent has to outlive the consent itself (the browser asks
#: again after 13 months, EVENT_RETENTION_DAYS) by the time in which the
#: processing could be challenged: 3 years, the prescription of a very serious
#: infraction under LOPDGDD art. 72 and LSSI art. 45. Draft for Santiago's
#: review, with the /privacidad text that states it.
CONSENT_PROOF_RETENTION_DAYS = EVENT_RETENTION_DAYS + 3 * 365 + 1

#: A client clock further off than this is ignored for the server's.
_CLOCK_PAST = timedelta(days=1)
_CLOCK_FUTURE = timedelta(minutes=2)

_BOT_UA = re.compile(
    r"bot|crawl|spider|slurp|headless|lighthouse|preview|facebookexternalhit|embedly|"
    r"curl|wget|python-|httpx|aiohttp|axios|node-fetch|go-http|java/|okhttp|scrapy|"
    r"phantomjs|puppeteer|playwright|selenium|pingdom|uptime|monitor",
    re.IGNORECASE,
)
_UUID_SEGMENT = re.compile(
    r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$", re.IGNORECASE
)
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]{1,40}$")
_ID_LIKE_SEGMENT = re.compile(r"^(\d+|[0-9a-f]{16,}|[A-Za-z0-9_-]{24,})$", re.IGNORECASE)
_HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8}){0,3}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_LOCALES = ("es", "en", "fr")

ANALYTICS_TABLES = (AnalyticsConsent.__table__, AnalyticsSession.__table__,
                    AnalyticsEvent.__table__)


# ---------------------------------------------------------------- admin list

def parse_admin_emails(raw: str | None) -> set[str]:
    return {e.strip().lower() for e in (raw or "").split(",") if e.strip()}


def is_admin(email: str | None) -> bool:
    """True when `email` is an admin by the one rule of auth.admin_emails
    (ADMIN_EMAILS plus OWNER_EMAIL). An empty list admits nobody."""
    value = (email or "").strip().lower()
    return bool(value) and value in admin_emails()


async def ensure_tables() -> None:
    """Create the three tables if they are missing, without touching
    alembic_version. For tests and the shared dev database only, where other
    branches stamp their own revisions; everywhere else `alembic upgrade head`
    creates them (0027_analytics) and this finds them already there."""
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: AnalyticsSession.metadata.create_all(c, tables=list(ANALYTICS_TABLES))
        )


# ---------------------------------------------------------------- cleaning

def is_bot(user_agent: str | None) -> bool:
    ua = (user_agent or "").strip()
    return not ua or bool(_BOT_UA.search(ua))


def device_from_ua(user_agent: str | None) -> str:
    """mobile | tablet | desktop. The user agent is read here and dropped."""
    ua = user_agent or ""
    if re.search(r"iPad|Tablet|PlayBook|Silk", ua) or (
        "Android" in ua and "Mobile" not in ua
    ):
        return "tablet"
    if re.search(r"Mobi|iPhone|iPod|Android|Windows Phone", ua):
        return "mobile"
    return "desktop"


def clean_path(value: Any) -> str | None:
    """A path without query or fragment, with identifiers masked.

    The query is where a question could ride (the landing's ?ask=q.<text>
    fallback, lib/landing-question.ts), so it never survives. A segment that
    looks like an id becomes ":id"; one with characters a route of ours never
    has (percent-encoded text, spaces) becomes ":x".
    """
    if not isinstance(value, str):
        return None
    raw = value.split("?", 1)[0].split("#", 1)[0].strip()
    if not raw.startswith("/"):
        return None
    segments = []
    for segment in raw.split("/")[1:]:
        if not segment:
            continue
        if _UUID_SEGMENT.match(segment) or _ID_LIKE_SEGMENT.match(segment):
            segments.append(":id")
        elif _SAFE_SEGMENT.match(segment):
            segments.append(segment)
        else:
            segments.append(":x")
    path = "/" + "/".join(segments)
    return path[:MAX_PATH_CHARS]


def clean_domain(value: Any) -> str | None:
    """The referring host and nothing else: a full URL (a post, a search)
    arrives as its domain."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().lower()
    host = urlsplit(raw).hostname if "://" in raw else re.split(r"[/?#:]", raw, 1)[0]
    if not host or len(host) > 100 or not _HOSTNAME.match(host):
        return None
    return host


def clean_label(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(_CONTROL.sub(" ", value).split())
    return text[:limit] or None


def clean_lang(value: Any) -> str | None:
    if isinstance(value, str) and _LANG.match(value.strip()):
        return value.strip()[:16]
    return None


def clean_int(value: Any, low: int, high: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = int(value)
    return number if low <= number <= high else None


def clean_country(value: str | None) -> str | None:
    code = (value or "").strip().upper()
    if not _COUNTRY.match(code) or code in ("XX", "T1"):
        return None
    return code


def clean_depth(value: Any) -> int | None:
    number = clean_int(value, 0, 10_000)
    if number is None or number <= 0:
        return None
    capped = min(number, 100)
    # Round down to the band the client reports, so a value of 63 reads 50.
    return max((d for d in SCROLL_DEPTHS if d <= capped), default=None)


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _when(value: Any, now: datetime) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            at = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return now
        if now - _CLOCK_PAST <= at <= now + _CLOCK_FUTURE:
            return at
    return now


def clean_event(raw: Any, now: datetime) -> dict | None:
    """One event of the closed vocabulary, or None. Unknown keys are dropped
    by construction: only the fields read below can reach a row."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("type")
    path = clean_path(raw.get("path"))
    if kind not in EVENT_TYPES or path is None:
        return None
    event = {"type": kind, "path": path, "occurred_at": _when(raw.get("ts"), now),
             "element": None, "depth": None, "step": None}
    if kind == "click":
        event["element"] = clean_label(raw.get("element"), MAX_ELEMENT_CHARS)
    elif kind == "scroll":
        event["depth"] = clean_depth(raw.get("depth"))
        if event["depth"] is None:
            return None
    elif kind == "step":
        if raw.get("step") not in FUNNEL_STEPS:
            return None
        event["step"] = raw["step"]
    return event


def parse_body(body: bytes) -> dict | None:
    """sendBeacon posts a string as text/plain (no CORS preflight), so the
    body is read as JSON whatever its content type."""
    if not body or len(body) > MAX_BODY_BYTES:
        return None
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- writing

async def latest_choice(db, consent_id: uuid.UUID) -> str | None:
    return await db.scalar(
        sa.select(AnalyticsConsent.choice)
        .where(AnalyticsConsent.consent_id == consent_id)
        .order_by(AnalyticsConsent.created_at.desc(), AnalyticsConsent.id.desc())
        .limit(1)
    )


async def record_consent(
    *, consent_id: uuid.UUID, choice: str, version: str, source: str,
    forget_visitor: uuid.UUID | None = None,
) -> None:
    """Append the proof of an answer. A withdrawal that names the browser's
    visitor id also deletes what that browser sent under this consent: she
    asked us to stop, and keeping her journey would serve nobody but us.

    Test traffic stores no proof (adelia/qa_traffic.py): nobody consented to
    anything, and its answers would skew the banner's acceptance rate."""
    if qa_traffic.is_qa():
        return
    async with AsyncSessionLocal() as db:
        db.add(AnalyticsConsent(consent_id=consent_id, choice=choice, version=version,
                                source=source))
        if choice == "withdrawn" and forget_visitor is not None:
            await db.execute(
                sa.delete(AnalyticsSession).where(
                    AnalyticsSession.visitor_id == forget_visitor,
                    AnalyticsSession.consent_id == consent_id,
                )
            )
        await db.commit()


async def ingest(
    payload: dict, *, user_agent: str | None, gpc: bool, country: str | None,
    now: datetime | None = None,
) -> int:
    """Store one batch if, and only if, it may be stored. Returns the number of
    events written; every refusal is a quiet 0. Test traffic is one of them
    (adelia/qa_traffic.py)."""
    if gpc or is_bot(user_agent) or qa_traffic.is_qa():
        return 0
    consent_id = _uuid(payload.get("consent_id"))
    visitor_id = _uuid(payload.get("visitor_id"))
    session_id = _uuid(payload.get("session_id"))
    if consent_id is None or visitor_id is None or session_id is None:
        return 0
    now = now or datetime.now(timezone.utc)
    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        return 0
    events = [e for e in (clean_event(r, now) for r in raw_events[:MAX_BATCH_EVENTS]) if e]
    if not events:
        return 0
    ctx = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    first = min(e["occurred_at"] for e in events)
    last = max(e["occurred_at"] for e in events)
    locale = ctx.get("locale") if ctx.get("locale") in _LOCALES else None

    async with AsyncSessionLocal() as db:
        if await latest_choice(db, consent_id) != "accepted":
            return 0
        stmt = (
            pg_insert(AnalyticsSession)
            .values(
                session_id=session_id, visitor_id=visitor_id, consent_id=consent_id,
                started_at=first, last_seen_at=last,
                landing_path=clean_path(ctx.get("landing_path")),
                referrer_domain=clean_domain(ctx.get("referrer")),
                utm_source=clean_label(ctx.get("utm_source"), MAX_UTM_CHARS),
                utm_medium=clean_label(ctx.get("utm_medium"), MAX_UTM_CHARS),
                utm_campaign=clean_label(ctx.get("utm_campaign"), MAX_UTM_CHARS),
                utm_content=clean_label(ctx.get("utm_content"), MAX_UTM_CHARS),
                utm_term=clean_label(ctx.get("utm_term"), MAX_UTM_CHARS),
                device=device_from_ua(user_agent),
                screen_w=clean_int(ctx.get("screen_w"), 1, 10_000),
                screen_h=clean_int(ctx.get("screen_h"), 1, 10_000),
                lang=clean_lang(ctx.get("lang")),
                locale=locale,
                country=country,
            )
            # Where the visit came from is decided by its first batch. A later
            # batch only moves the clock, and only for the same visitor under
            # the same consent: a forged batch cannot take over a session.
            .on_conflict_do_update(
                index_elements=[AnalyticsSession.session_id],
                set_={
                    "last_seen_at": sa.func.greatest(
                        AnalyticsSession.last_seen_at, sa.literal(last)
                    ),
                    "started_at": sa.func.least(AnalyticsSession.started_at, sa.literal(first)),
                },
                where=sa.and_(
                    AnalyticsSession.visitor_id == visitor_id,
                    AnalyticsSession.consent_id == consent_id,
                ),
            )
            .returning(AnalyticsSession.session_id)
        )
        if await db.scalar(stmt) is None:
            return 0
        db.add_all(AnalyticsEvent(session_id=session_id, **e) for e in events)
        await db.commit()
    return len(events)


# ---------------------------------------------------------------- retention

async def purge_expired(*, now: datetime | None = None) -> dict[str, int]:
    """Delete journeys older than 13 months and proofs past their period.

    Called at boot and then daily (main._periodic_analytics_purge). Events go
    by their own date as well as with their session, so a visit that somehow
    straddles the cut cannot keep an old step alive.
    """
    now = now or datetime.now(timezone.utc)
    events_cut = now - timedelta(days=EVENT_RETENTION_DAYS)
    proofs_cut = now - timedelta(days=CONSENT_PROOF_RETENTION_DAYS)
    async with AsyncSessionLocal() as db:
        events = await db.execute(
            sa.delete(AnalyticsEvent).where(AnalyticsEvent.occurred_at < events_cut)
        )
        sessions = await db.execute(
            sa.delete(AnalyticsSession).where(AnalyticsSession.last_seen_at < events_cut)
        )
        consents = await db.execute(
            sa.delete(AnalyticsConsent).where(AnalyticsConsent.created_at < proofs_cut)
        )
        await db.commit()
    return {"events": events.rowcount or 0, "sessions": sessions.rowcount or 0,
            "consents": consents.rowcount or 0}


# ---------------------------------------------------------------- reading

def _utc_day(column):
    return sa.cast(sa.func.timezone("UTC", column), sa.Date)


def _rate(n: int, base: int) -> float | None:
    return round(n / base, 4) if base else None


async def summary(days: int = 30, *, today: date | None = None) -> dict[str, Any]:
    """Everything the admin page draws, as JSON (also for a local backoffice).

    Visitors are counted by their random visitor id, so one mother on two
    days is one visitor in the funnel and one per day in the daily rows.
    """
    from adelia.services import funnel

    days = max(1, min(days, funnel.MAX_SUMMARY_DAYS))
    end = today or datetime.now(timezone.utc).date()
    start_day = end - timedelta(days=days - 1)
    since = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)
    S, E, C = AnalyticsSession, AnalyticsEvent, AnalyticsConsent

    async with AsyncSessionLocal() as db:
        session_day = _utc_day(S.started_at)
        daily_sessions = (await db.execute(
            sa.select(session_day, sa.func.count(), sa.func.count(sa.distinct(S.visitor_id)))
            .where(S.started_at >= since).group_by(session_day)
        )).all()
        event_day = _utc_day(E.occurred_at)
        daily_views = (await db.execute(
            sa.select(event_day, sa.func.count())
            .where(E.occurred_at >= since, E.type == "pageview").group_by(event_day)
        )).all()
        step_rows = (await db.execute(
            sa.select(E.step, sa.func.count(sa.distinct(S.visitor_id)),
                      sa.func.count(sa.distinct(S.session_id)))
            .join(S, S.session_id == E.session_id)
            .where(E.occurred_at >= since, E.type == "step").group_by(E.step)
        )).all()
        referrers = (await db.execute(
            sa.select(S.referrer_domain, sa.func.count(), sa.func.count(sa.distinct(S.visitor_id)))
            .where(S.started_at >= since).group_by(S.referrer_domain)
            .order_by(sa.func.count().desc()).limit(30)
        )).all()
        utm_key = (S.utm_source, S.utm_medium, S.utm_campaign, S.utm_content)
        has_utm = sa.or_(*(c.is_not(None) for c in utm_key))
        utm_rows = (await db.execute(
            sa.select(*utm_key, sa.func.count(), sa.func.count(sa.distinct(S.visitor_id)))
            .where(S.started_at >= since, has_utm).group_by(*utm_key)
            .order_by(sa.func.count().desc()).limit(50)
        )).all()
        utm_steps = (await db.execute(
            sa.select(*utm_key, E.step, sa.func.count(sa.distinct(S.session_id)))
            .join(E, E.session_id == S.session_id)
            .where(S.started_at >= since, has_utm, E.type == "step")
            .group_by(*utm_key, E.step)
        )).all()
        clicks = (await db.execute(
            sa.select(E.path, E.element, sa.func.count())
            .where(E.occurred_at >= since, E.type == "click")
            .group_by(E.path, E.element)
            .order_by(E.path, sa.func.count().desc()).limit(300)
        )).all()
        recent = (await db.execute(
            sa.select(S).where(S.started_at >= since)
            .order_by(S.started_at.desc()).limit(RECENT_SESSIONS)
        )).scalars().all()
        timeline_rows = []
        if recent:
            timeline_rows = (await db.execute(
                sa.select(E.session_id, E.occurred_at, E.type, E.path, E.element, E.depth, E.step)
                .where(E.session_id.in_([s.session_id for s in recent]))
                .order_by(E.session_id, E.occurred_at, E.id)
            )).all()
        period_visitors = await db.scalar(
            sa.select(sa.func.count(sa.distinct(S.visitor_id))).where(S.started_at >= since)
        )
        consent_rows = (await db.execute(
            sa.select(C.choice, sa.func.count()).where(C.created_at >= since).group_by(C.choice)
        )).all()

    counters = await funnel.summary(days, today=end)
    # The /r/<code> clicks of the social networks, counted for everyone.
    links = await funnel.link_clicks(days, today=end)

    by_day_sessions = {d: (int(n), int(v)) for d, n, v in daily_sessions}
    by_day_views = {d: int(n) for d, n in daily_views}
    daily = []
    for offset in range(days):
        d = end - timedelta(days=offset)
        sessions_n, visitors_n = by_day_sessions.get(d, (0, 0))
        daily.append({"day": d.isoformat(), "visitors": visitors_n, "sessions": sessions_n,
                      "pageviews": by_day_views.get(d, 0)})

    steps = {step: (int(v), int(s)) for step, v, s in step_rows}
    funnel_rows = []
    first_n = steps.get(FUNNEL_STEPS[0], (0, 0))[0]
    previous = None
    for step in FUNNEL_STEPS:
        visitors_n, sessions_n = steps.get(step, (0, 0))
        funnel_rows.append({
            "step": step, "visitors": visitors_n, "sessions": sessions_n,
            "rate_from_previous": None if previous is None else _rate(visitors_n, previous),
            "rate_from_first": _rate(visitors_n, first_n),
        })
        previous = visitors_n

    reached: dict[tuple, dict[str, int]] = {}
    for *key, step, n in utm_steps:
        if step in FUNNEL_STEPS:
            reached.setdefault(tuple(key), {})[step] = int(n)
    utm = []
    for source, medium, campaign, content, n, visitors_n in utm_rows:
        got = reached.get((source, medium, campaign, content), {})
        deepest = next((s for s in reversed(FUNNEL_STEPS) if got.get(s)), None)
        utm.append({"source": source, "medium": medium, "campaign": campaign,
                    "content": content, "sessions": int(n), "visitors": int(visitors_n),
                    "steps": {s: got.get(s, 0) for s in FUNNEL_STEPS}, "deepest": deepest})

    timelines: dict[uuid.UUID, list[dict]] = {}
    for sid, at, kind, path, element, depth, step in timeline_rows:
        items = timelines.setdefault(sid, [])
        if len(items) < MAX_TIMELINE_EVENTS:
            items.append({"at": at.isoformat(), "type": kind, "path": path,
                          "element": element, "depth": depth, "step": step})
    recent_sessions = [{
        # A short handle to tell rows apart on screen; the visitor id is
        # never sent to the page.
        "session": str(s.session_id)[:8],
        "started_at": s.started_at.isoformat(), "last_seen_at": s.last_seen_at.isoformat(),
        "landing_path": s.landing_path, "referrer_domain": s.referrer_domain,
        "utm_source": s.utm_source, "utm_medium": s.utm_medium,
        "utm_campaign": s.utm_campaign, "utm_content": s.utm_content,
        "device": s.device, "screen_w": s.screen_w, "screen_h": s.screen_h,
        "locale": s.locale, "lang": s.lang, "country": s.country,
        "events": timelines.get(s.session_id, []),
    } for s in recent]

    consent = {choice: 0 for choice in CHOICES}
    consent.update({choice: int(n) for choice, n in consent_rows})

    return {
        "days": days,
        "from": start_day.isoformat(),
        "to": end.isoformat(),
        "totals": {
            # Distinct over the period: the daily rows count a returning
            # visitor once per day, so their sum would count her twice.
            "visitors": int(period_visitors or 0),
            "sessions": sum(r["sessions"] for r in daily),
            "pageviews": sum(r["pageviews"] for r in daily),
        },
        "daily": daily,
        "funnel": funnel_rows,
        "sources": {
            "referrers": [{"domain": d, "sessions": int(n), "visitors": int(v)}
                          for d, n, v in referrers],
            "utm": utm,
        },
        "clicks": [{"path": p, "element": el, "clicks": int(n)} for p, el, n in clicks],
        "recent_sessions": recent_sessions,
        "consent": consent,
        "counters": counters,
        "links": links,
    }
