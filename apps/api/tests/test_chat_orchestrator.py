from datetime import date
from unittest.mock import MagicMock, patch
from uuid import uuid4


from adelia.services.chat_orchestrator import (
    ChatEvent,
    answer_question_streaming,
)


async def _collect_events(gen) -> list[ChatEvent]:
    events: list[ChatEvent] = []
    async for ev in gen:
        events.append(ev)
    return events


@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks")
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator._stream_llm_tokens")
async def test_rag_path_emits_tokens_and_final_citations(
    mock_stream, mock_embed, mock_retrieve, mock_temporal,
):
    user_id = uuid4()
    mock_embed.return_value = [[0.1] * 1024]
    mock_retrieve.return_value = [
        MagicMock(
            chunk_id=uuid4(), document_id=uuid4(),
            content="The patient takes Metformin 500mg.",
            raw_quote_hint="The patient takes Metformin 500mg.",
            page=1, entity_ids=[],
        )
    ]
    async def fake_stream(*args, **kwargs):
        for tok in ["You ", "take ", "Metformin."]:
            yield tok
    mock_stream.side_effect = fake_stream

    events = await _collect_events(
        answer_question_streaming(user_id=user_id, question="¿Qué tomo?")
    )

    token_events = [e for e in events if e.type == "token"]
    final_events = [e for e in events if e.type == "final"]
    assert len(token_events) == 3
    assert "".join(e.content for e in token_events) == "You take Metformin."
    assert len(final_events) == 1
    assert isinstance(final_events[0].citations, list)


@patch("adelia.services.chat_orchestrator.detect_temporal_intent")
@patch("adelia.services.chat_orchestrator.query_observations_by_name_and_date_range")
@patch("adelia.services.chat_orchestrator._stream_llm_tokens")
async def test_temporal_path_uses_structured_query_not_rag(
    mock_stream, mock_query, mock_temporal,
):
    user_id = uuid4()
    mock_temporal.return_value = MagicMock(
        entity_name="glucosa", from_date=date(2020, 1, 1), to_date=date(2024, 12, 31)
    )
    doc_id = uuid4()
    ent_id = uuid4()
    mock_query.return_value = [
        {"id": ent_id, "name": "Glucose", "value": {"value": 98, "unit": "mg/dL"},
         "event_date": date(2023, 5, 1), "raw_quote": "Glucose 98 mg/dL", "document_id": doc_id},
    ]
    async def fake_stream(*args, **kwargs):
        for tok in ["Your ", "glucose ", "is stable."]:
            yield tok
    mock_stream.side_effect = fake_stream

    events = await _collect_events(
        answer_question_streaming(user_id=user_id, question="curva de glucosa últimos 5 años")
    )

    mock_query.assert_called_once()
    final = [e for e in events if e.type == "final"][0]
    # Temporal path uses the entity_id from the observation row as a "citation"
    # surrogate, since chunks aren't searched in this path
    assert any(c.chunk_id == ent_id or str(c.chunk_id) == str(ent_id) for c in final.citations)


@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator._stream_llm_tokens")
async def test_empty_retrieval_still_yields_an_answer(
    mock_stream, mock_temporal, mock_embed, mock_retrieve,
):
    user_id = uuid4()
    mock_embed.return_value = [[0.1] * 1024]
    async def fake_stream(*args, **kwargs):
        yield "No tengo información suficiente."
    mock_stream.side_effect = fake_stream

    events = await _collect_events(
        answer_question_streaming(user_id=user_id, question="¿Tengo cáncer?")
    )

    assert any(e.type == "token" for e in events)
    final = [e for e in events if e.type == "final"][0]
    assert final.citations == []


@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query")
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks")
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator._stream_llm_tokens")
async def test_history_is_forwarded_to_llm(
    mock_stream, mock_embed, mock_retrieve, mock_evidence, mock_temporal,
):
    """Multi-turn: prior session messages must reach the LLM so follow-up
    questions resolve against the conversation, not just the fresh RAG context."""
    user_id = uuid4()
    mock_embed.return_value = [[0.1] * 1024]
    mock_retrieve.return_value = []
    mock_evidence.return_value = []

    async def fake_stream(*args, **kwargs):
        yield "ok"
    mock_stream.side_effect = fake_stream

    history = [
        {"role": "user", "content": "¿Cuál es mi glucosa?"},
        {"role": "assistant", "content": "Tu glucosa es 95 mg/dL [1]."},
    ]
    await _collect_events(
        answer_question_streaming(
            user_id=user_id, question="¿Y está en rango normal?", history=history
        )
    )

    assert mock_stream.call_args.kwargs.get("history") == history


@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query")
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks")
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator._stream_llm_tokens")
async def test_stalled_stream_yields_error_event(
    mock_stream, mock_embed, mock_retrieve, mock_evidence, mock_temporal, monkeypatch,
):
    """A hung LLM stream must surface an error event, not hold the SSE open."""
    import asyncio as aio

    from adelia.services import chat_orchestrator as orch

    monkeypatch.setattr(orch, "TOKEN_GAP_TIMEOUT_S", 0.05)
    monkeypatch.setattr(orch, "STREAM_TOTAL_TIMEOUT_S", 0.2)
    mock_embed.return_value = [[0.1] * 1024]
    mock_retrieve.return_value = []
    mock_evidence.return_value = []

    async def hung_stream(*args, **kwargs):
        yield "primer token"
        await aio.sleep(10)  # never sends another token
        yield "nunca llega"
    mock_stream.side_effect = hung_stream

    events = await _collect_events(
        answer_question_streaming(user_id=uuid4(), question="¿glucosa?")
    )

    types = [e.type for e in events]
    assert types[0] == "token"
    assert types[-1] == "error"
    assert "stalled" in events[-1].content or "budget" in events[-1].content
