"""The funnel is aggregate, owner-only, and cannot describe a person (4.8).

Three things are under test, in this order of importance:

1. The table cannot hold anybody. `funnel_counters` has three columns and none
   of them is an identifier, and the public endpoint writes nothing else.
2. Only the owner can read the numbers, and everyone else gets a 404 rather
   than a 403, which would confirm the endpoint exists.
3. Signups and activations are DERIVED from users.created_at and
   users.onboarded_at, not counted, so nothing has to be kept in sync.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import FunnelCounter, User
from adelia.services.funnel import utc_today

from tests.pg_gate import PG_AVAILABLE
from tests.test_auth import make_token

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")


@pytest.fixture(autouse=True)
async def _clean_counters():
    """The table is global, not per user: wipe today's rows around each case."""
    async def _wipe():
        async with AsyncSessionLocal() as session:
            await session.execute(sa.delete(FunnelCounter))
            await session.commit()

    await _wipe()
    yield
    await _wipe()


async def _owner_headers(monkeypatch) -> dict[str, str]:
    email = f"owner-{uuid.uuid4().hex[:8]}@godi.ai"
    async with AsyncSessionLocal() as session:
        user = User(email=email, subscription_status="active")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id
    monkeypatch.setattr(settings, "owner_email", email.upper())  # case-insensitive
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    return {"Authorization": f"Bearer {make_token(str(user_id))}"}


async def test_a_visit_is_one_integer_and_nothing_else(client):
    assert (await client.post("/funnel/visit")).status_code == 204
    assert (await client.post("/funnel/visit")).status_code == 204
    assert (await client.post("/funnel/start")).status_code == 204

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                sa.select(FunnelCounter.event, FunnelCounter.count).order_by(
                    FunnelCounter.event
                )
            )
        ).all()

    assert rows == [("start", 1), ("visit", 2)]


def test_the_table_has_no_column_that_could_hold_a_person():
    """The privacy promise is structural, not a policy: there is nowhere to
    put an IP, a session, a user agent or a user id even by accident."""
    columns = set(FunnelCounter.__table__.columns.keys())

    assert columns == {"day", "event", "count"}


async def test_an_unknown_event_writes_nothing_and_still_answers_204(client):
    """The endpoint is called from a beacon on a page the visitor is leaving.
    Nobody reads the status, and an error body is one more thing to probe."""
    assert (await client.post("/funnel/wat")).status_code == 204
    # "demo_ask" is counted, but only by the demo itself: letting anyone POST
    # it would let anyone burn the demo's daily budget without asking anything.
    assert (await client.post("/funnel/demo_ask")).status_code == 204

    async with AsyncSessionLocal() as session:
        assert (await session.execute(sa.select(FunnelCounter))).all() == []


async def test_the_summary_is_owner_only(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    monkeypatch.setattr(settings, "owner_email", "santiago@godi.ai")

    async with AsyncSessionLocal() as session:
        user = User(email=f"other-{uuid.uuid4().hex[:8]}@adelia.test")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        stranger = user.id

    anonymous = await client.get("/funnel/summary")
    assert anonymous.status_code in (401, 403)

    other = await client.get(
        "/funnel/summary",
        headers={"Authorization": f"Bearer {make_token(str(stranger))}"},
    )
    # 404, not 403: a 403 tells a stranger the numbers exist.
    assert other.status_code == 404


async def test_nobody_reads_the_summary_when_no_owner_is_configured(
    client, monkeypatch
):
    """The default of every self-hosted install."""
    headers = await _owner_headers(monkeypatch)
    monkeypatch.setattr(settings, "owner_email", "")

    assert (await client.get("/funnel/summary", headers=headers)).status_code == 404


async def test_the_owner_sees_the_four_funnel_numbers(client, monkeypatch):
    headers = await _owner_headers(monkeypatch)
    await client.post("/funnel/visit")
    await client.post("/funnel/visit")
    await client.post("/funnel/start")

    resp = await client.get("/funnel/summary?days=7", headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["days"] == 7
    today = body["rows"][0]
    assert today["day"] == utc_today().isoformat()
    assert today["visit"] == 2
    assert today["start"] == 1
    # The owner account was created a moment ago, so it is today's signup.
    assert today["signup"] >= 1


async def test_signups_and_activations_are_derived_not_counted(client, monkeypatch):
    """No write happens at signup or at onboarding: both columns are read off
    rows the product already keeps."""
    headers = await _owner_headers(monkeypatch)
    stamped = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        session.add(
            User(
                email=f"activated-{uuid.uuid4().hex[:8]}@adelia.test",
                onboarded_at=stamped,
            )
        )
        await session.commit()

    resp = await client.get("/funnel/summary?days=2", headers=headers)

    today = resp.json()["rows"][0]
    assert today["activation"] >= 1
    async with AsyncSessionLocal() as session:
        # ...and the counters table never learned about it.
        events = (
            await session.execute(sa.select(FunnelCounter.event))
        ).scalars().all()
    assert "signup" not in events and "activation" not in events


async def test_a_day_with_no_traffic_is_a_zero_row_not_a_gap(client, monkeypatch):
    """A missing day reads as lost data; a zero reads as nobody came."""
    headers = await _owner_headers(monkeypatch)

    rows = (await client.get("/funnel/summary?days=5", headers=headers)).json()["rows"]

    assert [r["day"] for r in rows] == [
        (utc_today() - timedelta(days=n)).isoformat() for n in range(5)
    ]
    assert rows[-1]["visit"] == 0


async def test_the_window_is_capped(client, monkeypatch):
    headers = await _owner_headers(monkeypatch)

    resp = await client.get("/funnel/summary?days=100000", headers=headers)

    assert resp.json()["days"] == 365


async def test_concurrent_visits_do_not_lose_a_count():
    """The increment is an atomic upsert evaluated by Postgres, not a
    read-modify-write in Python."""
    import asyncio

    from adelia.services import funnel

    await asyncio.gather(*(funnel.bump("visit") for _ in range(12)))

    async with AsyncSessionLocal() as session:
        total = await session.scalar(
            sa.select(FunnelCounter.count).where(
                FunnelCounter.day == utc_today(), FunnelCounter.event == "visit"
            )
        )
    assert total == 12


async def test_an_admin_on_admin_emails_reads_the_funnel_and_the_usage(client, monkeypatch):
    """One rule for "who reads the numbers" (2026-11-08): /funnel/summary and
    /funnel/usage admit the same accounts as /analytics/summary, so Santiago's
    two addresses in ADMIN_EMAILS open all three without OWNER_EMAIL."""
    email = f"admin-{uuid.uuid4().hex[:8]}@godi.ai"
    async with AsyncSessionLocal() as session:
        user = User(email=email, subscription_status="active")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        headers = {"Authorization": f"Bearer {make_token(str(user.id))}"}
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    monkeypatch.setattr(settings, "owner_email", "")
    monkeypatch.setattr(settings, "admin_emails", f"someone@else.org, {email.upper()}")

    assert (await client.get("/funnel/summary", headers=headers)).status_code == 200
    assert (await client.get("/funnel/usage", headers=headers)).status_code == 200

    monkeypatch.setattr(settings, "admin_emails", "someone@else.org")
    assert (await client.get("/funnel/summary", headers=headers)).status_code == 404
    assert (await client.get("/funnel/usage", headers=headers)).status_code == 404



# ---------------------------------------------------------------- short links
#
# /r/<code> on the web asks this API where the code goes (services/short_links)
# and counts the click: one integer per day and code, like a visit, so the
# community plan can tell which piece brings people even when the visitor
# never answers the analytics banner. No body, no cookie, no identifier.


async def _link_counts() -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            sa.select(FunnelCounter.event, FunnelCounter.count)
            .where(FunnelCounter.day == utc_today())
        )).all()
    return {event: int(count) for event, count in rows}


async def test_a_short_link_click_is_one_integer_and_answers_where_to_go(client):
    first = await client.post("/funnel/link/g02")
    second = await client.post("/funnel/link/G02")

    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == {
        "code": "g02",
        "location": "/es?utm_source=redes&utm_medium=social&utm_campaign=lanzamiento_2026_11"
                    "&utm_content=g02_fiebre3m",
    }
    assert "set-cookie" not in first.headers
    assert await _link_counts() == {"link_g02": 2}


async def test_reading_where_a_link_goes_counts_nothing(client):
    """For link previews and checkers: the web resolves with GET, no count."""
    res = await client.get("/funnel/link/ig")

    assert res.status_code == 200
    assert res.json()["location"].startswith("/es?utm_source=instagram&utm_medium=bio")
    assert await _link_counts() == {}


async def test_an_unknown_code_is_a_404_and_writes_nothing(client):
    for code in ("nope", "g11", "x" * 300):
        assert (await client.post(f"/funnel/link/{code}")).status_code == 404
        assert (await client.get(f"/funnel/link/{code}")).status_code == 404
    # Not through the visit endpoint either: the allowlist is the validation.
    assert (await client.post("/funnel/link_g02")).status_code == 204
    assert await _link_counts() == {}


async def test_the_summary_lists_every_short_link_with_its_clicks(client, monkeypatch):
    headers = await _owner_headers(monkeypatch)
    await client.post("/funnel/link/g02")
    await client.post("/funnel/link/g02")
    await client.post("/funnel/link/tt")

    body = (await client.get("/funnel/summary?days=7", headers=headers)).json()

    links = {row["code"]: row for row in body["links"]}
    assert links["g02"] == {"code": "g02", "source": "redes", "medium": "social",
                            "content": "g02_fiebre3m", "clicks": 2}
    assert links["tt"]["clicks"] == 1
    assert links["g01"]["clicks"] == 0
    assert [row["code"] for row in body["links"]][:2] == ["g02", "tt"]
