"""Consented visitor journeys (decision of Santiago, 2026-11-07).

What is under test, in order of importance:

1. Nothing is stored without an accepted consent: no consent id, an unknown
   one, a rejection, a withdrawal, the browser's GPC signal or a bot all end in
   zero rows. The banner is the first gate; this is the second.
2. With consent, a batch stores what the journey needs (random visitor and
   session ids, page, origin and UTM, element, scroll depth, funnel step,
   device, screen, language, country) and never anything typed: a question
   smuggled into any field of the payload is nowhere in the database.
3. Events go after 13 months and consent proofs after the period the law
   needs them for.
4. Only the admin list reads the summary; everyone else gets a 404.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import AnalyticsConsent, AnalyticsEvent, AnalyticsSession, User
from adelia.services import analytics

from tests.pg_gate import PG_AVAILABLE
from tests.test_auth import make_token

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

PHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
QUESTION = "Mi bebé de 4 meses tiene 38,5 de fiebre y vomita"


@pytest.fixture(autouse=True)
async def _schema():
    # The dev database is shared by branches that apply their own revisions,
    # so the tables are ensured here instead of stamping a revision on it. In
    # CI `alembic upgrade head` has created them and this is a no-op.
    await analytics.ensure_tables()
    yield
    # Leave the shared dev database as it was: these tables belong to this
    # feature alone, so wiping them after each case touches nobody else.
    async with AsyncSessionLocal() as db:
        await db.execute(sa.delete(AnalyticsSession))
        await db.execute(sa.delete(AnalyticsConsent))
        await db.commit()


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


async def _accept(client, consent_id: str | None = None) -> str:
    consent_id = consent_id or str(uuid.uuid4())
    res = await client.post(
        "/analytics/consent",
        json={"consent_id": consent_id, "choice": "accepted", "version": "2026-11-08",
              "source": "banner"},
    )
    assert res.status_code == 204
    return consent_id


def _batch(consent_id: str, *, session_id: str | None = None, visitor_id: str | None = None,
           events: list[dict] | None = None, **context) -> dict:
    ctx = {
        "locale": "es", "lang": "es-ES", "screen_w": 390, "screen_h": 844,
        "referrer": "www.tiktok.com", "landing_path": "/es",
        "utm_source": "tiktok", "utm_medium": "social", "utm_campaign": "lanzamiento",
        "utm_content": "video-3",
    }
    ctx.update(context)
    now = _now_ms()
    return {
        "consent_id": consent_id,
        "visitor_id": visitor_id or str(uuid.uuid4()),
        "session_id": session_id or str(uuid.uuid4()),
        "context": ctx,
        "events": events if events is not None else [
            {"ts": now - 4000, "type": "pageview", "path": "/es"},
            {"ts": now - 3000, "type": "step", "path": "/es", "step": "landing_view"},
            {"ts": now - 2000, "type": "click", "path": "/es", "element": "landing-ask"},
            {"ts": now - 1000, "type": "scroll", "path": "/es", "depth": 50},
            {"ts": now, "type": "step", "path": "/es/dashboard", "step": "question_sent"},
        ],
    }


async def _rows_for_session(session_id: str):
    sid = uuid.UUID(session_id)
    async with AsyncSessionLocal() as db:
        session = await db.get(AnalyticsSession, sid)
        events = (
            await db.execute(
                sa.select(AnalyticsEvent)
                .where(AnalyticsEvent.session_id == sid)
                .order_by(AnalyticsEvent.occurred_at, AnalyticsEvent.id)
            )
        ).scalars().all()
    return session, events


async def _collect(client, body, ua: str = PHONE_UA, **headers):
    return await client.post("/analytics/collect", json=body, headers={"user-agent": ua, **headers})


# ---------------------------------------------------------------- structure

def test_no_table_has_a_column_that_could_hold_a_person_or_her_words():
    forbidden = {"ip", "ip_address", "user_agent", "user_id", "guest_id", "email", "text",
                 "question", "answer", "note", "content", "body", "url", "query", "label_text"}
    for model in (AnalyticsSession, AnalyticsEvent, AnalyticsConsent):
        columns = set(model.__table__.columns.keys())
        assert not columns & forbidden, f"{model.__tablename__} has {columns & forbidden}"


def test_the_consent_proof_holds_version_date_and_choice_and_nothing_else():
    assert set(AnalyticsConsent.__table__.columns.keys()) == {
        "id", "consent_id", "choice", "version", "source", "created_at",
    }


#: Santiago's two addresses (decision of 2026-11-07). They live in the
#: production compose file, not in config.py: the repo is public and a
#: self-hosted install must not start with someone else as its admin.
SANTIAGO = {"santiagopatinoserna@gmail.com", "santiagopatinoserna@godi.ai"}
PROD_COMPOSE = Path(__file__).resolve().parents[3] / "infra" / "docker-compose.prod.yml"


def test_the_code_default_admin_list_is_empty():
    assert type(settings).model_fields["admin_emails"].default == ""
    assert type(settings).model_fields["owner_email"].default == ""


def test_production_defaults_admin_emails_to_santiagos_two_addresses():
    match = re.search(r"^\s*ADMIN_EMAILS: \$\{ADMIN_EMAILS:-([^}]*)\}\s*$",
                      PROD_COMPOSE.read_text(encoding="utf-8"), re.M)
    assert match, "infra/docker-compose.prod.yml does not pass ADMIN_EMAILS to the api"
    assert analytics.parse_admin_emails(match.group(1)) == SANTIAGO


# ---------------------------------------------------------------- consent gate

async def test_without_any_consent_nothing_is_stored(client):
    body = _batch(str(uuid.uuid4()))
    assert (await _collect(client, body)).status_code == 204
    session, events = await _rows_for_session(body["session_id"])
    assert session is None and events == []


async def test_after_a_rejection_nothing_is_stored(client):
    consent_id = str(uuid.uuid4())
    res = await client.post("/analytics/consent", json={
        "consent_id": consent_id, "choice": "rejected", "version": "2026-11-08",
        "source": "banner"})
    assert res.status_code == 204
    body = _batch(consent_id)
    assert (await _collect(client, body)).status_code == 204
    session, events = await _rows_for_session(body["session_id"])
    assert session is None and events == []


async def test_after_a_withdrawal_nothing_more_is_stored_and_the_past_is_forgotten(client):
    consent_id = await _accept(client)
    visitor = str(uuid.uuid4())
    first = _batch(consent_id, visitor_id=visitor)
    await _collect(client, first)
    assert (await _rows_for_session(first["session_id"]))[0] is not None

    res = await client.post("/analytics/consent", json={
        "consent_id": consent_id, "choice": "withdrawn", "version": "2026-11-08",
        "source": "settings", "forget_visitor": visitor})
    assert res.status_code == 204
    # What this browser sent before is gone with the withdrawal.
    assert (await _rows_for_session(first["session_id"]))[0] is None

    later = _batch(consent_id, visitor_id=visitor)
    await _collect(client, later)
    session, events = await _rows_for_session(later["session_id"])
    assert session is None and events == []


async def test_the_gpc_signal_is_a_rejection(client):
    consent_id = await _accept(client)
    body = _batch(consent_id)
    assert (await _collect(client, body, **{"sec-gpc": "1"})).status_code == 204
    session, events = await _rows_for_session(body["session_id"])
    assert session is None and events == []


@pytest.mark.parametrize("ua", [
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "facebookexternalhit/1.1",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 HeadlessChrome/131.0.0.0 Safari/537.36",
    "curl/8.7.1",
    "",
])
async def test_bots_are_not_visitors(client, ua):
    consent_id = await _accept(client)
    body = _batch(consent_id)
    assert (await _collect(client, body, ua=ua)).status_code == 204
    session, events = await _rows_for_session(body["session_id"])
    assert session is None and events == []


async def test_the_consent_proof_is_stored_without_anything_personal(client):
    consent_id = await _accept(client)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            sa.select(AnalyticsConsent).where(AnalyticsConsent.consent_id == uuid.UUID(consent_id))
        )).scalars().all()
    assert [(r.choice, r.version, r.source) for r in rows] == [
        ("accepted", "2026-11-08", "banner")]
    assert rows[0].created_at is not None


async def test_a_consent_with_an_unknown_choice_is_refused(client):
    res = await client.post("/analytics/consent", json={
        "consent_id": str(uuid.uuid4()), "choice": "maybe", "version": "2026-11-08",
        "source": "banner"})
    assert res.status_code == 422


# ---------------------------------------------------------------- with consent

async def test_with_consent_the_journey_is_stored_as_designed(client, monkeypatch):
    monkeypatch.setattr(settings, "trust_cf_connecting_ip", True)
    consent_id = await _accept(client)
    body = _batch(consent_id)
    res = await _collect(client, body, **{"cf-ipcountry": "ES", "cf-connecting-ip": "203.0.113.9"})
    assert res.status_code == 204

    session, events = await _rows_for_session(body["session_id"])
    assert session is not None
    assert str(session.visitor_id) == body["visitor_id"]
    assert str(session.consent_id) == consent_id
    assert session.referrer_domain == "www.tiktok.com"
    assert (session.utm_source, session.utm_medium, session.utm_campaign, session.utm_content) == (
        "tiktok", "social", "lanzamiento", "video-3")
    assert session.landing_path == "/es"
    assert (session.device, session.screen_w, session.screen_h) == ("mobile", 390, 844)
    assert (session.locale, session.lang, session.country) == ("es", "es-ES", "ES")
    assert [(e.type, e.path, e.element, e.depth, e.step) for e in events] == [
        ("pageview", "/es", None, None, None),
        ("step", "/es", None, None, "landing_view"),
        ("click", "/es", "landing-ask", None, None),
        ("scroll", "/es", None, 50, None),
        ("step", "/es/dashboard", None, None, "question_sent"),
    ]


async def test_country_is_only_read_where_cloudflare_is_trusted(client, monkeypatch):
    monkeypatch.setattr(settings, "trust_cf_connecting_ip", False)
    consent_id = await _accept(client)
    body = _batch(consent_id)
    await _collect(client, body, **{"cf-ipcountry": "FR"})
    session, _ = await _rows_for_session(body["session_id"])
    assert session.country is None


async def test_a_desktop_is_a_desktop(client):
    consent_id = await _accept(client)
    body = _batch(consent_id, screen_w=1440, screen_h=900)
    await _collect(client, body, ua=DESKTOP_UA)
    session, _ = await _rows_for_session(body["session_id"])
    assert session.device == "desktop"


async def test_a_second_batch_extends_the_same_session(client):
    consent_id = await _accept(client)
    body = _batch(consent_id)
    await _collect(client, body)
    more = dict(body, events=[{"ts": _now_ms(), "type": "step", "path": "/es/dashboard",
                               "step": "answer_shown"}])
    # A second batch from a later page may carry another referrer: the
    # session keeps the one it started with.
    more["context"] = dict(body["context"], referrer="adelia.godi.ai", utm_source=None)
    await _collect(client, more)
    session, events = await _rows_for_session(body["session_id"])
    assert len(events) == 6
    assert session.referrer_domain == "www.tiktok.com"
    assert session.utm_source == "tiktok"
    assert session.last_seen_at >= session.started_at


async def test_her_words_never_reach_the_database_whatever_the_payload_carries(client):
    """The question is planted everywhere a careless client could put it."""
    consent_id = await _accept(client)
    planted = _batch(
        consent_id,
        referrer=f"https://www.instagram.com/p/xyz/?q={QUESTION}",
        landing_path=f"/es/dashboard?ask=q.{QUESTION}",
        question=QUESTION,
        events=[
            {"ts": _now_ms(), "type": "pageview", "path": f"/es/dashboard?ask=q.{QUESTION}#{QUESTION}",
             "question": QUESTION, "answer": QUESTION, "text": QUESTION},
            {"ts": _now_ms(), "type": "click", "path": "/es/dashboard", "element": "agent-send",
             "value": QUESTION},
            {"ts": _now_ms(), "type": "step", "path": "/es/dashboard", "step": "question_sent",
             "question": QUESTION},
        ],
    )
    planted["question"] = QUESTION
    assert (await _collect(client, planted)).status_code == 204

    session, events = await _rows_for_session(planted["session_id"])
    assert session is not None and len(events) == 3
    assert session.referrer_domain == "www.instagram.com"
    assert session.landing_path == "/es/dashboard"
    assert events[0].path == "/es/dashboard"
    values: list[str] = []
    async with AsyncSessionLocal() as db:
        for table in ("analytics_sessions", "analytics_events", "analytics_consents"):
            for row in (await db.execute(sa.text(f"SELECT * FROM {table}"))).all():
                values.extend(str(v) for v in row)
    dump = " ".join(values)
    assert planted["session_id"] in dump
    for fragment in ("bebé", "fiebre", "38,5", "vomita", "meses"):
        assert fragment not in dump


async def test_identifiers_in_a_path_are_masked(client):
    consent_id = await _accept(client)
    doc = uuid.uuid4()
    body = _batch(consent_id, events=[
        {"ts": _now_ms(), "type": "pageview", "path": f"/es/dashboard/documents/{doc}"},
        {"ts": _now_ms(), "type": "pageview", "path": "/es/dashboard/briefings/12345"},
    ])
    await _collect(client, body)
    _, events = await _rows_for_session(body["session_id"])
    assert [e.path for e in events] == ["/es/dashboard/documents/:id", "/es/dashboard/briefings/:id"]


async def test_unknown_types_and_steps_are_dropped_and_long_labels_cut(client):
    consent_id = await _accept(client)
    body = _batch(consent_id, events=[
        {"ts": _now_ms(), "type": "keystroke", "path": "/es"},
        {"ts": _now_ms(), "type": "step", "path": "/es", "step": "typed_a_question"},
        {"ts": _now_ms(), "type": "scroll", "path": "/es", "depth": 400},
        {"ts": _now_ms(), "type": "click", "path": "/es", "element": "x" * 300},
    ])
    await _collect(client, body)
    _, events = await _rows_for_session(body["session_id"])
    assert [(e.type, e.depth) for e in events] == [("scroll", 100), ("click", None)]
    assert len(events[1].element) <= analytics.MAX_ELEMENT_CHARS


async def test_a_batch_is_capped(client):
    consent_id = await _accept(client)
    many = [{"ts": _now_ms(), "type": "pageview", "path": "/es"}] * (analytics.MAX_BATCH_EVENTS + 30)
    body = _batch(consent_id, events=many)
    await _collect(client, body)
    _, events = await _rows_for_session(body["session_id"])
    assert len(events) == analytics.MAX_BATCH_EVENTS


async def test_a_client_clock_far_off_is_replaced_by_the_server_clock(client):
    consent_id = await _accept(client)
    body = _batch(consent_id, events=[{"ts": 1, "type": "pageview", "path": "/es"}])
    await _collect(client, body)
    _, events = await _rows_for_session(body["session_id"])
    assert datetime.now(timezone.utc) - events[0].occurred_at < timedelta(minutes=5)


async def test_a_malformed_body_is_still_a_quiet_204(client):
    res = await client.post("/analytics/collect", content=b"not json",
                            headers={"content-type": "text/plain", "user-agent": PHONE_UA})
    assert res.status_code == 204


async def test_sendbeacon_text_plain_bodies_are_read(client):
    """sendBeacon with a string sends text/plain, which needs no preflight."""
    import json

    consent_id = await _accept(client)
    body = _batch(consent_id)
    res = await client.post("/analytics/collect", content=json.dumps(body).encode(),
                            headers={"content-type": "text/plain;charset=UTF-8",
                                     "user-agent": PHONE_UA})
    assert res.status_code == 204
    session, events = await _rows_for_session(body["session_id"])
    assert session is not None and len(events) == 5


# ---------------------------------------------------------------- retention

async def test_retention_deletes_events_after_13_months_and_proofs_when_the_law_allows():
    now = datetime.now(timezone.utc)
    old_consent, new_consent = uuid.uuid4(), uuid.uuid4()
    old_session, new_session = uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add_all([
            AnalyticsConsent(consent_id=old_consent, choice="accepted", version="old",
                             source="banner",
                             created_at=now - timedelta(days=analytics.CONSENT_PROOF_RETENTION_DAYS + 1)),
            AnalyticsConsent(consent_id=new_consent, choice="accepted", version="new",
                             source="banner", created_at=now - timedelta(days=500)),
            AnalyticsSession(session_id=old_session, visitor_id=uuid.uuid4(), consent_id=new_consent,
                             started_at=now - timedelta(days=400), last_seen_at=now - timedelta(days=400)),
            AnalyticsSession(session_id=new_session, visitor_id=uuid.uuid4(), consent_id=new_consent,
                             started_at=now - timedelta(days=380), last_seen_at=now - timedelta(days=380)),
        ])
        await db.flush()
        db.add_all([
            AnalyticsEvent(session_id=old_session, occurred_at=now - timedelta(days=400),
                           type="pageview", path="/es"),
            AnalyticsEvent(session_id=new_session, occurred_at=now - timedelta(days=380),
                           type="pageview", path="/es"),
        ])
        await db.commit()

    deleted = await analytics.purge_expired(now=now)
    assert deleted["sessions"] >= 1 and deleted["consents"] >= 1

    async with AsyncSessionLocal() as db:
        assert await db.get(AnalyticsSession, old_session) is None
        assert await db.get(AnalyticsSession, new_session) is not None
        old_events = await db.scalar(sa.select(sa.func.count()).select_from(AnalyticsEvent)
                                     .where(AnalyticsEvent.session_id == old_session))
        assert old_events == 0
        proofs = set((await db.execute(sa.select(AnalyticsConsent.consent_id).where(
            AnalyticsConsent.consent_id.in_([old_consent, new_consent])))).scalars())
        assert proofs == {new_consent}
        await db.execute(sa.delete(AnalyticsSession).where(AnalyticsSession.session_id == new_session))
        await db.execute(sa.delete(AnalyticsConsent).where(AnalyticsConsent.consent_id == new_consent))
        await db.commit()


def test_the_retention_periods_are_13_months_and_the_proof_outlives_them():
    assert 395 <= analytics.EVENT_RETENTION_DAYS <= 397
    # The proof must outlive the longest consent it can prove (13 months)
    # plus the 3 years in which a very serious infraction can be pursued
    # (LOPDGDD art. 72; LSSI art. 45).
    assert analytics.CONSENT_PROOF_RETENTION_DAYS >= analytics.EVENT_RETENTION_DAYS + 3 * 365


async def test_the_purge_runs_every_day_and_survives_a_bad_tick(monkeypatch):
    import asyncio

    from adelia import main

    calls: list[int] = []

    async def _purge(**_):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("one bad tick must not kill the loop")
        return {"sessions": 0, "events": 0, "consents": 0}

    monkeypatch.setattr(analytics, "purge_expired", _purge)
    monkeypatch.setattr(main, "ANALYTICS_PURGE_INTERVAL_S", 0.01)
    task = asyncio.create_task(main._periodic_analytics_purge())
    for _ in range(100):
        if len(calls) >= 3:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert len(calls) >= 3


async def test_the_purge_runs_at_boot_before_the_app_serves(monkeypatch):
    """Awaited in the lifespan, not raced beside it: a purge holding a pooled
    connection while the first requests arrive is the shape of the pool
    exhaustion CLAUDE.md warns about (and test_document_reconciliation counts
    the pool's connections at boot)."""
    from unittest.mock import AsyncMock

    from adelia.main import app, lifespan
    from adelia.routers import documents as docs_mod
    from adelia.routers import users as users_mod

    monkeypatch.setattr(users_mod, "sweep_blob_tombstones", AsyncMock())
    monkeypatch.setattr(docs_mod, "requeue_stuck_documents", AsyncMock(return_value=[]))
    monkeypatch.setattr(settings, "mistral_api_key", "")
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    purge = AsyncMock(return_value={"sessions": 0, "events": 0, "consents": 0})
    monkeypatch.setattr(analytics, "purge_expired", purge)

    async with lifespan(app):
        assert purge.await_count == 1


# ---------------------------------------------------------------- admin

async def _user_headers(email: str) -> dict[str, str]:
    async with AsyncSessionLocal() as db:
        user = User(email=email, subscription_status="active")
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return {"Authorization": f"Bearer {make_token(str(user.id))}"}


async def test_the_summary_is_a_404_for_anyone_not_on_the_admin_list(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    monkeypatch.setattr(settings, "admin_emails", "boss@godi.ai")
    stranger = await _user_headers(f"mum-{uuid.uuid4().hex[:8]}@example.com")
    assert (await client.get("/analytics/summary")).status_code == 404
    assert (await client.get("/analytics/summary", headers=stranger)).status_code == 404
    assert (await client.get("/analytics/access", headers=stranger)).status_code == 404
    assert (await client.get("/analytics/summary",
                             headers={"Authorization": "Bearer junk"})).status_code == 404


async def test_an_admin_reads_the_summary(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    email = f"admin-{uuid.uuid4().hex[:8]}@godi.ai"
    monkeypatch.setattr(settings, "admin_emails", f"someone@else.org, {email.upper()}")
    headers = await _user_headers(email)
    assert (await client.get("/analytics/access", headers=headers)).status_code == 204

    consent_id = await _accept(client)
    campaign = f"post-{uuid.uuid4().hex[:6]}"
    visitor = str(uuid.uuid4())
    now = _now_ms()
    await _collect(client, _batch(consent_id, visitor_id=visitor, utm_campaign=campaign, events=[
        {"ts": now - 5000, "type": "pageview", "path": "/es"},
        {"ts": now - 4000, "type": "step", "path": "/es", "step": "landing_view"},
        {"ts": now - 3500, "type": "step", "path": "/es", "step": "first_interaction"},
        {"ts": now - 3000, "type": "click", "path": "/es", "element": "landing-ask"},
        {"ts": now - 2000, "type": "step", "path": "/es", "step": "guest_created"},
        {"ts": now - 1000, "type": "step", "path": "/es/dashboard", "step": "question_sent"},
    ]))
    await _collect(client, _batch(consent_id, utm_campaign=campaign, events=[
        {"ts": now, "type": "step", "path": "/es", "step": "landing_view"},
    ]))

    res = await client.get("/analytics/summary?days=7", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["days"] == 7
    assert len(data["daily"]) == 7
    today = data["daily"][0]
    assert today["sessions"] >= 2 and today["visitors"] >= 2

    funnel = {row["step"]: row for row in data["funnel"]}
    assert [row["step"] for row in data["funnel"]] == list(analytics.FUNNEL_STEPS)
    assert funnel["landing_view"]["visitors"] >= 2
    assert funnel["guest_created"]["visitors"] >= 1
    assert 0 < funnel["guest_created"]["rate_from_previous"] <= 1

    utm = [row for row in data["sources"]["utm"] if row["campaign"] == campaign]
    assert len(utm) == 1
    assert utm[0]["sessions"] == 2 and utm[0]["source"] == "tiktok"
    assert utm[0]["steps"]["question_sent"] == 1
    assert utm[0]["deepest"] == "question_sent"

    assert any(r["path"] == "/es" and r["element"] == "landing-ask" for r in data["clicks"])
    recent = [s for s in data["recent_sessions"] if s["utm_campaign"] == campaign]
    assert recent and any(len(s["events"]) == 6 for s in recent)
    timeline = next(s for s in recent if len(s["events"]) == 6)["events"]
    assert [e["type"] for e in timeline] == ["pageview", "step", "step", "click", "step", "step"]
    assert timeline[-1]["step"] == "question_sent"
    assert "visitor_id" not in recent[0]
    assert set(data["consent"]) >= {"accepted", "rejected", "withdrawn"}
    # The anonymous counters keep their own block, untouched.
    assert set(data["counters"][0]) >= {"day", "visit", "start", "signup", "activation"}


async def test_rate_limit_on_collect(client, monkeypatch):
    from adelia import ratelimit

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    ratelimit.reset()
    group, budget = ratelimit._budget_for("POST", "/analytics/collect")
    assert group == "POST /analytics/" and 30 <= budget <= 600
    for _ in range(budget):
        assert (await client.post("/analytics/collect", json={})).status_code == 204
    assert (await client.post("/analytics/collect", json={})).status_code == 429


async def test_owner_email_is_one_more_admin(client, monkeypatch):
    """OWNER_EMAIL predates ADMIN_EMAILS (funnel, audit 4.8) and production may
    still set it. One rule for every admin read: it joins the list."""
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    email = f"owner-{uuid.uuid4().hex[:8]}@godi.ai"
    monkeypatch.setattr(settings, "admin_emails", "")
    monkeypatch.setattr(settings, "owner_email", email.upper())
    headers = await _user_headers(email)
    assert (await client.get("/analytics/access", headers=headers)).status_code == 204
    assert analytics.is_admin(email)
    monkeypatch.setattr(settings, "owner_email", "")
    assert (await client.get("/analytics/access", headers=headers)).status_code == 404



async def test_the_admin_summary_carries_the_short_link_clicks(client, monkeypatch):
    """The admin page shows which piece brought people: the /r/<code> clicks,
    counted without consent (services/funnel), next to the journeys."""
    from adelia.models import FunnelCounter
    from adelia.services.funnel import utc_today

    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    email = f"admin-{uuid.uuid4().hex[:8]}@godi.ai"
    monkeypatch.setattr(settings, "admin_emails", email)
    headers = await _user_headers(email)
    async with AsyncSessionLocal() as db:
        before = await db.scalar(sa.select(FunnelCounter.count).where(
            FunnelCounter.day == utc_today(), FunnelCounter.event == "link_g07"))
    await client.post("/funnel/link/g07")

    body = (await client.get("/analytics/summary?days=1", headers=headers)).json()

    links = {row["code"]: row for row in body["links"]}
    assert set(links) >= {"ig", "tt", "yt", "fb", "g01", "g10"}
    assert links["g07"]["clicks"] == (before or 0) + 1
    assert links["g07"]["content"] == "g07_bronquiolitis"
