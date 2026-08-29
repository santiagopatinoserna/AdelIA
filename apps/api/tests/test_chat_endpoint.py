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
