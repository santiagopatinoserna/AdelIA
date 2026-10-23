"""`observations`: what she notes about her child, one row per fact (AGENT_GRAPH step 4).

Decision 2 of the graph: the record node writes to its own table, with a
numeric value and a unit, from the start, so a temperature can be compared
with yesterday's and plotted later. The Telegram diary stays free text and
does not change. These tests pin the table, its tenancy (two children of one
mother never share a row), and that GDPR erasure and export reach it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from adelia.db import AsyncSessionLocal
from adelia.models import Observation, Profile, User
from adelia.services.observations import (
    OBSERVATION_KINDS,
    add_observation,
    previous_comparable,
)
from adelia.services.scope import Scope

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

NOW = datetime(2026, 10, 23, 16, 10, tzinfo=timezone.utc)


async def _child(user_id, name="Lucía") -> Profile:
    async with AsyncSessionLocal() as session:
        profile = Profile(user_id=user_id, display_name=name, relationship="child")
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
        return profile


async def _add(user_id, profile_id, kind="temperature", value=37.8, unit="°C", at=NOW,
               text="hoy ha tenido 37,8"):
    async with AsyncSessionLocal() as session:
        row = await add_observation(
            session, user_id=user_id, profile_id=profile_id, kind=kind, value=value, unit=unit,
            text=text, observed_at=at, source="agent",
        )
        await session.commit()
        return row.id


def test_the_kinds_are_the_ones_the_spec_names():
    assert set(OBSERVATION_KINDS) >= {
        "temperature", "feed", "sleep", "stool", "symptom", "medication", "vaccine", "note",
    }


async def test_an_observation_round_trips():
    user_id = await make_user()
    child = await _child(user_id)
    obs_id = await _add(user_id, child.id)
    async with AsyncSessionLocal() as session:
        row = await session.get(Observation, obs_id)
    assert (row.kind, row.value, row.unit, row.source) == ("temperature", 37.8, "°C", "agent")
    assert row.profile_id == child.id and row.observed_at == NOW
    assert row.text == "hoy ha tenido 37,8"


async def test_the_previous_comparable_is_the_latest_same_kind_before_it():
    user_id = await make_user()
    child = await _child(user_id)
    await _add(user_id, child.id, value=37.0, at=NOW - timedelta(days=2))
    yesterday = await _add(user_id, child.id, value=37.2, at=NOW - timedelta(days=1))
    await _add(user_id, child.id, kind="feed", value=150, unit="ml", at=NOW - timedelta(hours=1))
    await _add(user_id, child.id, value=38.0, at=NOW + timedelta(hours=1))
    async with AsyncSessionLocal() as session:
        prev = await previous_comparable(
            session, scope=Scope(user_id, child.id), kind="temperature", before=NOW
        )
    assert prev is not None and prev.id == yesterday and prev.value == 37.2


async def test_a_sibling_never_sees_the_other_childs_observations():
    user_id = await make_user()
    lucia, mateo = await _child(user_id, "Lucía"), await _child(user_id, "Mateo")
    await _add(user_id, mateo.id, value=39.1, at=NOW - timedelta(days=1))
    async with AsyncSessionLocal() as session:
        prev = await previous_comparable(
            session, scope=Scope(user_id, lucia.id), kind="temperature", before=NOW
        )
    assert prev is None


async def test_an_unknown_kind_is_refused_by_the_database():
    user_id = await make_user()
    with pytest.raises(IntegrityError):
        await _add(user_id, None, kind="horoscope")


async def test_erasing_the_account_erases_the_observations():
    user_id = await make_user()
    child = await _child(user_id)
    await _add(user_id, child.id)
    async with AsyncSessionLocal() as session:
        await session.execute(sa.delete(User).where(User.id == user_id))
        await session.commit()
        left = await session.scalar(
            sa.select(sa.func.count()).select_from(Observation).where(Observation.user_id == user_id)
        )
    assert left == 0


async def test_the_export_carries_the_observations():
    from adelia.services.data_export import build_export

    user_id = await make_user()
    child = await _child(user_id)
    await _add(user_id, child.id)
    async with AsyncSessionLocal() as session:
        payload = await build_export(session, user_id)
    (row,) = payload["adelia"]["observations"]
    assert row["kind"] == "temperature" and row["value"] == 37.8 and row["unit"] == "°C"
    assert row["profile_id"] == str(child.id) and row["text"] == "hoy ha tenido 37,8"
