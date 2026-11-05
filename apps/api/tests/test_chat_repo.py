
import pytest

from adelia.services.chat_repo import (
    create_session,
    delete_session,
    get_session_with_messages,
    list_sessions,
    persist_message,
)

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_create_session_returns_session_with_default_title():
    user_id = await make_user()
    session = await create_session(user_id=user_id)
    assert session.title == "Nueva conversación"


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_persist_message_appends_to_session():
    user_id = await make_user()
    session = await create_session(user_id=user_id)
    message = await persist_message(
        session_id=session.id,
        user_id=user_id,
        role="user",
        content="¿Qué medicamentos tomo?",
        citations=None,
    )
    assert message.role == "user"
    assert message.content == "¿Qué medicamentos tomo?"
    assert message.session_id == session.id


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_get_session_with_messages_returns_ordered_messages():
    user_id = await make_user()
    session = await create_session(user_id=user_id)
    await persist_message(session_id=session.id, user_id=user_id, role="user", content="primero", citations=None)
    await persist_message(session_id=session.id, user_id=user_id, role="assistant", content="respuesta1", citations=[])
    await persist_message(session_id=session.id, user_id=user_id, role="user", content="segundo", citations=None)
    detail = await get_session_with_messages(session_id=session.id, user_id=user_id)
    assert detail is not None
    assert len(detail.messages) == 3
    assert [m.content for m in detail.messages] == ["primero", "respuesta1", "segundo"]


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_list_sessions_filters_by_user_and_excludes_deleted():
    user_a = await make_user()
    user_b = await make_user()
    s1 = await create_session(user_id=user_a)
    s2 = await create_session(user_id=user_a)
    s3 = await create_session(user_id=user_b)
    sessions = await list_sessions(user_id=user_a)
    ids = {s.id for s in sessions}
    assert s1.id in ids and s2.id in ids
    assert s3.id not in ids
    await delete_session(session_id=s1.id, user_id=user_a)
    sessions_after = await list_sessions(user_id=user_a)
    ids_after = {s.id for s in sessions_after}
    assert s1.id not in ids_after


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_delete_session_404_for_other_users():
    user_a = await make_user()
    user_b = await make_user()
    s = await create_session(user_id=user_a)
    result = await delete_session(session_id=s.id, user_id=user_b)
    assert result is False  # not found / not owned


async def _child(user_id, name: str, *, default: bool):
    from adelia.db import AsyncSessionLocal
    from adelia.models import Profile

    async with AsyncSessionLocal() as session:
        profile = Profile(user_id=user_id, display_name=name, relationship="child",
                          is_default=default)
        session.add(profile)
        await session.commit()
        return profile.id


async def _session_profile(session_id):
    from adelia.db import AsyncSessionLocal
    from adelia.models import ChatSession

    async with AsyncSessionLocal() as session:
        return (await session.get(ChatSession, session_id)).profile_id


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_a_session_carries_the_child_it_is_about():
    """GET /today reads the "No olvides" line per child, so the session says which one."""
    user_id = await make_user()
    nora = await _child(user_id, "Nora", default=True)
    adel = await _child(user_id, "Adel", default=False)
    session = await create_session(user_id=user_id, profile_id=nora)
    assert await _session_profile(session.id) == nora
    # A turn about another child moves the conversation to that child: the
    # newest plan in it is the one the home card shows, and it is about Adel.
    await persist_message(session_id=session.id, user_id=user_id, role="user",
                          content="¿Y Adel?", citations=None, profile_id=adel)
    assert await _session_profile(session.id) == adel
    # The assistant half of the turn does not pass a profile and leaves it be.
    await persist_message(session_id=session.id, user_id=user_id, role="assistant",
                          content="respuesta", citations=[])
    assert await _session_profile(session.id) == adel
