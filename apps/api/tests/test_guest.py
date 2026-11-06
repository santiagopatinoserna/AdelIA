"""Guest accounts: the demo is the real app (decision of 2026-11-06).

Until that date the landing answered from an in-memory fixture and wrote
nothing. Santiago reversed it: a visitor uses the real panel with Lucía as her
child, everything she does is kept under her own guest account, she can save
it with an email or erase it, and none of it is shared with anybody else.
These tests hold the server to that, with no model call anywhere (CI has no
keys): the seed is the fixture's text, and the agent turns used here are red
flags, which the deterministic guard answers before any model.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from jose import jwt

from adelia import ratelimit
from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import (
    BlobTombstone, ChatMessage, ChatSession, Chunk, DemoSeedEmbedding, Document, Entity, GuestClaim,
    Observation, Profile, User,
)
from adelia.services import guest as guest_service

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE

pg_only = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

RED_FLAG = "Mi bebé ha convulsionado y no reacciona"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    # A deployment that sells: the guest's access must not depend on billing being off.
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_guest")


def _bearer(user_id) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "test-secret", algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


async def _new_guest(client, locale: str = "es") -> tuple[uuid.UUID, uuid.UUID]:
    with patch("adelia.services.guest.fill_seed_embeddings", return_value=0):
        resp = await client.post("/guest", json={"locale": locale})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return uuid.UUID(body["user_id"]), uuid.UUID(body["profile_id"])


async def _count(model, user_id) -> int:
    async with AsyncSessionLocal() as session:
        return await session.scalar(
            sa.select(sa.func.count()).select_from(model).where(model.user_id == user_id))


def _sse(text: str) -> list[tuple[str, dict]]:
    frames = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        event = next((ln[7:] for ln in block.splitlines() if ln.startswith("event: ")), None)
        data = next((ln[6:] for ln in block.splitlines() if ln.startswith("data: ")), None)
        if event:
            frames.append((event, json.loads(data) if data else {}))
    return frames


# --- Creation: Lucía, seeded as her own record, with access and no card --------


@pg_only
async def test_a_guest_gets_lucia_as_her_child_with_the_demo_story_as_real_rows(client):
    user_id, profile_id = await _new_guest(client)
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        profile = await session.get(Profile, profile_id)
        docs = (await session.execute(
            sa.select(Document).where(Document.user_id == user_id))).scalars().all()
    assert user.is_guest is True
    assert user.email.endswith("@guest.adelia.invalid")
    assert user.onboarded_at is not None, "a guest must never land on the onboarding screen"
    assert (profile.display_name, profile.relationship, profile.is_default) == (
        "Lucía", "child", True)
    age_days = (date.today() - profile.date_of_birth).days
    assert 5 * 30 <= age_days < 6 * 30, "Lucía is five months old whatever day it is"
    # The report, the blood test and the recorded appointment, all processed:
    # a seeded row without processed_at is requeued as a real pipeline at boot.
    assert sorted(d.source for d in docs) == ["consulta", "web", "web"]
    assert all(d.processed_at is not None and d.profile_id == profile_id for d in docs)
    assert await _count(Chunk, user_id) == 3
    assert await _count(Observation, user_id) >= 1
    async with AsyncSessionLocal() as session:
        names = set((await session.execute(
            sa.select(Entity.name).where(Entity.user_id == user_id))).scalars().all())
    assert {"Hemoglobina", "Ferritina", "Peso"} <= names


@pg_only
async def test_a_guest_uses_the_paid_product_without_a_card_or_an_end_date(client):
    user_id, _ = await _new_guest(client)
    async with AsyncSessionLocal() as session:
        # Far past the free trial: a guest's access does not run out.
        await session.execute(sa.update(User).where(User.id == user_id).values(
            created_at=datetime.now(timezone.utc) - timedelta(days=400)))
        await session.commit()
    status = (await client.get("/billing/status", headers=_bearer(user_id))).json()
    assert status["active"] is True and status["is_guest"] is True
    assert (await client.get("/users/me/onboarding", headers=_bearer(user_id))).json() == {
        "needed": False}
    turn = await client.post("/agent/turn", headers=_bearer(user_id),
                             json={"message": RED_FLAG, "locale": "es"})
    assert turn.status_code == 200, "the agent must not answer a guest with 402"


@pg_only
async def test_today_reads_lucias_seeded_record(client):
    user_id, profile_id = await _new_guest(client)
    resp = await client.get("/today", headers=_bearer(user_id),
                            params={"profile_id": str(profile_id), "locale": "es"})
    assert resp.status_code == 200
    body = json.dumps(resp.json(), ensure_ascii=False)
    assert "Lucía" in body
    assert "5 h" in body or "5h" in body, body


@pg_only
async def test_reused_vectors_come_from_the_template_and_no_model_runs_at_creation(client):
    """The texts are the same for every guest: a vector stored once is reused."""
    probe_user, _ = await _new_guest(client)
    async with AsyncSessionLocal() as session:
        keys = (await session.execute(
            sa.select(Chunk.chunk_metadata["seed_key"].astext).where(
                Chunk.user_id == probe_user))).scalars().all()
        for key in keys:
            await session.merge(DemoSeedEmbedding(content_sha256=key, embedding=[0.01] * 1024))
        await session.commit()
    with patch("adelia.workers.embed.embed_texts", side_effect=AssertionError("no model")):
        created = await guest_service.create_guest("es")
    assert created.missing_embeddings == {}
    async with AsyncSessionLocal() as session:
        missing = await session.scalar(
            sa.select(sa.func.count()).select_from(Chunk).where(
                Chunk.user_id == created.user_id, Chunk.embedding.is_(None)))
    assert missing == 0


# --- Isolation ---------------------------------------------------------------


@pg_only
async def test_one_guest_never_reads_or_writes_another_guests_vault(client):
    a, a_profile = await _new_guest(client)
    b, b_profile = await _new_guest(client)
    async with AsyncSessionLocal() as session:
        b_doc = await session.scalar(sa.select(Document.id).where(Document.user_id == b))
    assert (await client.get(f"/documents/{b_doc}", headers=_bearer(a))).status_code == 404
    assert (await client.delete(f"/documents/{b_doc}", headers=_bearer(a))).status_code == 404
    ids = {p["id"] for p in (await client.get(
        "/enrichment/profiles", headers=_bearer(a))).json()}
    assert str(a_profile) in ids and str(b_profile) not in ids
    listed = (await client.get("/documents", headers=_bearer(a))).json()
    assert str(b_doc) not in json.dumps(listed)
    # B's conversation is stored and A never gets it, even by naming it.
    await client.post("/agent/turn", headers=_bearer(b), json={"message": RED_FLAG})
    b_thread = (await client.get("/agent/thread", headers=_bearer(b))).json()["thread"]
    assert b_thread is not None
    await client.post("/agent/turn", headers=_bearer(a),
                      json={"message": RED_FLAG, "thread_id": b_thread["id"]})
    async with AsyncSessionLocal() as session:
        b_messages = await session.scalar(
            sa.select(sa.func.count()).select_from(ChatMessage).where(
                ChatMessage.session_id == uuid.UUID(b_thread["id"])))
    assert b_messages == 2, "A's turn must open her own thread, not write into B's"
    a_thread = (await client.get("/agent/thread", headers=_bearer(a))).json()["thread"]
    assert a_thread["id"] != b_thread["id"]


# --- The brake on creation -----------------------------------------------------


@pg_only
async def test_guest_creation_is_rate_limited_per_address(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    ratelimit.reset()
    codes = []
    with patch("adelia.services.guest.fill_seed_embeddings", return_value=0):
        for _ in range(6):
            codes.append((await client.post("/guest", json={"locale": "es"})).status_code)
    assert codes[:5] == [201] * 5 and codes[5] == 429


@pg_only
async def test_guest_creation_also_has_an_hourly_ceiling(client, monkeypatch):
    from adelia.routers import guest as guest_router

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(guest_router, "GUEST_SIGNUPS_PER_HOUR", 2)
    ratelimit.reset()
    with patch("adelia.services.guest.fill_seed_embeddings", return_value=0):
        codes = [(await client.post("/guest", json={})).status_code for _ in range(3)]
    assert codes == [201, 201, 429]


@pg_only
async def test_guest_creation_from_the_web_counts_the_mothers_address(client, monkeypatch):
    """POST /guest is called by the web server (lib/auth.ts, the "guest"
    provider), so the connection's peer is the web container for every mother.
    Behind Cloudflare the web forwards CF-Connecting-IP, and the brake must
    count that address: one mother's spent ceiling cannot lock out the next."""
    from adelia.routers import guest as guest_router

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "trust_cf_connecting_ip", True)
    monkeypatch.setattr(guest_router, "GUEST_SIGNUPS_PER_HOUR", 1)
    ratelimit.reset()
    first, second = {"CF-Connecting-IP": "203.0.113.7"}, {"CF-Connecting-IP": "198.51.100.9"}
    with patch("adelia.services.guest.fill_seed_embeddings", return_value=0):
        codes = [(await client.post("/guest", json={}, headers=h)).status_code
                 for h in (first, first, second)]
    assert codes == [201, 429, 201]


# --- "Guardar mi cuenta" --------------------------------------------------------


async def _account(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as session:
        user = User(email=email)
        session.add(user)
        await session.commit()
        return user.id


@pg_only
async def test_saving_the_account_moves_lucia_and_everything_she_did(client):
    guest, lucia = await _new_guest(client)
    await client.post("/agent/turn", headers=_bearer(guest), json={"message": RED_FLAG})
    email = f"madre-{uuid.uuid4()}@adelia.test"
    claim = await client.post("/guest/claim", headers=_bearer(guest), json={"email": email})
    assert claim.status_code == 200
    token = claim.json()["token"]
    # The magic link signs in (or creates) the account for that email.
    account = await _account(email)
    adopted = await client.post("/guest/adopt", headers=_bearer(account), json={"token": token})
    assert adopted.status_code == 200, adopted.text

    async with AsyncSessionLocal() as session:
        profile = await session.get(Profile, lucia)
        owner = await session.get(User, account)
        assert await session.get(User, guest) is None
    assert profile.user_id == account and profile.is_default is True
    assert owner.is_guest is False and owner.onboarded_at is not None
    assert await _count(Document, account) == 3
    assert await _count(Chunk, account) == 3
    assert await _count(Observation, account) >= 1
    assert await _count(ChatSession, account) == 1
    assert await _count(Document, guest) == 0
    thread = (await client.get("/agent/thread", headers=_bearer(account))).json()["thread"]
    assert thread["messages"][0]["content"] == RED_FLAG
    # The guest's own session dies with the guest row.
    assert (await client.get("/billing/status", headers=_bearer(guest))).status_code == 401


@pg_only
async def test_an_existing_account_keeps_its_own_baby_first(client):
    guest, lucia = await _new_guest(client)
    email = f"madre-{uuid.uuid4()}@adelia.test"
    account = await _account(email)
    async with AsyncSessionLocal() as session:
        own = Profile(user_id=account, display_name="Nora", relationship="child", is_default=True)
        session.add(own)
        await session.commit()
    token = (await client.post("/guest/claim", headers=_bearer(guest),
                               json={"email": email})).json()["token"]
    assert (await client.post("/guest/adopt", headers=_bearer(account),
                              json={"token": token})).status_code == 200
    async with AsyncSessionLocal() as session:
        assert (await session.get(Profile, own.id)).is_default is True
        assert (await session.get(Profile, lucia)).is_default is False


@pg_only
async def test_a_claim_only_works_for_the_email_it_names_and_before_it_expires(client):
    guest, _ = await _new_guest(client)
    email = f"madre-{uuid.uuid4()}@adelia.test"
    token = (await client.post("/guest/claim", headers=_bearer(guest),
                               json={"email": email})).json()["token"]
    stranger = await _account(f"otra-{uuid.uuid4()}@adelia.test")
    assert (await client.post("/guest/adopt", headers=_bearer(stranger),
                              json={"token": token})).status_code == 404
    owner = await _account(email)
    async with AsyncSessionLocal() as session:
        await session.execute(sa.update(GuestClaim).where(GuestClaim.guest_id == guest).values(
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        await session.commit()
    assert (await client.post("/guest/adopt", headers=_bearer(owner),
                              json={"token": token})).status_code == 404
    assert await _count(Document, guest) == 3, "a refused adoption moves nothing"


@pg_only
async def test_only_a_guest_can_claim_and_only_with_a_real_address(client):
    account = await make_user()
    assert (await client.post("/guest/claim", headers=_bearer(account),
                              json={"email": "a@b.es"})).status_code == 409
    guest, _ = await _new_guest(client)
    for bad in ("no-es-un-correo", f"x@{guest_service.GUEST_EMAIL_DOMAIN}"):
        assert (await client.post("/guest/claim", headers=_bearer(guest),
                                  json={"email": bad})).status_code == 422


# --- Erasure (GDPR art. 17) ----------------------------------------------------


@pg_only
async def test_deleting_a_guest_erases_everything_she_did(client):
    """Also her blobs. The seed writes documents with an s3_key and no blob
    (their text is in the row), and erasure tombstones every key. The sweep
    production spawns after the 204 must still clear them: deleting an object
    that does not exist is a success in S3, so a seeded key cannot wedge it.
    The sweep is run here by hand against the real storage, only on her keys;
    while it was patched out and never run, every run left due tombstones in
    the shared database for the next full sweep (test_audio_retention) to find."""
    from adelia.routers.users import sweep_blob_tombstones

    guest, lucia = await _new_guest(client)
    await client.post("/agent/turn", headers=_bearer(guest), json={"message": RED_FLAG})
    assert await _count(ChatSession, guest) == 1
    async with AsyncSessionLocal() as session:
        keys = list((await session.execute(
            sa.select(Document.s3_key).where(Document.user_id == guest))).scalars())
    assert keys, "the seed gives her documents"
    with patch("adelia.routers.users._spawn_erasure_sweep") as spawn:
        resp = await client.delete("/users/me", headers=_bearer(guest))
    assert resp.status_code == 204
    for model in (Document, Chunk, Entity, Observation, ChatSession, ChatMessage, Profile):
        assert await _count(model, guest) == 0, model.__tablename__
    async with AsyncSessionLocal() as session:
        assert await session.get(User, guest) is None
    assert sorted(spawn.call_args.args[0]) == sorted(keys)
    await sweep_blob_tombstones(keys=keys)
    async with AsyncSessionLocal() as session:
        left = (await session.execute(sa.select(sa.func.count()).select_from(BlobTombstone)
                                      .where(BlobTombstone.s3_key.in_(keys)))).scalar_one()
    assert left == 0


# --- The agent: red flag first, stored turns, follow-ups with context ----------


@pg_only
async def test_the_red_flag_still_answers_first_for_a_guest_and_is_stored(client):
    guest, lucia = await _new_guest(client)
    with patch("adelia.agent.orchestrator.get_provider",
               side_effect=AssertionError("a red flag must not reach a model")):
        resp = await client.post("/agent/turn", headers=_bearer(guest),
                                 json={"message": RED_FLAG, "profile_id": str(lucia)})
    frames = _sse(resp.text)
    answer = "".join(d.get("content", "") for e, d in frames if e == "token")
    assert "112" in answer
    thread_frames = [d for e, d in frames if e == "thread"]
    assert thread_frames and thread_frames[0]["thread_id"]
    thread = (await client.get("/agent/thread", headers=_bearer(guest),
                               params={"profile_id": str(lucia)})).json()["thread"]
    assert [m["role"] for m in thread["messages"]] == ["user", "assistant"]
    assert thread["messages"][1]["content"] == answer


@pg_only
async def test_a_follow_up_continues_the_same_thread_and_carries_the_history(client):
    """After an answer she keeps asking about the same thing: the second turn
    goes to the same stored conversation, and the history the browser sends
    reaches the graph."""
    guest, lucia = await _new_guest(client)
    first = _sse((await client.post("/agent/turn", headers=_bearer(guest),
                                    json={"message": RED_FLAG})).text)
    thread_id = next(d["thread_id"] for e, d in first if e == "thread")
    answer = "".join(d.get("content", "") for e, d in first if e == "token")

    seen: dict = {}
    from adelia.agent import orchestrator

    real = orchestrator.run_turn

    async def spy(**kwargs):
        seen.update(kwargs)
        async for event in real(**kwargs):
            yield event

    history = [{"role": "user", "content": RED_FLAG}, {"role": "assistant", "content": answer}]
    with patch("adelia.routers.agent.run_turn", spy):
        second = _sse((await client.post("/agent/turn", headers=_bearer(guest), json={
            # A red flag again, so the turn needs no model and is stored.
            "message": "Ahora ha convulsionado otra vez, ¿qué hago?",
            "thread_id": thread_id, "history": history})).text)
    assert seen["history"] == history
    assert not [d for e, d in second if e == "thread"], "same thread, no new id"
    thread = (await client.get("/agent/thread", headers=_bearer(guest))).json()["thread"]
    assert thread["id"] == thread_id and len(thread["messages"]) == 4


@pg_only
async def test_an_old_conversation_is_not_resumed_but_stays_in_the_history(client):
    guest, _ = await _new_guest(client)
    await client.post("/agent/turn", headers=_bearer(guest), json={"message": RED_FLAG})
    async with AsyncSessionLocal() as session:
        await session.execute(sa.update(ChatSession).where(ChatSession.user_id == guest).values(
            updated_at=datetime.now(timezone.utc) - timedelta(days=2)))
        await session.commit()
    assert (await client.get("/agent/thread", headers=_bearer(guest))).json() == {"thread": None}
    assert len((await client.get("/chat/sessions", headers=_bearer(guest))).json()) == 1
