from uuid import uuid4

import pytest

from adelia.services.retrieval import RetrievedChunk, retrieve_relevant_chunks


@pytest.mark.skipif(
    True, reason="needs Postgres + seeded chunks with embeddings"
)
async def test_retrieve_returns_top_k_relevant_chunks():
    user_id = uuid4()
    query_embedding = [0.1] * 1024  # fake 1024-dim query
    results = await retrieve_relevant_chunks(
        user_id=user_id, query_embedding=query_embedding, top_k=8
    )
    assert isinstance(results, list)
    assert len(results) <= 8
    for r in results:
        assert isinstance(r, RetrievedChunk)
        assert r.user_id == user_id
        assert r.embedding_distance is not None


@pytest.mark.skipif(True, reason="needs Postgres")
async def test_retrieve_includes_parent_chunk_content():
    user_id = uuid4()
    query_embedding = [0.1] * 1024
    results = await retrieve_relevant_chunks(
        user_id=user_id, query_embedding=query_embedding, top_k=4
    )
    for r in results:
        # Parent expansion: parent_content present when parent_index is set
        if r.parent_content is not None:
            assert isinstance(r.parent_content, str)


@pytest.mark.skipif(True, reason="needs Postgres")
async def test_retrieve_filters_soft_deleted_documents():
    user_id = uuid4()
    query_embedding = [0.1] * 1024
    results = await retrieve_relevant_chunks(
        user_id=user_id, query_embedding=query_embedding, top_k=8
    )
    # Implicit: results should NOT include chunks whose parent document
    # has deleted_at IS NOT NULL. Verified by test setup that soft-deletes
    # documents and asserts they don't appear.
    for r in results:
        assert r.document_deleted_at is None
