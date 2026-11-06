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


# ---------------------------------------------------------------------------
# Red flags come first, in code (audit 3.3)
#
# The dangerous question is not the one retrieval fails on. It is the one
# retrieval answers beautifully: there IS a paracetamol fragment, the model
# WILL dose it, and the answer will carry a citation. So the check runs before
# the embedding, and the mocks below are set to explode if it does not.
# ---------------------------------------------------------------------------


def _explode(*args, **kwargs):
    raise AssertionError("nothing downstream of the red-flag check may run")


@patch("adelia.services.chat_orchestrator._stream_llm_tokens", _explode)
@patch("adelia.services.chat_orchestrator.embed_texts", _explode)
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", _explode)
async def test_red_flag_returns_the_referral_without_retrieval_or_the_model():
    events = await _collect_events(
        answer_question_streaming(
            user_id=uuid4(),
            question="Mi bebé de 2 meses tiene 38,2, ¿le doy paracetamol?",
        )
    )
    text = "".join(e.content for e in events if e.type == "token")
    assert "112" in text
    assert "urgencias" in text.lower()
    assert "mg/kg" not in text
    assert "paracetamol" not in text.lower()
    assert [e.type for e in events] == ["token", "final"]


@patch("adelia.services.chat_orchestrator._stream_llm_tokens", _explode)
@patch("adelia.services.chat_orchestrator.embed_texts", _explode)
async def test_red_flag_cites_the_guideline_it_applied():
    events = await _collect_events(
        answer_question_streaming(user_id=uuid4(), question="le salieron manchas que no blanquean")
    )
    final = events[-1]
    assert final.type == "final"
    assert len(final.evidence_citations) == 1
    assert "NG240" in final.evidence_citations[0]["title"]
    assert final.evidence_citations[0]["url"].startswith("https://www.nice.org.uk/")


@patch("adelia.services.chat_orchestrator._stream_llm_tokens", _explode)
@patch("adelia.services.chat_orchestrator.embed_texts", _explode)
async def test_the_profile_age_is_what_makes_the_fever_rule_fire():
    """The parent wrote no age. Without the profile the rule cannot apply, and
    that is exactly the hole item 3.3 closes."""
    events = await _collect_events(
        answer_question_streaming(
            user_id=uuid4(), question="tiene fiebre desde anoche", age_months=2
        )
    )
    assert "112" in "".join(e.content for e in events if e.type == "token")


@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query")
@patch("adelia.services.chat_orchestrator._stream_llm_tokens")
async def test_an_ordinary_question_from_the_same_baby_still_goes_through_the_pipeline(
    mock_stream, mock_evidence, mock_embed, mock_retrieve, mock_temporal,
):
    mock_embed.return_value = [[0.1] * 1024]
    mock_evidence.return_value = [_evidence_match()]

    async def fake_stream(*args, **kwargs):
        yield "La leche materna sigue siendo el alimento principal [ev_1]."
    mock_stream.side_effect = fake_stream

    events = await _collect_events(
        answer_question_streaming(
            user_id=uuid4(),
            question="¿cuándo empiezo con la alimentación complementaria?",
            age_months=2,
        )
    )
    assert mock_stream.called
    assert events[-1].type == "final"


@pytest.mark.parametrize("locale,needle", [
    ("es", "urgencias pediátricas"),
    ("en", "paediatric emergency"),
    ("fr", "urgences pédiatriques"),
])
@patch("adelia.services.chat_orchestrator._stream_llm_tokens", _explode)
@patch("adelia.services.chat_orchestrator.embed_texts", _explode)
async def test_the_referral_speaks_the_parents_language(locale, needle):
    events = await _collect_events(
        answer_question_streaming(
            user_id=uuid4(), question="se atragantó con un trozo de manzana", locale=locale
        )
    )
    assert needle in "".join(e.content for e in events if e.type == "token")


@patch("adelia.services.chat_orchestrator.retrieve_evidence")
@patch("adelia.services.chat_orchestrator.AsyncSessionLocal")
async def test_the_chat_passes_the_relative_margin_from_the_setting(
    mock_session, mock_retrieve_evidence,
):
    """retrieve_evidence applies no relative criterion unless asked, so the
    chat has to ask: without this the margin exists and nothing uses it."""
    from adelia.config import settings
    from adelia.services.chat_orchestrator import _retrieve_evidence_for_query

    mock_retrieve_evidence.return_value = []
    await _retrieve_evidence_for_query([0.1] * 1024)

    assert (
        mock_retrieve_evidence.call_args.kwargs["relative_margin"]
        == settings.evidence_relative_margin
    )


# --- the corpus is searched in Spanish, her documents in her language ------
#
# agent/corpus_query.py: measured 2026-11-03, a French question sat 0.06 farther
# from the Spanish corpus than its Spanish twin and was refused. Her own
# documents are in her language, so only the evidence half changes.


@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query", return_value=[])
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator.corpus_query")
async def test_a_french_question_searches_her_documents_as_written_and_the_corpus_in_spanish(
    mock_corpus, mock_temporal, mock_embed, mock_chunks, mock_evidence,
):
    from adelia.services.chat_orchestrator import retrieve_for_account
    from adelia.services.scope import Scope

    question = "Mon bébé régurgite après chaque tétée"
    mock_corpus.return_value = "Mi bebé regurgita después de cada toma"
    mock_embed.return_value = [[0.1] * 1024, [0.2] * 1024]

    await retrieve_for_account(Scope(user_id=uuid4()), question=question, locale="fr")

    mock_corpus.assert_awaited_once_with(question, "fr")
    mock_embed.assert_awaited_once_with([question, "Mi bebé regurgita después de cada toma"])
    assert mock_chunks.call_args.kwargs["query_embedding"] == [0.1] * 1024
    assert mock_evidence.call_args.args[0] == [0.2] * 1024


@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query", return_value=[])
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
async def test_a_spanish_question_embeds_once_for_both_halves(
    mock_temporal, mock_embed, mock_chunks, mock_evidence,
):
    from adelia.services.chat_orchestrator import retrieve_for_account
    from adelia.services.scope import Scope

    mock_embed.return_value = [[0.1] * 1024]
    await retrieve_for_account(Scope(user_id=uuid4()), question="¿Regurgita?", locale="es")

    mock_embed.assert_awaited_once_with(["¿Regurgita?"])
    assert mock_evidence.call_args.args[0] == [0.1] * 1024


@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.query_observations_by_name_and_date_range",
       return_value=[])
@patch("adelia.services.chat_orchestrator.detect_temporal_intent")
@patch("adelia.services.chat_orchestrator.corpus_query")
async def test_the_temporal_path_embeds_only_the_corpus_text(
    mock_corpus, mock_temporal, mock_rows, mock_embed, mock_evidence,
):
    """Her values come from the structured query there; the embedding is for
    the guidelines alone."""
    from adelia.services.chat_orchestrator import retrieve_for_account
    from adelia.services.scope import Scope

    mock_temporal.return_value = MagicMock(entity_name="ferritine", from_date=None, to_date=None)
    mock_corpus.return_value = "curva de ferritina"
    mock_embed.return_value = [[0.3] * 1024]

    await retrieve_for_account(Scope(user_id=uuid4()), question="courbe de ferritine",
                               locale="fr")

    mock_embed.assert_awaited_once_with(["curva de ferritina"])
    assert mock_evidence.call_args.args[0] == [0.3] * 1024


# --- her words, rendered for the corpus (agent/lay_terms.py) ----------------------
#
# The chat and the /dashboard agent search the corpus through this function, so
# settings.lay_query_expansion reaches them here: off, the calls of before; on,
# a third text in the same embedding call and a second evidence search, merged
# by best distance. Her own documents are searched with what she wrote.

_LAY = "Tiene el culito muy rojo del pañal"


@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query", return_value=[])
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
async def test_with_the_expansion_off_the_chat_searches_exactly_as_before(
    mock_temporal, mock_embed, mock_chunks, mock_evidence, monkeypatch,
):
    from adelia.agent import lay_terms
    from adelia.config import settings
    from adelia.services.chat_orchestrator import retrieve_for_account
    from adelia.services.scope import Scope

    monkeypatch.setattr(settings, "lay_query_expansion", False)

    def _never(*args, **kwargs):
        raise AssertionError("the lexicon is read with the expansion off")

    monkeypatch.setattr(lay_terms, "expanded_query", _never)
    mock_embed.return_value = [[0.1] * 1024]
    await retrieve_for_account(Scope(user_id=uuid4()), question=_LAY, locale="es")

    mock_embed.assert_awaited_once_with([_LAY])
    mock_evidence.assert_awaited_once_with([0.1] * 1024, query_text=_LAY, locale="es")


@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query")
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
async def test_with_the_expansion_on_the_chat_also_searches_the_clinical_terms(
    mock_temporal, mock_embed, mock_chunks, mock_evidence, monkeypatch,
):
    from adelia.agent.lay_terms import expanded_query
    from adelia.config import settings
    from adelia.enrichment.evidence_retrieval import EvidenceMatch
    from adelia.services.chat_orchestrator import retrieve_for_account
    from adelia.services.scope import Scope

    monkeypatch.setattr(settings, "lay_query_expansion", True)
    found = EvidenceMatch(
        chunk_id=uuid4(), source_id=uuid4(), source_title="Nappy rash (NHS)",
        organization="NHS", publication_year=2026, url=None, content="dermatitis del pañal",
        chunk_index=0, distance=0.12,
    )
    mock_evidence.side_effect = [[], [found]]
    mock_embed.return_value = [[0.1] * 1024, [0.2] * 1024]

    out = await retrieve_for_account(Scope(user_id=uuid4()), question=_LAY, locale="es")

    mock_embed.assert_awaited_once_with([_LAY, expanded_query(_LAY)])
    assert mock_chunks.call_args.kwargs["query_embedding"] == [0.1] * 1024
    assert [c.args[0] for c in mock_evidence.await_args_list] == [[0.1] * 1024, [0.2] * 1024]
    assert out.evidence == [found]


@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query", return_value=[])
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator.corpus_query")
async def test_with_the_expansion_on_a_french_question_expands_its_spanish_rendering(
    mock_corpus, mock_temporal, mock_embed, mock_chunks, mock_evidence, monkeypatch,
):
    from adelia.agent.lay_terms import expanded_query
    from adelia.config import settings
    from adelia.services.chat_orchestrator import retrieve_for_account
    from adelia.services.scope import Scope

    monkeypatch.setattr(settings, "lay_query_expansion", True)
    question = "Elle a les fesses toutes rouges"
    mock_corpus.return_value = _LAY
    mock_embed.return_value = [[0.1] * 1024, [0.2] * 1024, [0.3] * 1024]

    await retrieve_for_account(Scope(user_id=uuid4()), question=question, locale="fr")

    mock_embed.assert_awaited_once_with([question, _LAY, expanded_query(_LAY)])
    assert mock_chunks.call_args.kwargs["query_embedding"] == [0.1] * 1024
    assert [c.args[0] for c in mock_evidence.await_args_list] == [[0.2] * 1024, [0.3] * 1024]


# --- the baby she does not name (agent/implicit_subject.py) ----------------------
#
# The chat and the /dashboard agent search the corpus here, so
# settings.implicit_subject_expansion reaches them here too: off, the calls of
# before; on, her sentence with the baby put back as one more text in the same
# embedding call and one more evidence search, merged by best distance. Her
# own documents are searched with what she wrote.

_NO_SUBJECT = "Tiene diarrea desde ayer, ¿qué hago?"


@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query", return_value=[])
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
async def test_with_the_subject_off_the_chat_searches_exactly_as_before(
    mock_temporal, mock_embed, mock_chunks, mock_evidence, monkeypatch,
):
    from adelia.agent import implicit_subject
    from adelia.config import settings
    from adelia.services.chat_orchestrator import retrieve_for_account
    from adelia.services.scope import Scope

    monkeypatch.setattr(settings, "implicit_subject_expansion", False)
    monkeypatch.setattr(settings, "lay_query_expansion", False)

    def _never(*args, **kwargs):
        raise AssertionError("the subject rules are read with the setting off")

    monkeypatch.setattr(implicit_subject, "subject_query", _never)
    mock_embed.return_value = [[0.1] * 1024]
    await retrieve_for_account(Scope(user_id=uuid4()), question=_NO_SUBJECT, locale="es",
                               age_months=7, baby_name="Nora")

    mock_embed.assert_awaited_once_with([_NO_SUBJECT])
    mock_evidence.assert_awaited_once_with([0.1] * 1024, query_text=_NO_SUBJECT, locale="es")


@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query")
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
async def test_with_the_subject_on_the_chat_also_searches_with_the_baby(
    mock_temporal, mock_embed, mock_chunks, mock_evidence, monkeypatch,
):
    from adelia.config import settings
    from adelia.services.chat_orchestrator import retrieve_for_account
    from adelia.services.scope import Scope

    monkeypatch.setattr(settings, "implicit_subject_expansion", True)
    monkeypatch.setattr(settings, "lay_query_expansion", False)
    found = _evidence_match()
    mock_evidence.side_effect = [[], [found]]
    mock_embed.return_value = [[0.1] * 1024, [0.2] * 1024]

    out = await retrieve_for_account(Scope(user_id=uuid4()), question=_NO_SUBJECT,
                                     locale="es", age_months=7)

    mock_embed.assert_awaited_once_with([_NO_SUBJECT, f"Mi bebé de 7 meses: {_NO_SUBJECT}"])
    assert mock_chunks.call_args.kwargs["query_embedding"] == [0.1] * 1024
    assert [c.args[0] for c in mock_evidence.await_args_list] == [[0.1] * 1024, [0.2] * 1024]
    assert out.evidence == [found]


@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query", return_value=[])
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
async def test_the_child_s_name_counts_as_the_subject_in_the_chat(
    mock_temporal, mock_embed, mock_chunks, mock_evidence, monkeypatch,
):
    from adelia.config import settings
    from adelia.services.chat_orchestrator import retrieve_for_account
    from adelia.services.scope import Scope

    monkeypatch.setattr(settings, "implicit_subject_expansion", True)
    monkeypatch.setattr(settings, "lay_query_expansion", False)
    mock_embed.return_value = [[0.1] * 1024]
    question = "Nora tiene diarrea desde ayer"
    await retrieve_for_account(Scope(user_id=uuid4()), question=question, locale="es",
                               age_months=7, baby_name="Nora")
    mock_embed.assert_awaited_once_with([question])


@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query", return_value=[])
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator.corpus_query")
async def test_with_the_subject_on_a_french_question_gets_the_baby_in_spanish(
    mock_corpus, mock_temporal, mock_embed, mock_chunks, mock_evidence, monkeypatch,
):
    from adelia.config import settings
    from adelia.services.chat_orchestrator import retrieve_for_account
    from adelia.services.scope import Scope

    monkeypatch.setattr(settings, "implicit_subject_expansion", True)
    monkeypatch.setattr(settings, "lay_query_expansion", False)
    question = "Elle a la diarrhée depuis hier"
    mock_corpus.return_value = "Tiene diarrea desde ayer"
    mock_embed.return_value = [[0.1] * 1024, [0.2] * 1024, [0.3] * 1024]

    await retrieve_for_account(Scope(user_id=uuid4()), question=question, locale="fr",
                               age_months=9)

    mock_embed.assert_awaited_once_with(
        [question, "Tiene diarrea desde ayer", "Mi bebé de 9 meses: Tiene diarrea desde ayer"]
    )
    assert mock_chunks.call_args.kwargs["query_embedding"] == [0.1] * 1024
    assert [c.args[0] for c in mock_evidence.await_args_list] == [[0.2] * 1024, [0.3] * 1024]


@patch("adelia.services.chat_orchestrator.detect_temporal_intent", return_value=None)
@patch("adelia.services.chat_orchestrator.retrieve_relevant_chunks", return_value=[])
@patch("adelia.services.chat_orchestrator.embed_texts")
@patch("adelia.services.chat_orchestrator._retrieve_evidence_for_query", return_value=[])
@patch("adelia.services.chat_orchestrator._stream_llm_tokens", _explode)
async def test_the_chat_hands_the_profile_age_to_the_subject(
    mock_evidence, mock_embed, mock_chunks, mock_temporal, monkeypatch,
):
    from adelia.config import settings

    monkeypatch.setattr(settings, "implicit_subject_expansion", True)
    monkeypatch.setattr(settings, "lay_query_expansion", False)
    mock_embed.return_value = [[0.1] * 1024, [0.2] * 1024]
    await _collect_events(
        answer_question_streaming(user_id=uuid4(), question=_NO_SUBJECT, age_months=7)
    )
    mock_embed.assert_awaited_once_with([_NO_SUBJECT, f"Mi bebé de 7 meses: {_NO_SUBJECT}"])
