"""profile_service tests. PG-gated until env-var migration in v0.2.1."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from adelia.enrichment.profile_service import ProfileCreate


@pytest.mark.skipif(True, reason="PG required — run locally with docker compose up")
@pytest.mark.asyncio
async def test_ensure_default_profile_idempotent():
    from adelia.db import AsyncSessionLocal
    from adelia.enrichment import profile_service

    user_id = uuid4()
    async with AsyncSessionLocal() as session:
        a = await profile_service.ensure_default_profile(session, user_id=user_id)
        await session.commit()
        b = await profile_service.ensure_default_profile(session, user_id=user_id)
        await session.commit()
        assert a.id == b.id
        assert a.is_default is True


@pytest.mark.skipif(True, reason="PG required")
@pytest.mark.asyncio
async def test_create_additional_profile():
    from adelia.db import AsyncSessionLocal
    from adelia.enrichment import profile_service

    user_id = uuid4()
    from datetime import date
    async with AsyncSessionLocal() as session:
        await profile_service.ensure_default_profile(session, user_id=user_id)
        child = await profile_service.create_profile(
            session,
            user_id=user_id,
            data=ProfileCreate(
                display_name="Diego (hijo)",
                relationship="child",
                date_of_birth=date(2018, 6, 15),
                sex="M",
            ),
        )
        await session.commit()
        assert child.relationship == "child"
        assert child.is_default is False


@pytest.mark.skipif(True, reason="PG required")
@pytest.mark.asyncio
async def test_set_default_demotes_previous():
    from adelia.db import AsyncSessionLocal
    from adelia.enrichment import profile_service

    user_id = uuid4()
    async with AsyncSessionLocal() as session:
        first = await profile_service.ensure_default_profile(session, user_id=user_id)
        second = await profile_service.create_profile(
            session,
            user_id=user_id,
            data=ProfileCreate(display_name="Other", relationship="other"),
        )
        await session.commit()

        # Promote second to default
        promoted = await profile_service.set_default_profile(
            session, profile_id=second.id, user_id=user_id
        )
        await session.commit()

        assert promoted is not None
        assert promoted.is_default is True

        # First should no longer be default
        first_refreshed = await profile_service.get_profile(
            session, profile_id=first.id, user_id=user_id
        )
        assert first_refreshed.is_default is False


@pytest.mark.skipif(True, reason="PG required")
@pytest.mark.asyncio
async def test_cannot_delete_only_profile():
    from adelia.db import AsyncSessionLocal
    from adelia.enrichment import profile_service

    user_id = uuid4()
    async with AsyncSessionLocal() as session:
        only_one = await profile_service.ensure_default_profile(session, user_id=user_id)
        await session.commit()
        ok = await profile_service.soft_delete_profile(
            session, profile_id=only_one.id, user_id=user_id
        )
        assert ok is False  # protected


@pytest.mark.skipif(True, reason="PG required")
@pytest.mark.asyncio
async def test_cross_user_isolation():
    from adelia.db import AsyncSessionLocal
    from adelia.enrichment import profile_service

    user_a = uuid4()
    user_b = uuid4()
    async with AsyncSessionLocal() as session:
        a_profile = await profile_service.ensure_default_profile(session, user_id=user_a)
        await session.commit()
        # User B tries to access user A's profile
        result = await profile_service.get_profile(
            session, profile_id=a_profile.id, user_id=user_b
        )
        assert result is None  # opaque 404


@pytest.mark.skipif(True, reason="PG required")
@pytest.mark.asyncio
async def test_resolve_profile_id_falls_back_to_default():
    from adelia.db import AsyncSessionLocal
    from adelia.enrichment import profile_service

    user_id = uuid4()
    async with AsyncSessionLocal() as session:
        default = await profile_service.ensure_default_profile(session, user_id=user_id)
        await session.commit()
        resolved = await profile_service.resolve_profile_id(
            session, user_id=user_id, profile_id=None
        )
        assert resolved == default.id


def test_profile_create_dataclass():
    """ProfileCreate is the input shape — verify it accepts expected fields."""
    p = ProfileCreate(display_name="Test", relationship="child", sex="F")
    assert p.display_name == "Test"
    assert p.relationship == "child"
    assert p.is_default is False


def test_profile_create_default_flag():
    p = ProfileCreate(display_name="Me", relationship="self", is_default=True)
    assert p.is_default is True
