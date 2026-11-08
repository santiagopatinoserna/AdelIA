"""Test traffic stays out of the numbers (2026-11-08).

The production smoke suite (apps/web/e2e-prod) and other agents' runs used to
add visits, guest signups, short-link clicks and provider calls to the same
counters Santiago reads to decide where the product goes. A request carrying
`X-AdelIA-QA: 1` is still served exactly as any other; it is only left out of
the anonymous funnel, the consented analytics, the /r/ clicks and the usage
counter. Not a security control: it opens nothing and closes nothing, and the
demo's daily spending ceiling still counts it.
"""
from __future__ import annotations

import asyncio
import random
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from fastapi import HTTPException

from adelia import qa_traffic
from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import AnalyticsConsent, AnalyticsSession, FunnelCounter, Profile, User
from adelia.services import analytics, funnel, short_links, usage

from tests.pg_gate import PG_AVAILABLE

pg_only = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

QA = {"X-AdelIA-QA": "1"}
PHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1"
)


@pytest.fixture
async def day(monkeypatch):
    """A day of its own, far in the past, for funnel_counters.

    The table is global and other worktrees' suites bump today's rows on the
    same dev database, so these cases count on a day nobody else writes.
    """
    the_day = date(1990, 1, 1) + timedelta(days=random.randrange(3000))
    monkeypatch.setattr(funnel, "utc_today", lambda: the_day)

    async def _wipe():
        async with AsyncSessionLocal() as session:
            await session.execute(sa.delete(FunnelCounter).where(FunnelCounter.day == the_day))
            await session.commit()

    await _wipe()
    yield the_day
    await _wipe()


async def _counters(the_day: date) -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            sa.select(FunnelCounter.event, FunnelCounter.count)
            .where(FunnelCounter.day == the_day))).all()
    return {event: int(n) for event, n in rows}


# --- the marker ------------------------------------------------------------------


def test_the_header_is_x_adelia_qa():
    assert qa_traffic.HEADER == "X-AdelIA-QA"


def test_outside_a_request_nothing_is_test_traffic():
    assert qa_traffic.is_qa() is False
    with qa_traffic.marked():
        assert qa_traffic.is_qa() is True
    assert qa_traffic.is_qa() is False


async def test_work_spawned_by_a_test_request_is_test_traffic_too():
    """The guest's embedding fill and a document's pipeline run as tasks after
    the response; they inherit the request's context, so their provider calls
    stay out of the usage counter as well."""
    with qa_traffic.marked():
        inherited = await asyncio.create_task(asyncio.sleep(0, result=qa_traffic.is_qa()))
        task = asyncio.create_task(_read_marker())
    assert await task is True
    assert inherited is True


async def _read_marker() -> bool:
    await asyncio.sleep(0)
    return qa_traffic.is_qa()


# --- the anonymous funnel ----------------------------------------------------------


@pg_only
async def test_a_test_visit_or_start_is_not_counted_and_still_answers_204(client, day):
    for event in ("visit", "start"):
        assert (await client.post(f"/funnel/{event}", headers=QA)).status_code == 204
    assert await _counters(day) == {}

    await client.post("/funnel/visit")
    assert await _counters(day) == {"visit": 1}


@pg_only
@pytest.mark.parametrize("value", ["0", "true", "yes", ""])
async def test_only_the_value_1_marks_test_traffic(client, day, value):
    await client.post("/funnel/visit", headers={"X-AdelIA-QA": value})
    assert await _counters(day) == {"visit": 1}


@pg_only
async def test_a_test_click_on_a_short_link_is_not_counted_and_goes_to_the_same_place(
    client, day,
):
    code = next(iter(short_links.LINKS))
    plain = await client.post(f"/funnel/link/{code}")
    tested = await client.post(f"/funnel/link/{code}", headers=QA)

    assert tested.status_code == plain.status_code == 200
    assert tested.json() == plain.json()
    assert await _counters(day) == {short_links.event(short_links.LINKS[code]): 1}


@pg_only
async def test_the_demo_ceiling_still_counts_test_asks_but_the_funnel_does_not(
    day, monkeypatch,
):
    """The header must never be a way around the demo's spending gate: a test
    ask spends the same budget, it is only kept out of the demo_ask column."""
    from adelia.routers.demo import _admit

    monkeypatch.setattr(settings, "demo_daily_budget", 2)
    await _admit()
    with qa_traffic.marked():
        await _admit()
        with pytest.raises(HTTPException) as refused:
            await _admit()
    assert refused.value.status_code == 429
    with pytest.raises(HTTPException):
        await _admit()

    assert (await funnel.summary(1, today=day))[0]["demo_ask"] == 2  # two real asks tried
    counted = await _counters(day)
    assert counted["demo_ask"] == 2
    assert counted["demo_ask_qa"] == 2


@pg_only
async def test_test_asks_alone_cannot_spend_past_the_ceiling(day, monkeypatch):
    from adelia.routers.demo import _admit

    monkeypatch.setattr(settings, "demo_daily_budget", 1)
    with qa_traffic.marked():
        await _admit()
        with pytest.raises(HTTPException):
            await _admit()
    with pytest.raises(HTTPException):
        await _admit()
    assert (await funnel.summary(1, today=day))[0]["demo_ask"] == 1


# --- guest signups -------------------------------------------------------------------


async def _new_guest(client, headers: dict[str, str] | None = None) -> uuid.UUID:
    with patch("adelia.services.guest.fill_seed_embeddings", return_value=0):
        resp = await client.post("/guest", json={"locale": "es"}, headers=headers or {})
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["user_id"])


@pg_only
async def test_a_test_guest_is_a_real_guest_left_out_of_signups_and_activations(client):
    the_day = date(1980, 1, 1) + timedelta(days=random.randrange(3000))
    stamp = datetime.combine(the_day, datetime.min.time(), tzinfo=timezone.utc)
    stamp += timedelta(hours=12)
    tested = await _new_guest(client, QA)
    real = await _new_guest(client)
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                sa.update(User).where(User.id.in_([tested, real]))
                .values(created_at=stamp, onboarded_at=stamp))
            await session.commit()
            guest = await session.get(User, tested)
            assert guest.is_guest is True
            lucia = await session.scalar(sa.select(Profile).where(Profile.user_id == tested))
            assert lucia is not None

        row = (await funnel.summary(1, today=the_day))[0]
        assert (row["signup"], row["activation"]) == (1, 1)
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(sa.delete(User).where(User.id.in_([tested, real])))
            await session.commit()


# --- the consented analytics ---------------------------------------------------------


def _batch(consent_id: str) -> dict:
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    return {
        "consent_id": consent_id,
        "visitor_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "context": {"locale": "es", "landing_path": "/es"},
        "events": [{"ts": now, "type": "pageview", "path": "/es"}],
    }


@pg_only
async def test_a_test_batch_and_a_test_consent_are_not_stored(client):
    await analytics.ensure_tables()
    accepted, tested_consent = str(uuid.uuid4()), str(uuid.uuid4())
    body = {"choice": "accepted", "version": "2026-11-08", "source": "banner"}
    try:
        assert (await client.post("/analytics/consent",
                                  json={"consent_id": accepted, **body})).status_code == 204
        res = await client.post("/analytics/consent", headers=QA,
                                json={"consent_id": tested_consent, **body})
        assert res.status_code == 204
        tested_batch, real_batch = _batch(accepted), _batch(accepted)
        res = await client.post("/analytics/collect", json=tested_batch,
                                headers={"user-agent": PHONE_UA, **QA})
        assert res.status_code == 204
        await client.post("/analytics/collect", json=real_batch, headers={"user-agent": PHONE_UA})

        async with AsyncSessionLocal() as db:
            consents = set((await db.execute(
                sa.select(AnalyticsConsent.consent_id).where(AnalyticsConsent.consent_id.in_(
                    [uuid.UUID(accepted), uuid.UUID(tested_consent)])))).scalars())
            assert consents == {uuid.UUID(accepted)}
            assert await db.get(AnalyticsSession, uuid.UUID(tested_batch["session_id"])) is None
            assert await db.get(AnalyticsSession, uuid.UUID(real_batch["session_id"])) is not None
    finally:
        async with AsyncSessionLocal() as db:
            ids = [uuid.UUID(accepted), uuid.UUID(tested_consent)]
            await db.execute(sa.delete(AnalyticsSession).where(AnalyticsSession.consent_id.in_(ids)))
            await db.execute(sa.delete(AnalyticsConsent).where(AnalyticsConsent.consent_id.in_(ids)))
            await db.commit()


# --- the usage counter -----------------------------------------------------------------


async def test_a_provider_call_of_test_traffic_is_not_counted(monkeypatch):
    written: list[str] = []

    async def _record(operation, provider, model, **_):
        written.append(operation)

    monkeypatch.setattr(usage, "record", _record)
    with qa_traffic.marked():
        usage.count("chat", "mistral", "mistral-small-latest", input_tokens=10)
    usage.count("embed", "mistral", "mistral-embed", input_tokens=3)
    await asyncio.gather(*usage._live_pending())

    assert written == ["embed"]
