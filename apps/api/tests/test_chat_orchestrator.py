from datetime import date
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from adelia.enrichment.evidence_retrieval import EvidenceMatch
from adelia.services.answer_contract import no_evidence_reply
from adelia.services.chat_orchestrator import (
    ChatEvent,
    answer_question_streaming,
)


def _evidence_match(distance: float = 0.11) -> EvidenceMatch:
    """One surviving evidence fragment, well inside the calibrated cut-off."""
    return EvidenceMatch(
        chunk_id=uuid4(), source_id=uuid4(),
        source_title="Reflujo (GER) vs enfermedad por reflujo (GERD)",
        organization="NASPGHAN-ESPGHAN", publication_year=2018,
        url="https://example.org/naspghan",
        content="La regurgitación del lactante es fisiológica y mejora hacia los 12 meses.",
        chunk_index=0, distance=distance,
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


@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query", return_value=[])
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator._stream_llm_tokens")
async def test_out_of_corpus_question_refuses_without_calling_the_model(
    mock_stream, mock_temporal, mock_embed, mock_retrieve, mock_evidence,
):
    """The control question of audit finding 4.1.

    Nothing survives either cut-off, so the generative model must never be
    reached: the refusal comes from the code. Asserting on the mock is the
    whole point, a prompt clause would not be a guarantee.
    """
    user_id = uuid4()
    mock_embed.return_value = [[0.1] * 1024]

    events = await _collect_events(
        answer_question_streaming(
            user_id=user_id,
            question="¿es normal que no gatee a los 9 meses?",
        )
    )

    mock_stream.assert_not_called()
    tokens = "".join(e.content for e in events if e.type == "token")
    assert tokens == no_evidence_reply("es")
    assert "pediatra" in tokens
    final = [e for e in events if e.type == "final"][0]
    assert final.citations == []
    assert final.evidence_citations == []


@pytest.mark.parametrize("locale", ["es", "en", "fr"])
@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query", return_value=[])
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator._stream_llm_tokens")
async def test_refusal_is_returned_in_the_requested_locale(
    mock_stream, mock_temporal, mock_embed, mock_retrieve, mock_evidence, locale,
):
    mock_embed.return_value = [[0.1] * 1024]
    events = await _collect_events(
        answer_question_streaming(
            user_id=uuid4(), question="mortgage rates", locale=locale
        )
    )
    mock_stream.assert_not_called()
    tokens = "".join(e.content for e in events if e.type == "token")
    assert tokens == no_evidence_reply(locale)


@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query")
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator._stream_llm_tokens")
async def test_in_corpus_question_still_answers_with_evidence_citations(
    mock_stream, mock_temporal, mock_embed, mock_retrieve, mock_evidence,
):
    """The other half of the contract: evidence survives, so the model runs
    and the answer carries its [ev_N] citations."""
    mock_embed.return_value = [[0.1] * 1024]
    mock_evidence.return_value = [_evidence_match()]

    async def fake_stream(*args, **kwargs):
        yield "Regurgitar tras las tomas es habitual [ev_1]."
    mock_stream.side_effect = fake_stream

    events = await _collect_events(
        answer_question_streaming(
            user_id=uuid4(),
            question="¿es normal que regurgite después de cada toma?",
        )
    )

    mock_stream.assert_called_once()
    final = [e for e in events if e.type == "final"][0]
    assert [c["tag"] for c in final.evidence_citations] == ["ev_1"]
    assert final.evidence_citations[0]["organization"] == "NASPGHAN-ESPGHAN"


@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query", return_value=[])
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks")
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator._stream_llm_tokens")
async def test_patient_history_alone_is_enough_to_answer(
    mock_stream, mock_temporal, mock_embed, mock_retrieve, mock_evidence,
):
    """Zero evidence but the user's own record has something: the model is
    still called (it may report the datum as a fact), only clinical
    interpretation is what the contract forbids without an [ev_N]."""
    mock_embed.return_value = [[0.1] * 1024]
    mock_retrieve.return_value = [
        MagicMock(
            chunk_id=uuid4(), document_id=uuid4(),
            content="Peso 7,2 kg el 12 de agosto.",
            raw_quote_hint="Peso 7,2 kg", page=1, entity_ids=[],
        )
    ]

    async def fake_stream(*args, **kwargs):
        yield "Tu bebe pesaba 7,2 kg [1]."
    mock_stream.side_effect = fake_stream

    events = await _collect_events(
        answer_question_streaming(user_id=uuid4(), question="¿cuanto pesa?")
    )

    mock_stream.assert_called_once()
    assert [e for e in events if e.type == "final"][0].citations


def test_patient_retrieval_now_passes_a_distance_cut_off():
    """Audit 4.1: retrieve_relevant_chunks accepted no max_distance at all,
    so the closest top_k came back however far they were."""
    import inspect

    from adelia.services.retrieval import retrieve_relevant_chunks

    assert "max_distance" in inspect.signature(retrieve_relevant_chunks).parameters


@patch("adelia.services.chat_orchestrator.retrieve_evidence")
@patch("adelia.services.chat_orchestrator.AsyncSessionLocal")
async def test_evidence_cut_off_comes_from_the_calibrated_setting(
    mock_session, mock_retrieve_evidence,
):
    """The 0.45 literal sat above the corpus diameter (0.3386) and filtered
    nothing. The value now comes from the calibrated setting."""
    from adelia.config import settings
    from adelia.services.chat_orchestrator import _retrieve_evidence_for_query

    mock_retrieve_evidence.return_value = []
    await _retrieve_evidence_for_query([0.1] * 1024)

    assert (
        mock_retrieve_evidence.call_args.kwargs["max_distance"]
        == settings.evidence_max_distance
    )
    # This runs in CI, where there is no corpus, so it is the ONLY threshold
    # guard on the deployment gate: the three integration tests next door skip
    # on an empty database. Both bounds come from the measured valley in
    # docs/CALIBRACION_UMBRAL_EVIDENCIA.md, taken against the index the code
    # actually searches (the pediatric subset).
    assert settings.evidence_max_distance < 0.3386, (
        "a cut-off above the corpus diameter cannot reject anything"
    )
    assert 0.1821 <= settings.evidence_max_distance <= 0.1989, (
        "the cut-off must sit in the measured valley: below 0.1821, the worst "
        "cross-topic in-corpus probe, it starts refusing questions the corpus "
        "does answer; above 0.1989, the nearest off-corpus probe, adult "
        "content starts coming back as clinical evidence for a baby"
    )


@patch("adelia.services.chat_orchestrator.retrieve_evidence")
@patch("adelia.services.chat_orchestrator.AsyncSessionLocal")
async def test_the_answering_path_searches_only_the_pediatric_corpus(
    mock_session, mock_retrieve_evidence,
):
    """evidence_chunks also holds 8 ADULT sources (atrial fibrillation,
    hypertension, cholesterol, breast and colorectal screening, endometriosis,
    adult diabetes, SBAR). Without this filter the calibration table described
    a population the code never searched, and an app about a baby could answer
    with anticoagulation or cancer-screening text labelled "Clinical evidence"
    (measured on dev: 12 of 14 adult probes leaked at the cut-off)."""
    from adelia.services.chat_orchestrator import _retrieve_evidence_for_query

    mock_retrieve_evidence.return_value = []
    await _retrieve_evidence_for_query([0.1] * 1024)

    assert mock_retrieve_evidence.call_args.kwargs["specialties"] == ["pediatrics"]


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
    # Evidence present: without it the orchestrator refuses in code and never
    # reaches the LLM, which is a different test (the refusal one below).
    mock_evidence.return_value = [_evidence_match()]

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
    mock_evidence.return_value = [_evidence_match()]

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
