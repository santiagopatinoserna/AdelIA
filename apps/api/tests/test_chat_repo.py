from uuid import uuid4

import pytest

from adelia.services.chat_repo import (
    create_session,
    delete_session,
    get_session_with_messages,
    list_sessions,
    persist_message,
)


@pytest.mark.skipif(True, reason="needs Postgres running")
async def test_create_session_returns_session_with_default_title():
    user_id = uuid4()
    session = await create_session(user_id=user_id)
    assert session.title == "Nueva conversación"


@pytest.mark.skipif(True, reason="needs Postgres running")
async def test_persist_message_appends_to_session():
    user_id = uuid4()
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


@pytest.mark.skipif(True, reason="needs Postgres running")
async def test_get_session_with_messages_returns_ordered_messages():
    user_id = uuid4()
    session = await create_session(user_id=user_id)
    await persist_message(session_id=session.id, user_id=user_id, role="user", content="primero", citations=None)
    await persist_message(session_id=session.id, user_id=user_id, role="assistant", content="respuesta1", citations=[])
    await persist_message(session_id=session.id, user_id=user_id, role="user", content="segundo", citations=None)
    detail = await get_session_with_messages(session_id=session.id, user_id=user_id)
    assert detail is not None
    assert len(detail.messages) == 3
    assert [m.content for m in detail.messages] == ["primero", "respuesta1", "segundo"]


@pytest.mark.skipif(True, reason="needs Postgres running")
async def test_list_sessions_filters_by_user_and_excludes_deleted():
    user_a = uuid4()
    user_b = uuid4()
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


@pytest.mark.skipif(True, reason="needs Postgres running")
async def test_delete_session_404_for_other_users():
    user_a = uuid4()
    user_b = uuid4()
    s = await create_session(user_id=user_a)
    result = await delete_session(session_id=s.id, user_id=user_b)
    assert result is False  # not found / not owned
