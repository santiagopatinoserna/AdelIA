"""The three questions a baby-health app has to ask (audit 4.3).

Between the magic link and the first useful pixel there was a credit card and
not one question about the child, so every age-gated clinical rule ran blind:
the "<3 months with a fever" red flag could not fire, the lab ranges compared
an infant against adult values, and the briefing header printed "0 años".
"""
from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from tests.pg_gate import PG_AVAILABLE

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")


async def _as(user_id):
    """An httpx client authenticated as `user_id`. Onboarding is NOT behind
    the paywall, so only the identity dependency is overridden."""
    from adelia.auth import get_current_user_id
    from adelia.main import app

    app.dependency_overrides[get_current_user_id] = lambda: user_id
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _clear_overrides():
    from adelia.main import app

    app.dependency_overrides.clear()


async def test_a_new_account_is_asked_about_the_baby():
    from tests.db_helpers import make_user

    user_id = await make_user()
    try:
        async with await _as(user_id) as ac:
            res = await ac.get("/users/me/onboarding")
    finally:
        _clear_overrides()

    assert res.status_code == 200
    assert res.json()["needed"] is True


async def test_answering_creates_a_child_profile_and_closes_the_screen():
    from adelia.db import AsyncSessionLocal
    from adelia.enrichment import profile_service
    from tests.db_helpers import make_user

    user_id = await make_user()
    dob = (date.today() - timedelta(days=200)).isoformat()
    try:
        async with await _as(user_id) as ac:
            created = await ac.post(
                "/users/me/onboarding",
                json={"display_name": "Adel", "date_of_birth": dob, "sex": "M"},
            )
            after = await ac.get("/users/me/onboarding")
    finally:
        _clear_overrides()

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["relationship"] == "child"
    assert body["is_default"] is True
    assert after.json()["needed"] is False

    # And the facts every clinical surface reads are now there.
    async with AsyncSessionLocal() as session:
        facts = await profile_service.get_profile_facts(session, user_id=user_id)
    assert facts.display_name == "Adel"
    assert facts.sex == "M"
    assert facts.age_months == 6


async def test_the_screen_is_skippable_and_stays_skipped():
    """A parent arriving at 3 a.m. with a feverish baby gets past it in one
    tap, and is not asked again on her next device."""
    from tests.db_helpers import make_user

    user_id = await make_user()
    try:
        async with await _as(user_id) as ac:
            skipped = await ac.post("/users/me/onboarding/skip")
            after = await ac.get("/users/me/onboarding")
    finally:
        _clear_overrides()

    assert skipped.status_code == 204
    assert after.json()["needed"] is False


async def test_an_account_that_already_has_a_child_is_never_asked():
    """The agent's completar_perfil tool and the profiles screen both create
    child profiles; re-asking would read as the app not listening."""
    from adelia.db import AsyncSessionLocal
    from adelia.enrichment import profile_service
    from tests.db_helpers import make_user

    user_id = await make_user()
    async with AsyncSessionLocal() as session:
        await profile_service.create_profile(
            session,
            user_id=user_id,
            data=profile_service.ProfileCreate(
                display_name="Nora", relationship="child",
                date_of_birth=date(2024, 1, 1), is_default=True,
            ),
        )
        await session.commit()

    try:
        async with await _as(user_id) as ac:
            res = await ac.get("/users/me/onboarding")
    finally:
        _clear_overrides()

    assert res.json()["needed"] is False


async def test_a_future_date_of_birth_is_rejected():
    """Accepting it would make age_in_months return None and silently switch
    off every age-gated clinical rule."""
    from tests.db_helpers import make_user

    user_id = await make_user()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    try:
        async with await _as(user_id) as ac:
            res = await ac.post(
                "/users/me/onboarding",
                json={"display_name": "Adel", "date_of_birth": tomorrow},
            )
    finally:
        _clear_overrides()

    assert res.status_code == 422


async def test_onboarding_needs_authentication():
    from adelia.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        res = await ac.get("/users/me/onboarding")
    assert res.status_code in (401, 403)


async def test_name_only_is_enough():
    """Date of birth and sex are optional: a name alone still gives the
    briefing header and the profile switcher something true to show."""
    from tests.db_helpers import make_user

    user_id = await make_user()
    try:
        async with await _as(user_id) as ac:
            res = await ac.post(
                "/users/me/onboarding", json={"display_name": "Bebé"}
            )
    finally:
        _clear_overrides()

    assert res.status_code == 201
    assert res.json()["date_of_birth"] is None
    assert res.json()["sex"] is None


async def test_unknown_user_id_does_not_500():
    """The identity comes from a JWT that outlives an erased account."""
    ghost = uuid4()
    try:
        async with await _as(ghost) as ac:
            res = await ac.get("/users/me/onboarding")
    finally:
        _clear_overrides()

    assert res.status_code == 200
    assert res.json()["needed"] is True
