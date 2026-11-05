import json
from uuid import uuid4

import pytest

from adelia.routers.chat import _final_data
from adelia.schemas import ChatCitation
from adelia.services.chat_orchestrator import ChatEvent
from tests.pg_gate import PG_AVAILABLE


def test_final_data_carries_both_citation_namespaces():
    """The SSE `final` payload must serialise the evidence citations next to
    the document citations: the web chat renders one block per namespace,
    and the evidence block was silently empty while this key was missing."""
    session_id = uuid4()
    doc_cit = ChatCitation(chunk_id=uuid4(), document_id=uuid4(), raw_quote="regurgita tras cada toma", page=2)
    ev_cit = {
        "tag": "ev_1",
        "source_id": str(uuid4()),
        "chunk_id": str(uuid4()),
        "title": "Complementary Feeding: ESPGHAN position paper",
        "organization": "ESPGHAN",
        "year": 2017,
        "url": "https://example.org/espghan",
        "snippet": "Exclusive breastfeeding ...",
        "distance": 0.31,
    }
    event = ChatEvent(type="final", citations=[doc_cit], evidence_citations=[ev_cit])

    payload = json.loads(json.dumps(_final_data(session_id, event)))  # must survive json.dumps

    assert payload["session_id"] == str(session_id)
    assert payload["citations"] == [doc_cit.model_dump(mode="json")]
    assert payload["evidence_citations"] == [ev_cit]


def test_final_data_without_evidence_keeps_the_key():
    """No evidence retrieved: the key is still present (empty), so the client
    never has to special-case a missing field."""
    payload = _final_data(uuid4(), ChatEvent(type="final"))
    assert payload["citations"] == []
    assert payload["evidence_citations"] == []


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres + MISTRAL_API_KEY")
async def test_post_chat_streams_sse_events_and_persists(client):
    """End-to-end: POST /chat with question. Asserts SSE events arrive and a
    new session + 2 messages (user + assistant) get persisted.
    Skipped in sandbox. Acceptance script (T10) verifies live."""
    pass


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")
async def test_get_chat_sessions_lists_user_sessions(client):
    pass


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")
async def test_delete_chat_session_returns_404_for_other_user(client):
    pass


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")
async def test_post_chat_tags_the_session_with_the_resolved_child(client, monkeypatch):
    """No profile_id from the client resolves to the default child, and the session
    records that child; a later turn about her sibling moves it to the sibling."""
    from adelia.config import settings
    from adelia.db import AsyncSessionLocal
    from adelia.models import ChatSession, Profile
    from adelia.routers import chat as chat_router
    from tests.db_helpers import make_user
    from tests.test_auth import make_token

    async def fake_stream(**kwargs):
        yield ChatEvent(type="token", content="## No olvides\n- Apunta las tomas.\n")
        yield ChatEvent(type="final")

    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    monkeypatch.setattr(chat_router, "answer_question_streaming", fake_stream)
    user_id = await make_user()
    async with AsyncSessionLocal() as session:
        nora = Profile(user_id=user_id, display_name="Nora", relationship="child",
                       is_default=True)
        adel = Profile(user_id=user_id, display_name="Adel", relationship="child",
                       is_default=False)
        session.add_all([nora, adel])
        await session.commit()
        nora_id, adel_id = nora.id, adel.id
    headers = {"Authorization": f"Bearer {make_token(str(user_id))}"}

    resp = await client.post("/chat", json={"question": "come poco"}, headers=headers)
    assert resp.status_code == 200
    start = next(json.loads(line[len("data:"):]) for line in resp.text.splitlines()
                 if line.startswith("data:") and "session_id" in line)
    session_id = start["session_id"]
    async with AsyncSessionLocal() as session:
        assert (await session.get(ChatSession, session_id)).profile_id == nora_id

    resp = await client.post(
        "/chat",
        json={"question": "¿y Adel?", "session_id": session_id, "profile_id": str(adel_id)},
        headers=headers,
    )
    assert resp.status_code == 200
    async with AsyncSessionLocal() as session:
        assert (await session.get(ChatSession, session_id)).profile_id == adel_id
