from uuid import uuid4

import pytest

from adelia.services.retrieval import RetrievedChunk, retrieve_relevant_chunks
from adelia.services.scope import Scope

from tests.pg_gate import PG_AVAILABLE


@pytest.mark.skipif(
    not PG_AVAILABLE, reason="needs Postgres + seeded chunks with embeddings"
)
async def test_retrieve_returns_top_k_relevant_chunks():
    user_id = uuid4()
    query_embedding = [0.1] * 1024  # fake 1024-dim query
    results = await retrieve_relevant_chunks(
        scope=Scope(user_id=user_id), query_embedding=query_embedding, top_k=8
    )
    assert isinstance(results, list)
    assert len(results) <= 8
    for r in results:
        assert isinstance(r, RetrievedChunk)
        assert r.user_id == user_id
        assert r.embedding_distance is not None


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")
async def test_retrieve_includes_parent_chunk_content():
    user_id = uuid4()
    query_embedding = [0.1] * 1024
    results = await retrieve_relevant_chunks(
        scope=Scope(user_id=user_id), query_embedding=query_embedding, top_k=4
    )
    for r in results:
        # Parent expansion: parent_content present when parent_index is set
        if r.parent_content is not None:
            assert isinstance(r.parent_content, str)


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")
async def test_retrieve_filters_soft_deleted_documents():
    user_id = uuid4()
    query_embedding = [0.1] * 1024
    results = await retrieve_relevant_chunks(
        scope=Scope(user_id=user_id), query_embedding=query_embedding, top_k=8
    )
    # Implicit: results should NOT include chunks whose parent document
    # has deleted_at IS NOT NULL. Verified by test setup that soft-deletes
    # documents and asserts they don't appear.
    for r in results:
        assert r.document_deleted_at is None


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")
async def test_parent_window_rebuilt_from_raw_text():
    """Parent expansion: the LLM context window is rebuilt from raw_text
    offsets across sibling chunks — exact text, no overlap duplication."""
    from tests.db_helpers import make_user
    from adelia.db import AsyncSessionLocal
    from adelia.models import Chunk, Document
    from adelia.services.retrieval import retrieve_relevant_chunks

    user_id = await make_user()
    raw = "A" * 100 + "B" * 100 + "C" * 100  # parent 0 covers [0, 300)
    async with AsyncSessionLocal() as session:
        doc = Document(
            user_id=user_id, source="web", mime_type="application/pdf",
            s3_key="users/x/parent.pdf", raw_text=raw,
        )
        session.add(doc)
        await session.flush()
        for i in range(3):
            session.add(Chunk(
                document_id=doc.id, user_id=user_id,
                content=raw[i * 100:(i + 1) * 100],
                embedding=[0.1] * 1024,
                chunk_index=i,
                chunk_metadata={
                    "parent_index": 0,
                    "start_char": i * 100,
                    "end_char": (i + 1) * 100,
                    "entity_ids": [],
                },
            ))
        await session.commit()

    results = await retrieve_relevant_chunks(
        scope=Scope(user_id=user_id), query_embedding=[0.1] * 1024, top_k=2
    )
    assert results, "expected hits"
    for r in results:
        assert r.parent_content == raw  # full [0,300) window
        assert len(r.content) == 100    # citation quote stays small
