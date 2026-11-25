"""`GET /history`: one child's record, a month at a time, for Historial.

docs/specs/ADELIA_SIMPLE.md puts it first: what she noted, her documents and her
recordings in one list, per child, since birth. Until 2026-11-25 Historial
listed the account's documents only, and a note confirmed in the panel came back
through a question and nowhere else. These pin the read: one list by day, newest
first, in the confirmation card's words and in Madrid's days, month by month back
to the month she was born, one child at a time, and open to her after her
subscription lapsed (her own record, tests/test_subscription_gate FREE_ROUTES).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from adelia.agent.graph import LOCAL_TZ
from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import Document, Profile
from adelia.routers.history import DOCUMENT_FIELDS
from adelia.services.observations import add_observation

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE
from tests.test_auth import make_token

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

BORN = date(2026, 7, 10)


@pytest.fixture(autouse=True)
def _signed_and_selling(monkeypatch):
    """Tokens signed with a known secret, and a deployment that sells: with no
    Stripe key every account passes the gate and the lapsed case proves nothing."""
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_gate")


def _madrid(*args) -> datetime:
    return datetime(*args, tzinfo=LOCAL_TZ)


async def _child(user_id, name="Nora", *, default=True) -> Profile:
    async with AsyncSessionLocal() as session:
        profile = Profile(user_id=user_id, display_name=name, relationship="child",
                          date_of_birth=BORN, is_default=default)
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
        return profile


async def _note(user_id, profile_id, at, *, kind="temperature", value: float | None = 37.8,
                unit: str | None = "°C", text="37,8", timed=True):
    async with AsyncSessionLocal() as session:
        await add_observation(session, user_id=user_id, profile_id=profile_id, kind=kind,
                              value=value, unit=unit, text=text, observed_at=at,
                              source="agent", timed=timed)
        await session.commit()


async def _document(user_id, profile_id, at, *, name="analitica.pdf", source="web",
                    mime="application/pdf", deleted=False) -> Document:
    # processed_at set: an unprocessed row is requeued as a real pipeline by the
    # next app boot (CLAUDE.md, the shared dev database).
    async with AsyncSessionLocal() as session:
        doc = Document(user_id=user_id, profile_id=profile_id, source=source, mime_type=mime,
                       s3_key=f"users/{user_id}/{uuid4()}-{name}",
                       raw_text="texto de la analítica " * 50, processed_at=at,
                       created_at=at, deleted_at=at if deleted else None)
        session.add(doc)
        await session.commit()
        await session.refresh(doc)
        return doc


def _auth(user_id) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(str(user_id))}"}


async def test_notes_documents_and_recordings_in_one_list_by_day_newest_first(client):
    user_id = await make_user()
    nora = await _child(user_id)
    await _note(user_id, nora.id, _madrid(2026, 11, 20, 9, 0), kind="feed", value=120.0,
                unit="ml", text="ha tomado 120 ml")
    await _note(user_id, nora.id, _madrid(2026, 11, 20, 16, 10))
    await _note(user_id, nora.id, _madrid(2026, 11, 20, 12, 0), kind="weight", value=6.2,
                unit="kg", text="hoy la han pesado, 6,2", timed=False)
    await _note(user_id, nora.id, _madrid(2026, 11, 19, 22, 0), kind="symptom", value=None,
                unit=None, text="tos  por la\nnoche")
    report = await _document(user_id, nora.id, _madrid(2026, 11, 20, 10, 30))
    consult = await _document(user_id, nora.id, _madrid(2026, 11, 19, 18, 0),
                              name="consulta.webm", source="consulta", mime="audio/webm")

    res = await client.get("/history", params={"locale": "es"}, headers=_auth(user_id))

    assert res.status_code == 200
    body = res.json()
    assert (body["name"], body["profile_id"]) == ("Nora", str(nora.id))
    assert body["month"] == "2026-11" and body["months"] == ["2026-11"]
    assert [d["day"] for d in body["days"]] == ["2026-11-20", "2026-11-19"]
    day20, day19 = body["days"]
    # The card's words under the day, with her hour; the weighing she gave no
    # hour reads without one, after the day's timed entries.
    assert [(n["time"], n["text"]) for n in day20["notes"]] == [
        ("16:10", "Temperatura: 37,8 °C"),
        ("09:00", "Toma: 120 ml"),
        (None, "Peso: 6,2 kg"),
    ]
    # With no number, what she said: "Síntoma" alone would lose the note.
    assert [(n["time"], n["text"]) for n in day19["notes"]] == [
        ("22:00", "Síntoma: tos por la noche")]
    assert [d["id"] for d in day20["documents"]] == [str(report.id)]
    assert [d["id"] for d in day19["documents"]] == [str(consult.id)]
    # A row of the list, not the document: its text stays on its own page.
    assert set(day20["documents"][0]) == DOCUMENT_FIELDS
    assert day20["documents"][0]["file_name"] == "analitica.pdf"
    assert day20["documents"][0]["status"] == "ready"
    assert day19["documents"][0]["source"] == "consulta"

    fr = (await client.get("/history", params={"locale": "fr"}, headers=_auth(user_id))).json()
    # French puts a no-break space before the unit, as the card does.
    assert fr["days"][0]["notes"][0]["text"] == "Température : 37,8\u00a0°C"


async def test_days_and_months_are_madrids(client):
    """00:30 in Madrid on 1 November is 23:30 UTC on 31 October: the note is
    November's, on its own day, as the web prints it (lib/dates APP_TIME_ZONE)."""
    user_id = await make_user()
    nora = await _child(user_id)
    await _note(user_id, nora.id, datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc))

    body = (await client.get("/history", headers=_auth(user_id))).json()

    assert body["months"] == ["2026-11"]
    assert [(d["day"], d["notes"][0]["time"]) for d in body["days"]] == [("2026-11-01", "00:30")]


async def test_months_name_what_holds_something_back_to_the_day_she_was_born(client):
    user_id = await make_user()
    nora = await _child(user_id)
    await _note(user_id, nora.id, _madrid(2026, 7, 10, 12, 0), kind="weight", value=3.2,
                unit="kg", text="al nacer pesó 3,2 kg", timed=False)
    await _note(user_id, nora.id, _madrid(2026, 11, 20, 16, 10))

    newest = (await client.get("/history", headers=_auth(user_id))).json()
    born = (await client.get("/history", params={"month": "2026-07"},
                             headers=_auth(user_id))).json()
    quiet = (await client.get("/history", params={"month": "2026-09"},
                              headers=_auth(user_id))).json()

    # No page per empty month: the month she was born is one tap from the newest.
    assert newest["months"] == ["2026-11", "2026-07"]
    assert newest["month"] == "2026-11"
    assert [d["day"] for d in newest["days"]] == ["2026-11-20"]
    assert born["month"] == "2026-07"
    assert [(d["day"], [(n["time"], n["text"]) for n in d["notes"]]) for d in born["days"]] == [
        ("2026-07-10", [(None, "Peso: 3,2 kg")])]
    assert quiet["month"] == "2026-09" and quiet["days"] == []
    assert quiet["months"] == newest["months"]


async def test_a_sibling_never_shares_the_list(client):
    user_id = await make_user()
    nora = await _child(user_id, "Nora", default=True)
    adel = await _child(user_id, "Adel", default=False)
    await _note(user_id, nora.id, _madrid(2026, 11, 20, 9, 0), value=37.1, text="37,1")
    await _note(user_id, adel.id, _madrid(2026, 11, 20, 10, 0), value=39.0, text="39")
    # Filed before profiles existed: every child shows it, as GET /documents does.
    legacy = await _document(user_id, None, _madrid(2026, 11, 18, 11, 0))

    default = (await client.get("/history", headers=_auth(user_id))).json()
    as_adel = (await client.get("/history", params={"profile_id": str(adel.id)},
                                headers=_auth(user_id))).json()

    def lines(body):
        return [n["text"] for d in body["days"] for n in d["notes"]]

    def docs(body):
        return [doc["id"] for d in body["days"] for doc in d["documents"]]

    # No profile is the default child, the one she picked last, not the account.
    assert (default["name"], lines(default)) == ("Nora", ["Temperatura: 37,1 °C"])
    assert (as_adel["name"], lines(as_adel)) == ("Adel", ["Temperatura: 39 °C"])
    assert docs(default) == docs(as_adel) == [str(legacy.id)]


async def test_another_mothers_child_reads_nothing(client):
    mine = await make_user()
    other = await make_user()
    hers = await _child(other, "Lía")
    await _note(other, hers.id, _madrid(2026, 11, 20, 9, 0))

    res = await client.get("/history", params={"profile_id": str(hers.id)},
                           headers=_auth(mine))

    assert res.status_code == 200
    assert res.json() == {"profile_id": None, "name": None, "month": None, "months": [],
                          "days": []}


async def test_a_deleted_document_is_gone_from_the_list_and_its_month(client):
    user_id = await make_user()
    nora = await _child(user_id)
    await _document(user_id, nora.id, _madrid(2026, 10, 3, 9, 0), deleted=True)
    await _note(user_id, nora.id, _madrid(2026, 11, 20, 9, 0))

    body = (await client.get("/history", params={"month": "2026-10"},
                             headers=_auth(user_id))).json()

    assert body["months"] == ["2026-11"]
    assert body["days"] == []


async def test_the_paywall_does_not_lock_her_own_record(client):
    """A lapsed subscription keeps reading what she noted and filed, like
    GET /documents: the gate is for what spends money."""
    lapsed = await make_user(subscription_status="canceled", created_days_ago=365)
    nora = await _child(lapsed)
    await _note(lapsed, nora.id, _madrid(2026, 11, 20, 9, 0))

    assert (await client.get("/history")).status_code == 401
    res = await client.get("/history", headers=_auth(lapsed))
    assert res.status_code == 200
    assert [n["text"] for d in res.json()["days"] for n in d["notes"]] == [
        "Temperatura: 37,8 °C"]
    # Control: the same account IS refused where money is spent.
    assert (await client.post("/agent/turn", headers=_auth(lapsed), json={})).status_code == 402


@pytest.mark.parametrize("month", ["2026-13", "2026-00", "nov", "2026-1", "2026-11-01"])
async def test_a_month_that_is_not_one_is_refused(client, month):
    user_id = await make_user()
    res = await client.get("/history", params={"month": month}, headers=_auth(user_id))
    assert res.status_code == 422
