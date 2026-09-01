"""Two children, one account: nothing of profile B may reach an answer,
a document list or a briefing about profile A (audit 4.1).

`profile_id` was written on documents, entities, chunks and briefings and read
by no query, so the vault of a mother with two children was one merged vault.
These tests are the regression: they seed two real profiles with real rows and
assert on what comes back, not on the shape of a SQL string.

Backward compatibility is asserted too, because it is the part that is easy to
break while fixing the leak: a row with `profile_id IS NULL` (everything
written before profiles existed, and everything an unscoped surface still
writes) must stay visible under every profile.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from adelia.services.scope import Scope

from tests.pg_gate import PG_AVAILABLE

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")


# Two orthogonal 1024-dim vectors: a query aimed at one is maximally far from
# the other, so if profile B's chunk ever came back it would be on merit of
# the filter failing, not of a lucky distance.
VEC_A = [1.0] + [0.0] * 1023
VEC_B = [0.0, 1.0] + [0.0] * 1022


async def _seed_two_children():
    """One user, profiles A and B, each with a document + chunk + entity,
    plus one legacy row belonging to neither."""
    from adelia.db import AsyncSessionLocal
    from adelia.enrichment import profile_service
    from adelia.models import Chunk, Document, Entity

    from tests.db_helpers import make_user

    user_id = await make_user()
    async with AsyncSessionLocal() as session:
        a = await profile_service.create_profile(
            session,
            user_id=user_id,
            data=profile_service.ProfileCreate(
                display_name="Adel", relationship="child",
                date_of_birth=date(2025, 3, 1), sex="M", is_default=True,
            ),
        )
        b = await profile_service.create_profile(
            session,
            user_id=user_id,
            data=profile_service.ProfileCreate(
                display_name="Nora", relationship="child",
                date_of_birth=date(2021, 3, 1), sex="F",
            ),
        )
        await session.commit()
        a_id, b_id = a.id, b.id

    docs: dict[str, object] = {}
    async with AsyncSessionLocal() as session:
        for tag, profile_id, vector, quote in (
            ("A", a_id, VEC_A, "Peso de Adel 7,2 kg el 12 de agosto."),
            ("B", b_id, VEC_B, "Peso de Nora 16,4 kg el 12 de agosto."),
            ("legacy", None, VEC_A, "Peso registrado 5,0 kg antes de los perfiles."),
        ):
            doc = Document(
                id=uuid4(), user_id=user_id, profile_id=profile_id, source="web",
                mime_type="application/pdf", s3_key=f"users/{user_id}/{tag}.pdf",
                raw_text=quote,
            )
            session.add(doc)
            await session.flush()
            session.add(Chunk(
                document_id=doc.id, user_id=user_id, profile_id=profile_id,
                content=quote, embedding=vector, chunk_index=0,
                chunk_metadata={"entity_ids": []},
            ))
            session.add(Entity(
                user_id=user_id, profile_id=profile_id, document_id=doc.id,
                entity_type="observation", name=f"peso {tag}",
                value={"value": 7.2, "unit": "kg"}, event_date=date(2026, 8, 12),
                raw_quote=quote, status="active",
                provenance="extracted_from_clinician_doc", confidence=0.9,
            ))
            docs[tag] = doc.id
        await session.commit()
    return user_id, a_id, b_id, docs


async def test_retrieval_returns_no_chunk_of_the_other_child():
    from adelia.services.retrieval import retrieve_relevant_chunks

    user_id, a_id, b_id, docs = await _seed_two_children()

    # The query vector points AT profile B's chunk. Unscoped it would be the
    # first hit; scoped to A it must not appear at all.
    results = await retrieve_relevant_chunks(
        scope=Scope(user_id=user_id, profile_id=a_id),
        query_embedding=VEC_B,
        top_k=8,
        max_distance=float("inf"),
    )
    returned_docs = {r.document_id for r in results}
    assert docs["B"] not in returned_docs, "profile B's chunk leaked into A's answer"
    assert docs["A"] in returned_docs
    # Pre-profile rows are still the user's own history, not another child's.
    assert docs["legacy"] in returned_docs


async def test_retrieval_without_a_profile_still_sees_everything():
    """A v0.1 account (no profile at all) keeps the old behaviour."""
    from adelia.services.retrieval import retrieve_relevant_chunks

    user_id, a_id, b_id, docs = await _seed_two_children()
    results = await retrieve_relevant_chunks(
        scope=Scope(user_id=user_id),
        query_embedding=VEC_B,
        top_k=8,
        max_distance=float("inf"),
    )
    returned_docs = {r.document_id for r in results}
    assert {docs["A"], docs["B"], docs["legacy"]} <= returned_docs


async def test_structured_query_returns_no_entity_of_the_other_child():
    from adelia.services.structured_query import (
        query_observations_by_name_and_date_range,
    )

    user_id, a_id, b_id, _docs = await _seed_two_children()
    rows = await query_observations_by_name_and_date_range(
        scope=Scope(user_id=user_id, profile_id=a_id),
        name_substring="peso",
        from_date=None,
        to_date=None,
    )
    names = {r["name"] for r in rows}
    assert "peso B" not in names, "profile B's observation leaked into A's answer"
    assert names == {"peso A", "peso legacy"}


async def test_document_list_narrows_to_the_requested_child():
    """GET /documents?profile_id=A hides B and keeps the unassigned rows."""
    from httpx import ASGITransport, AsyncClient

    from adelia.auth import get_current_user_id
    from adelia.main import app

    user_id, a_id, b_id, docs = await _seed_two_children()
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            scoped = await ac.get("/documents", params={"profile_id": str(a_id)})
            everything = await ac.get("/documents")
            foreign = await ac.get("/documents", params={"profile_id": str(uuid4())})
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)

    assert scoped.status_code == 200
    scoped_ids = {d["id"] for d in scoped.json()}
    assert str(docs["B"]) not in scoped_ids
    assert {str(docs["A"]), str(docs["legacy"])} <= scoped_ids
    # Unfiltered stays the whole account: this list is also the GDPR view.
    assert str(docs["B"]) in {d["id"] for d in everything.json()}
    # Someone else's profile id is an opaque 404, never a silent empty list.
    assert foreign.status_code == 404


async def test_briefing_of_one_child_never_mentions_the_other():
    """The briefing is the artefact a parent prints and hands to a
    paediatrician, so this asserts on the rendered HTML, not on an
    intermediate list."""
    from adelia.schemas import LLMMeta, Specialty
    from adelia.services import briefing_orchestrator

    user_id, a_id, b_id, _docs = await _seed_two_children()

    captured: dict[str, str] = {}

    async def _fake_bake(**kwargs):
        captured["entities_text"] = kwargs["entities_text"]
        captured["sources"] = " ".join(kwargs["source_raw_texts"].values())
        return [], LLMMeta(model="m", tokens_used=1, cost_estimate_usd=0.0)

    with patch.object(
        briefing_orchestrator, "bake_questions", new=AsyncMock(side_effect=_fake_bake)
    ), patch.object(
        briefing_orchestrator, "_retrieve_specialty_evidence",
        new=AsyncMock(return_value=("", [])),
    ), patch.object(
        briefing_orchestrator, "_persist_briefing_status", new_callable=AsyncMock
    ) as persist:
        await briefing_orchestrator.run(
            briefing_id=uuid4(),
            user_id=user_id,
            target_specialty=Specialty.PEDIATRICS,
            profile_id=a_id,
        )

    kwargs = persist.call_args.kwargs
    assert kwargs["status"] == "ready", kwargs["error_message"]
    html = kwargs["html_render"] or ""
    payload = kwargs["payload"]

    assert payload.patient.name == "Adel"
    for surface in (html, captured["entities_text"], captured["sources"]):
        assert "Nora" not in surface, "the other child reached the briefing"
        assert "16,4" not in surface
    assert "Adel" in captured["entities_text"]
    # The pre-profile row is this child's own history and stays in.
    assert "antes de los perfiles" in captured["sources"]


async def test_briefing_row_records_which_child_it_is_about():
    """So a regenerate six weeks later rebuilds the same child's briefing."""
    from adelia.db import AsyncSessionLocal
    from adelia.models import Briefing
    from adelia.schemas import Specialty
    from adelia.services import briefing_repo

    user_id, a_id, _b_id, _docs = await _seed_two_children()
    async with AsyncSessionLocal() as session:
        created = await briefing_repo.create_briefing(
            session, user_id=user_id, target_specialty=Specialty.PEDIATRICS,
            profile_id=a_id,
        )
        await session.commit()
        briefing_id = created.id

    async with AsyncSessionLocal() as session:
        stored = await session.get(Briefing, briefing_id)
        assert stored is not None
        assert stored.profile_id == a_id


async def test_create_briefing_rejects_a_profile_of_another_account():
    from httpx import ASGITransport, AsyncClient

    from adelia.auth import get_current_user_id, require_active_subscription
    from adelia.main import app

    from tests.db_helpers import make_user

    _owner, a_id, _b_id, _docs = await _seed_two_children()
    intruder = await make_user()

    # /briefings is behind the paywall, so both dependencies are overridden;
    # the point under test is the ownership check, not the subscription.
    app.dependency_overrides[get_current_user_id] = lambda: intruder
    app.dependency_overrides[require_active_subscription] = lambda: intruder
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(
                "/briefings",
                json={"target_specialty": "pediatrics", "profile_id": str(a_id)},
            )
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
        app.dependency_overrides.pop(require_active_subscription, None)

    assert res.status_code == 404
