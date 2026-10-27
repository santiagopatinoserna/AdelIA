"""`GET /today`: what is due today with this child, read from her own tables.

The vision note of 2026-10-22: a mother wants a plan and to feel accompanied,
which on the home screen means one glance answers "what is due today, what
must I not forget". Three sources, nothing invented: the vaccination
calendar against the child's age and record, the `observations` table, and
the "No olvides" section of the last plan the chat stored. Every read goes
through `Scope`, so two children of one mother never share a line.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from adelia.db import AsyncSessionLocal
from adelia.models import ChatMessage, ChatSession, Profile
from adelia.services.observations import add_observation
from adelia.services.today import build_today

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

NOW = datetime(2026, 10, 27, 16, 10, tzinfo=timezone.utc)


def _dob(months: int) -> date:
    """A date of birth `months` whole months before NOW."""
    year, month = NOW.year, NOW.month - months
    while month <= 0:
        year, month = year - 1, month + 12
    return date(year, month, 1)


async def _child(user_id, name="Nora", *, months: int | None = None, default=True) -> Profile:
    async with AsyncSessionLocal() as session:
        profile = Profile(user_id=user_id, display_name=name, relationship="child",
                          date_of_birth=_dob(months) if months is not None else None,
                          is_default=default)
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
        return profile


async def _observe(user_id, profile_id, value, at, kind="temperature", unit="°C", text=None):
    async with AsyncSessionLocal() as session:
        await add_observation(
            session, user_id=user_id, profile_id=profile_id, kind=kind, value=value, unit=unit,
            text=text or f"ha tenido {value}", observed_at=at, source="agent",
        )
        await session.commit()


async def _store_plan(user_id, content, *, days_ago=0):
    async with AsyncSessionLocal() as session:
        chat = ChatSession(user_id=user_id, title="t")
        session.add(chat)
        await session.flush()
        msg = ChatMessage(session_id=chat.id, user_id=user_id, role="assistant", content=content,
                          created_at=NOW - timedelta(days=days_ago))
        session.add(msg)
        await session.commit()


def _kinds(payload: dict) -> list[str]:
    return [item["kind"] for item in payload["items"]]


async def test_nothing_due_means_no_items():
    """A 6-month-old with every dose noted, no reading this week, no plan: nothing to show."""
    user_id = await make_user()
    child = await _child(user_id, months=6)
    async with AsyncSessionLocal() as session:
        for name in ("Hexavalente", "Hexavalente", "Neumococo", "Neumococo",
                     "Meningococo B", "Meningococo B", "Meningococo C"):
            await add_observation(
                session, user_id=user_id, profile_id=child.id, kind="vaccine", value=None,
                unit=None, text=f"le han puesto la {name}", observed_at=NOW - timedelta(days=30),
                source="agent",
            )
        await session.commit()
    payload = await build_today(user_id=user_id, profile_id=child.id, locale="es", now=NOW)
    assert payload == {"name": "Nora", "items": []}


async def test_a_dose_due_this_month_is_named_without_a_dose_amount():
    """At 3 months with the 2-month doses noted, the 4-month ones are within a month."""
    user_id = await make_user()
    child = await _child(user_id, months=3)
    for name in ("Hexavalente", "Neumococo", "Meningococo B", "Rotavirus"):
        await _observe(user_id, child.id, None, NOW - timedelta(days=30), kind="vaccine",
                       unit=None, text=f"le han puesto la {name}")
    payload = await build_today(user_id=user_id, profile_id=child.id, locale="es", now=NOW)
    vaccine = [i for i in payload["items"] if i["kind"] == "vaccine"]
    assert len(vaccine) == 1
    text = vaccine[0]["text"]
    assert "Hexavalente" in text and "4 meses" in text and "2.ª dosis" in text
    assert "Meningococo C" in text
    assert vaccine[0]["tone"] == "neutral"
    assert "mg" not in text and "ml" not in text


async def test_doses_further_than_a_month_away_do_not_show():
    """At 9 months with the 2 and 4 month doses noted, the 11-month ones are not for today."""
    user_id = await make_user()
    child = await _child(user_id, months=9)
    for name in ("Hexavalente", "Hexavalente", "Neumococo", "Neumococo",
                 "Meningococo B", "Meningococo B", "Meningococo C"):
        await _observe(user_id, child.id, None, NOW - timedelta(days=60), kind="vaccine",
                       unit=None, text=f"le han puesto la {name}")
    payload = await build_today(user_id=user_id, profile_id=child.id, locale="es", now=NOW)
    assert _kinds(payload) == []
    payload = await build_today(user_id=user_id, profile_id=child.id, locale="es",
                                now=NOW.replace(month=12))
    assert _kinds(payload) == ["vaccine"]
    assert payload["items"][0]["tone"] == "neutral"


async def test_overdue_doses_are_a_warning_and_a_siblings_record_does_not_cover_them():
    user_id = await make_user()
    nora = await _child(user_id, "Nora", months=6)
    adel = await _child(user_id, "Adel", months=30, default=False)
    for name in ("Hexavalente", "Hexavalente", "Neumococo", "Neumococo",
                 "Meningococo B", "Meningococo B", "Meningococo C"):
        await _observe(user_id, adel.id, None, NOW - timedelta(days=60), kind="vaccine",
                       unit=None, text=f"le han puesto la {name}")
    payload = await build_today(user_id=user_id, profile_id=nora.id, locale="es", now=NOW)
    assert _kinds(payload) == ["vaccine"]
    assert payload["items"][0]["tone"] == "warn"
    assert "Hexavalente" in payload["items"][0]["text"]


async def test_no_date_of_birth_means_no_vaccine_line():
    user_id = await make_user()
    child = await _child(user_id)
    payload = await build_today(user_id=user_id, profile_id=child.id, locale="es", now=NOW)
    assert _kinds(payload) == []


async def _well_vaccinated_child(user_id, name="Nora", *, default=True) -> Profile:
    """A 9-month-old with every dose to date noted, so only observations and plans show."""
    child = await _child(user_id, name, months=9, default=default)
    for vac in ("Hexavalente", "Hexavalente", "Neumococo", "Neumococo",
                "Meningococo B", "Meningococo B", "Meningococo C"):
        await _observe(user_id, child.id, None, NOW - timedelta(days=90), kind="vaccine",
                       unit=None, text=f"le han puesto la {vac}")
    return child


async def test_todays_reading_is_compared_with_yesterdays():
    user_id = await make_user()
    child = await _well_vaccinated_child(user_id)
    await _observe(user_id, child.id, 37.2, NOW - timedelta(days=1))
    await _observe(user_id, child.id, 37.8, NOW - timedelta(hours=2))
    payload = await build_today(user_id=user_id, profile_id=child.id, locale="es", now=NOW)
    assert _kinds(payload) == ["observation"]
    assert payload["items"][0]["text"] == "Temperatura: ayer 37,2 °C, hoy 37,8 °C."
    assert payload["items"][0]["tone"] == "neutral"


async def test_a_first_reading_stands_alone_and_an_old_one_does_not_show():
    user_id = await make_user()
    child = await _well_vaccinated_child(user_id)
    await _observe(user_id, child.id, 37.2, NOW - timedelta(days=3))
    payload = await build_today(user_id=user_id, profile_id=child.id, locale="es", now=NOW)
    assert _kinds(payload) == []
    await _observe(user_id, child.id, 150, NOW - timedelta(days=1), kind="feed", unit="ml")
    payload = await build_today(user_id=user_id, profile_id=child.id, locale="es", now=NOW)
    assert payload["items"][0]["text"] == "Toma: ayer 150 ml."


async def test_a_siblings_reading_never_appears_under_this_child():
    user_id = await make_user()
    nora = await _well_vaccinated_child(user_id, "Nora")
    adel = await _well_vaccinated_child(user_id, "Adel", default=False)
    await _observe(user_id, adel.id, 38.5, NOW - timedelta(hours=1))
    await _observe(user_id, nora.id, 37.0, NOW - timedelta(days=1))
    payload = await build_today(user_id=user_id, profile_id=nora.id, locale="es", now=NOW)
    assert payload["name"] == "Nora"
    assert [i["text"] for i in payload["items"]] == ["Temperatura: ayer 37 °C."]


async def test_the_reading_speaks_her_language():
    user_id = await make_user()
    child = await _well_vaccinated_child(user_id)
    await _observe(user_id, child.id, 37.2, NOW - timedelta(days=1))
    await _observe(user_id, child.id, 37.8, NOW - timedelta(hours=2))
    en = await build_today(user_id=user_id, profile_id=child.id, locale="en", now=NOW)
    fr = await build_today(user_id=user_id, profile_id=child.id, locale="fr", now=NOW)
    # fr reads the French calendar (pediatrics: a locale is the only country signal
    # until Profile carries one), so pick the reading by kind, not by position.
    reading = {lang: next(i for i in p["items"] if i["kind"] == "observation")
               for lang, p in (("en", en), ("fr", fr))}
    assert reading["en"]["text"] == "Temperature: yesterday 37.2 °C, today 37.8 °C."
    # French keeps the no-break space before the unit, as record.py already does.
    assert reading["fr"]["text"] == "Température : hier 37,2\u00a0°C, aujourd’hui 37,8\u00a0°C."


PLAN = (
    "## Hoy\n- Ofrécele pecho o biberón más a menudo [ev_1].\n\n"
    "## Vigila\n- Que moje al menos 4 pañales.\n\n"
    "## Cuándo ir al médico\n- Si la fiebre pasa de 38 °C.\n\n"
    "## No olvides\n- Apunta cada toma y cada pañal mojado hasta mañana [ev_2].\n"
    "- Lleva la cartilla a la revisión.\n"
)


async def test_the_last_plans_no_olvides_line_is_shown_without_citation_markers():
    user_id = await make_user()
    child = await _well_vaccinated_child(user_id)
    await _store_plan(user_id, PLAN, days_ago=2)
    payload = await build_today(user_id=user_id, profile_id=child.id, locale="es", now=NOW)
    assert _kinds(payload) == ["remember"]
    assert payload["items"][0]["text"] == "Apunta cada toma y cada pañal mojado hasta mañana."


async def test_a_plan_older_than_a_week_or_without_the_section_is_skipped():
    user_id = await make_user()
    child = await _well_vaccinated_child(user_id)
    await _store_plan(user_id, PLAN, days_ago=8)
    await _store_plan(user_id, "Una respuesta corta sin apartados [ev_1].", days_ago=1)
    payload = await build_today(user_id=user_id, profile_id=child.id, locale="es", now=NOW)
    assert _kinds(payload) == []


async def test_with_two_children_the_plan_line_cannot_be_attributed_and_is_skipped():
    """chat_messages carry no profile_id: a plan about Adel must not land under Nora."""
    user_id = await make_user()
    nora = await _well_vaccinated_child(user_id, "Nora")
    await _well_vaccinated_child(user_id, "Adel", default=False)
    await _store_plan(user_id, PLAN, days_ago=1)
    payload = await build_today(user_id=user_id, profile_id=nora.id, locale="es", now=NOW)
    assert _kinds(payload) == []


async def test_the_section_is_read_in_her_language():
    user_id = await make_user()
    child = await _well_vaccinated_child(user_id)
    await _store_plan(user_id, "## Today\n- Rest.\n\n## Don’t forget\n- Bring the card [ev_1].\n")
    payload = await build_today(user_id=user_id, profile_id=child.id, locale="en", now=NOW)
    remember = next(i for i in payload["items"] if i["kind"] == "remember")
    assert remember["text"] == "Bring the card."


async def test_another_mothers_profile_id_yields_nothing():
    """The id of a child that is not hers resolves to no profile, never to her whole record."""
    user_id = await make_user()
    other = await make_user()
    mine = await _well_vaccinated_child(user_id)
    hers = await _well_vaccinated_child(other)
    await _observe(user_id, mine.id, 37.8, NOW - timedelta(hours=2))
    await _observe(other, hers.id, 39.0, NOW - timedelta(hours=1))
    payload = await build_today(user_id=user_id, profile_id=hers.id, locale="es", now=NOW)
    assert payload == {"name": None, "items": []}


async def test_the_endpoint_answers_for_the_signed_in_mother_only(client):
    from adelia.auth import get_current_user_id
    from adelia.main import app

    user_id = await make_user()
    child = await _well_vaccinated_child(user_id)
    await _observe(user_id, child.id, 37.8, datetime.now(timezone.utc) - timedelta(hours=1))
    unauthenticated = await client.get("/today")
    assert unauthenticated.status_code == 401

    async def fake_user_id():
        return user_id

    app.dependency_overrides[get_current_user_id] = fake_user_id
    try:
        res = await client.get("/today", params={"locale": "es"})
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Nora"
    assert [i["kind"] for i in body["items"]] == ["observation"]
    # Not "hoy": the API reads the clock in Europe/Madrid and the row was
    # written an hour ago, which just after midnight is yesterday.
    assert body["items"][0]["text"].startswith("Temperatura: ") and "37,8 °C" in body["items"][0]["text"]
