"""What a mother closes on the panel stays closed (2026-11-09).

"La barra de conectar a Telegram nunca desaparece" (Santiago): the link card
came back on every visit, on every device, and a guest got it too. A closed
card is now remembered on the server, per account, so it does not come back
after a reload nor in another browser; it never reaches a guest; and it still
goes away by itself once Telegram is linked.
"""
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.main import app
from adelia.models import TelegramLink, UiDismissal, User
from adelia.services import dismissals
from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")


@pytest.fixture(autouse=True)
async def _table():
    await dismissals.ensure_table()


@pytest.fixture
def bot_on(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "test-dummy")


def _as(user_id: uuid.UUID):
    from adelia.auth import get_current_user_id

    async def fake():
        return user_id

    app.dependency_overrides[get_current_user_id] = fake


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


def _intents(body: dict) -> set[str]:
    return {a["intent"] for c in body["cards"] for a in c["actions"]}


async def test_a_closed_telegram_card_stays_closed_for_that_account_only(client, bot_on):
    mine, other = await make_user(), await make_user()

    _as(mine)
    before = (await client.get("/agent/suggestions?locale=es")).json()
    card = next(c for c in before["cards"] if "link_telegram" in {a["intent"] for a in c["actions"]})
    assert card["payload"]["dismiss_key"] == "link_telegram"

    res = await client.post("/agent/suggestions/dismiss", json={"key": "link_telegram"})
    assert res.status_code == 204
    # Twice is still once: a double tap must not fail.
    assert (await client.post("/agent/suggestions/dismiss", json={"key": "link_telegram"})).status_code == 204

    # A new request (a reload, another browser of the same account): still closed.
    assert "link_telegram" not in _intents((await client.get("/agent/suggestions")).json())

    # Another account still gets it: the memory is hers, not the server's.
    _as(other)
    assert "link_telegram" in _intents((await client.get("/agent/suggestions")).json())

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(sa.select(UiDismissal).where(UiDismissal.user_id == mine))).scalars().all()
    assert [r.key for r in rows] == ["link_telegram"]


async def test_a_guest_is_never_offered_telegram(client, bot_on):
    user_id = await make_user()
    async with AsyncSessionLocal() as s:
        await s.execute(sa.update(User).where(User.id == user_id).values(is_guest=True))
        await s.commit()
    _as(user_id)
    assert not _intents((await client.get("/agent/suggestions")).json()) & {
        "link_telegram", "daily_diary"}


async def test_linking_telegram_replaces_the_link_card(client, bot_on):
    user_id = await make_user()
    async with AsyncSessionLocal() as s:
        s.add(TelegramLink(user_id=user_id, chat_id=uuid.uuid4().int % 10**12, username="e2e"))
        await s.commit()
    _as(user_id)
    intents = _intents((await client.get("/agent/suggestions")).json())
    assert "link_telegram" not in intents


async def test_only_a_known_shape_of_key_is_stored(client):
    _as(await make_user())
    for key in ("", "x" * 41, "Link Telegram", "<script>", "link-telegram"):
        res = await client.post("/agent/suggestions/dismiss", json={"key": key})
        assert res.status_code == 422, key


async def test_erasing_the_account_erases_what_she_closed():
    user_id = await make_user()
    await dismissals.dismiss(user_id, "link_telegram")
    async with AsyncSessionLocal() as s:
        await s.execute(sa.delete(User).where(User.id == user_id))
        await s.commit()
        left = await s.scalar(
            sa.select(sa.func.count()).select_from(UiDismissal).where(UiDismissal.user_id == user_id))
    assert left == 0
