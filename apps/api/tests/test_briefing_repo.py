"""briefing_repo CRUD tests. PG-gated until env-var migration in v0.1.1."""
from __future__ import annotations


import pytest

from adelia.schemas import Specialty

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres")
@pytest.mark.asyncio
async def test_create_briefing_returns_processing_status():
    from adelia.db import AsyncSessionLocal
    from adelia.services import briefing_repo

    user_id = await make_user()
    async with AsyncSessionLocal() as session:
        briefing = await briefing_repo.create_briefing(
            session, user_id=user_id, target_specialty=Specialty.ENDOCRINOLOGY
        )
        await session.commit()
        assert briefing.status == "processing"
        assert briefing.is_stale is False
        assert briefing.target_specialty == "endocrinology"


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required")
@pytest.mark.asyncio
async def test_get_by_id_returns_briefing_for_owner():
    from adelia.db import AsyncSessionLocal
    from adelia.services import briefing_repo

    user_id = await make_user()
    async with AsyncSessionLocal() as session:
        created = await briefing_repo.create_briefing(
            session, user_id=user_id, target_specialty=Specialty.DEFAULT
        )
        await session.commit()
        fetched = await briefing_repo.get_by_id(session, briefing_id=created.id, user_id=user_id)
        assert fetched is not None
        assert fetched.id == created.id


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required")
@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_cross_user():
    from adelia.db import AsyncSessionLocal
    from adelia.services import briefing_repo

    owner = await make_user()
    other = await make_user()
    async with AsyncSessionLocal() as session:
        created = await briefing_repo.create_briefing(
            session, user_id=owner, target_specialty=Specialty.DEFAULT
        )
        await session.commit()
        fetched = await briefing_repo.get_by_id(session, briefing_id=created.id, user_id=other)
        assert fetched is None


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required")
@pytest.mark.asyncio
async def test_list_for_user_returns_only_owned():
    from adelia.db import AsyncSessionLocal
    from adelia.services import briefing_repo

    a, b = await make_user(), await make_user()
    async with AsyncSessionLocal() as session:
        await briefing_repo.create_briefing(session, user_id=a, target_specialty=Specialty.DEFAULT)
        await briefing_repo.create_briefing(session, user_id=a, target_specialty=Specialty.CARDIOLOGY)
        await briefing_repo.create_briefing(session, user_id=b, target_specialty=Specialty.DEFAULT)
        await session.commit()
        a_list = await briefing_repo.list_for_user(session, user_id=a)
        assert len(a_list) == 2


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required")
@pytest.mark.asyncio
async def test_mark_stale_updates_older_briefings():
    from datetime import datetime, UTC, timedelta
    from adelia.db import AsyncSessionLocal
    from adelia.services import briefing_repo

    user_id = await make_user()
    async with AsyncSessionLocal() as session:
        b1 = await briefing_repo.create_briefing(session, user_id=user_id, target_specialty=Specialty.DEFAULT)
        await session.commit()
        await briefing_repo.mark_stale_for_user(session, user_id=user_id, since=datetime.now(UTC) + timedelta(seconds=1))
        await session.commit()
        fetched = await briefing_repo.get_by_id(session, briefing_id=b1.id, user_id=user_id)
        assert fetched.is_stale is True


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required")
@pytest.mark.asyncio
async def test_update_payload_and_status_transitions_to_ready():
    from datetime import datetime, UTC
    from adelia.db import AsyncSessionLocal
    from adelia.schemas import (
        AppliedFilter,
        BriefingPayload,
        BriefingSections,
        LLMMeta,
        PatientHeader,
    )
    from adelia.services import briefing_repo

    user_id = await make_user()
    async with AsyncSessionLocal() as session:
        b = await briefing_repo.create_briefing(
            session, user_id=user_id, target_specialty=Specialty.DEFAULT
        )
        payload = BriefingPayload(
            schema_version="1.0",
            generated_at=datetime.now(UTC),
            target_specialty=Specialty.DEFAULT,
            patient=PatientHeader(name="x", age=1, sex="?"),
            sections=BriefingSections(
                reason_for_consult=None,
                active_problems=[],
                medications=[],
                allergies="no_known_allergies",
                immunizations=None,
                procedures=[],
                family_history=None,
                relevant_observations=[],
                open_questions=[],
            ),
            applied_filter=AppliedFilter(specialty="default", rules_version="1.0"),
            llm_meta=LLMMeta(model="test", tokens_used=0, cost_estimate_usd=0.0),
        )
        await briefing_repo.update_payload_html_status(
            session,
            briefing_id=b.id,
            payload=payload,
            html_render="<html></html>",
            status="ready",
            error_message=None,
        )
        await session.commit()
        fetched = await briefing_repo.get_by_id(session, briefing_id=b.id, user_id=user_id)
        assert fetched.status == "ready"
        assert fetched.html_render == "<html></html>"
        assert fetched.completed_at is not None
