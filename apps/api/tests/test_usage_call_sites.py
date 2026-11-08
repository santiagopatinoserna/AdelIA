"""Every path that calls a model counts the call, and only the call (2026-11-08).

One case per provider call in the code: the agent's steps, the route
classifier and the two other JSON jobs that borrow its plumbing (the record
extraction and the corpus translation), the RAG chat on three providers, OCR,
extraction, the consultation summary, transcription, embeddings and the
briefing questions. Each runs on a fake client that answers with a known
usage, and `usage.count` is replaced by a recorder, so none needs a key.

Then the surfaces: each entry point labels what it calls (demo, chat, agent,
guest, ingestion, briefing, corpus), and a counter that fails or hangs never
changes the answer. Last, a real write through a real path, to show that what
lands in usage_counters is labels and integers and never the text.
"""
from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa

from adelia.agent import route as route_mod
from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import UsageCounter
from adelia.services import usage
from tests.pg_gate import PG_AVAILABLE

# conftest replaces route._complete_json for every test; the purpose cases need
# the real one, captured here at import, before any fixture runs.
REAL_COMPLETE_JSON = route_mod._complete_json

needs_pg = pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres")

QUESTION = "¿Es normal que Lucía regurgite después de cada toma?"
ANSWER = "La regurgitación es habitual a esta edad."


@pytest.fixture(autouse=True)
def _no_pinned_surface(monkeypatch):
    monkeypatch.delenv(usage.SURFACE_ENV, raising=False)


@pytest.fixture
def counted(monkeypatch) -> list[tuple]:
    """(surface, operation, provider, model, counts) of every count() call."""
    calls: list[tuple] = []

    def _count(operation, provider, model, **counts):
        calls.append((usage.current_surface(), operation, provider, model, counts))

    monkeypatch.setattr(usage, "count", _count)
    return calls


def _anthropic_message(text: str = ANSWER, **extra) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1000, output_tokens=50,
                              cache_read_input_tokens=200, cache_creation_input_tokens=30),
        **extra,
    )


ANTHROPIC_COUNTS = {"input_tokens": 1000, "output_tokens": 50,
                    "cache_read_tokens": 200, "cache_write_tokens": 30}


class _FakeAnthropicStream:
    def __init__(self, final, pieces=(ANSWER,)):
        self._final = final
        self._pieces = pieces

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for piece in self._pieces:
                yield SimpleNamespace(type="text", text=piece)
        return gen()

    @property
    def text_stream(self):
        async def gen():
            for piece in self._pieces:
                yield piece
        return gen()

    async def get_final_message(self):
        return self._final


def _fake_anthropic_client(final=None):
    final = final or _anthropic_message()
    client = MagicMock()
    client.messages.stream = MagicMock(return_value=_FakeAnthropicStream(final))
    client.messages.create = AsyncMock(return_value=final)
    return client


def _mistral_reply(content: str = ANSWER):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content, tool_calls=None), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=700, completion_tokens=12),
    )


MISTRAL_COUNTS = {"input_tokens": 700, "output_tokens": 12, "cache_read_tokens": 0}


def _fake_mistral_client(content: str = ANSWER):
    client = MagicMock()
    client.chat.complete_async = AsyncMock(return_value=_mistral_reply(content))
    return client


class _FakeHttpx:
    """httpx.AsyncClient answering one JSON payload to any POST."""

    def __init__(self, payload: dict):
        self._payload = payload

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        payload = self._payload
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)


# --- the agent ------------------------------------------------------------------------


async def test_an_agent_step_on_anthropic_is_counted(counted, monkeypatch):
    from adelia.agent.provider import AnthropicProvider

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    provider = AnthropicProvider()
    provider._client = _fake_anthropic_client()

    events = [e async for e in provider.stream_step(system="s", messages=[], tools=[])]

    assert events[-1]["type"] == "stop"
    assert counted == [("other", "agent_step", "anthropic", settings.agent_model,
                        ANTHROPIC_COUNTS)]


async def test_an_agent_step_on_mistral_is_counted(counted, monkeypatch):
    from adelia import llm
    from adelia.agent.provider import MistralProvider

    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    monkeypatch.setattr(llm, "get_mistral_client", lambda: _fake_mistral_client())

    events = [e async for e in MistralProvider().stream_step(system="s", messages=[], tools=[])]

    assert events[0] == {"type": "token", "text": ANSWER}
    assert counted == [("other", "agent_step", "mistral", settings.mistral_chat_model,
                        MISTRAL_COUNTS)]


# --- route, and the JSON jobs that borrow its plumbing ----------------------------------


async def test_the_route_classifier_is_counted_on_each_provider(counted, monkeypatch):
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(route_mod, "get_mistral_client", lambda: _fake_mistral_client("{}"))
    monkeypatch.setattr(route_mod, "get_anthropic_client",
                        lambda: _fake_anthropic_client(_anthropic_message("{}")))

    class _OpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(
                create=AsyncMock(return_value=_mistral_reply("{}"))))

    monkeypatch.setattr("openai.AsyncOpenAI", _OpenAI)

    assert await route_mod._mistral_json("s", "u") == "{}"
    assert await route_mod._anthropic_json("s", "u") == "{}"
    assert await route_mod._openai_json("s", "u") == "{}"

    assert counted == [
        ("other", "route", "mistral", settings.mistral_routing_model, MISTRAL_COUNTS),
        ("other", "route", "anthropic", settings.anthropic_routing_model, ANTHROPIC_COUNTS),
        ("other", "route", "openai", settings.openai_chat_model, MISTRAL_COUNTS),
    ]


async def test_the_record_extraction_is_counted_as_record(counted, monkeypatch):
    from adelia.agent import record

    monkeypatch.setattr(route_mod, "_complete_json", REAL_COMPLETE_JSON)
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    monkeypatch.setattr(route_mod, "get_mistral_client",
                        lambda: _fake_mistral_client('{"tipo": "nota"}'))

    await record.extract_record("Hoy la vi un poco rara al despertar", locale="es",
                                now=datetime.now(timezone.utc))

    assert [c[1:3] for c in counted] == [("record", "mistral")]


async def test_the_corpus_translation_is_counted_as_translate(counted, monkeypatch):
    from adelia.agent import corpus_query

    monkeypatch.setattr(route_mod, "_complete_json", REAL_COMPLETE_JSON)
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    monkeypatch.setattr(route_mod, "get_mistral_client",
                        lambda: _fake_mistral_client('{"es": "¿Es normal?"}'))

    out = await corpus_query.corpus_query("Is it normal?", "en")

    assert out == "¿Es normal?"
    assert [c[1:3] for c in counted] == [("translate", "mistral")]


# --- the RAG chat (and the demo's generate_answer, which streams the same way) --------


async def test_a_streamed_mistral_answer_is_counted_from_its_last_chunk(counted, monkeypatch):
    from adelia.services import chat_orchestrator

    def chunk(text, chunk_usage=None):
        delta = SimpleNamespace(content=text)
        return SimpleNamespace(
            data=SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=chunk_usage)
        )

    async def fake_stream():
        yield chunk("La regurgitación ")
        yield chunk("es habitual.", SimpleNamespace(prompt_tokens=700, completion_tokens=12))

    fake_client = MagicMock()
    fake_client.chat.stream_async = AsyncMock(return_value=fake_stream())
    monkeypatch.setattr(chat_orchestrator, "get_mistral_client", lambda: fake_client)

    pieces = [p async for p in chat_orchestrator._stream_mistral_tokens([])]

    assert "".join(pieces) == "La regurgitación es habitual."
    assert counted == [("other", "chat", "mistral", settings.mistral_chat_model,
                        MISTRAL_COUNTS)]


async def test_a_streamed_anthropic_answer_is_counted_from_its_final_message(
    counted, monkeypatch
):
    from adelia.services import chat_orchestrator

    monkeypatch.setattr(chat_orchestrator, "get_anthropic_client",
                        lambda: _fake_anthropic_client())

    pieces = [p async for p in chat_orchestrator._stream_anthropic_tokens("s", QUESTION, None)]

    assert "".join(pieces) == ANSWER
    assert counted == [("other", "chat", "anthropic", settings.anthropic_chat_model,
                        ANTHROPIC_COUNTS)]


async def test_a_streamed_openai_answer_counts_the_call(counted, monkeypatch):
    """OpenAI streams no usage unless the request asks for it, and asking
    would change the call the demo makes: the call is counted, tokens are 0."""
    from adelia.services import chat_orchestrator

    async def stream():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=ANSWER))])

    class _OpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(
                create=AsyncMock(return_value=stream())))

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr("openai.AsyncOpenAI", _OpenAI)

    pieces = [p async for p in chat_orchestrator._stream_openai_tokens([])]

    assert "".join(pieces) == ANSWER
    assert counted == [("other", "chat", "openai", settings.openai_chat_model, {})]


# --- documents --------------------------------------------------------------------------


async def test_mistral_ocr_counts_the_pages_it_was_billed(counted, monkeypatch):
    from adelia.workers import ocr

    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    payload = {"pages": [{"markdown": "a"}, {"markdown": "b"}],
               "usage_info": {"pages_processed": 2}}
    monkeypatch.setattr(ocr.httpx, "AsyncClient", _FakeHttpx(payload))

    text = await ocr.extract_text_from_pdf(b"%PDF", "application/pdf")

    assert text == "a\n\nb"
    assert counted == [("other", "ocr", "mistral", settings.mistral_ocr_model, {"pages": 2})]


async def test_anthropic_ocr_is_counted(counted, monkeypatch):
    from adelia.workers import ocr

    monkeypatch.setattr(ocr, "get_anthropic_client", lambda: _fake_anthropic_client())

    assert await ocr._ocr_anthropic(b"%PDF", "application/pdf") == ANSWER
    assert counted == [("other", "ocr", "anthropic", settings.anthropic_ocr_model,
                        ANTHROPIC_COUNTS)]


async def test_extraction_is_counted_on_each_provider(counted, monkeypatch):
    from adelia.workers import extract

    await extract._complete(_fake_mistral_client('{"entities": []}'), "s", "t",
                            {"type": "json_object"})
    monkeypatch.setattr(extract, "get_anthropic_client",
                        lambda: _fake_anthropic_client(_anthropic_message('{"entities": []}')))
    await extract._request_entities_anthropic("s", "t")

    assert counted == [
        ("other", "extract", "mistral", settings.mistral_extraction_model, MISTRAL_COUNTS),
        ("other", "extract", "anthropic", settings.anthropic_extraction_model,
         ANTHROPIC_COUNTS),
    ]


async def test_the_consultation_summary_is_counted_on_each_provider(counted, monkeypatch):
    from adelia.workers import summarize

    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    monkeypatch.setattr(summarize.httpx, "AsyncClient", _FakeHttpx({
        "choices": [{"message": {"content": "- Revisión en un mes."}}],
        "usage": {"prompt_tokens": 700, "completion_tokens": 12},
    }))
    monkeypatch.setattr(summarize, "get_anthropic_client", lambda: _fake_anthropic_client())

    assert await summarize.summarize_consultation("[Hablante 1] ...") == "- Revisión en un mes."
    assert await summarize._summarize_anthropic("[Hablante 1] ...") == ANSWER

    assert counted == [
        ("other", "summarize", "mistral", settings.mistral_chat_model, MISTRAL_COUNTS),
        ("other", "summarize", "anthropic", settings.anthropic_chat_model, ANTHROPIC_COUNTS),
    ]


async def test_transcription_counts_audio_seconds_on_mistral_and_calls_on_openai(
    counted, monkeypatch
):
    from adelia.workers import transcribe

    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(transcribe.httpx, "AsyncClient", _FakeHttpx(
        {"text": "hola", "usage": {"prompt_audio_seconds": 63}}))

    class _OpenAI:
        def __init__(self, **kwargs):
            self.audio = SimpleNamespace(transcriptions=SimpleNamespace(
                create=AsyncMock(return_value="hola")))

    monkeypatch.setattr(transcribe, "AsyncOpenAI", _OpenAI)

    assert await transcribe._transcribe_mistral(b"ogg", "audio/ogg", diarize=False) == "hola"
    assert await transcribe._transcribe_openai(b"ogg", "audio/ogg") == "hola"

    assert counted == [
        ("other", "transcribe", "mistral", settings.mistral_stt_model, {"audio_seconds": 63}),
        ("other", "transcribe", "openai", settings.openai_stt_model, {}),
    ]


async def test_embeddings_are_counted_per_batch(counted, monkeypatch):
    from adelia.workers import embed as embed_mod

    fake_client = MagicMock()
    fake_client.embeddings.create_async = AsyncMock(
        return_value=SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.0] * 3)],
            usage=SimpleNamespace(prompt_tokens=42, completion_tokens=0),
        )
    )
    monkeypatch.setattr(embed_mod, "get_mistral_client", lambda: fake_client)

    with usage.surface("chat"):
        await embed_mod.embed_texts([QUESTION])

    assert counted == [(
        "chat", "embed", "mistral", settings.mistral_embed_model,
        {"input_tokens": 42, "output_tokens": 0, "cache_read_tokens": 0},
    )]


# --- briefing questions -----------------------------------------------------------------


async def test_the_briefing_questions_are_counted_on_each_provider(counted, monkeypatch):
    from adelia import llm
    from adelia.services import qa_pre_baker

    await qa_pre_baker._llm_structured_call(
        _fake_mistral_client('{"items": []}'), "s", "u", "mistral-medium-latest")
    monkeypatch.setattr(llm, "get_anthropic_client",
                        lambda: _fake_anthropic_client(_anthropic_message('{"items": []}')))
    data, tokens = await qa_pre_baker._anthropic_structured_call("s", "u", "claude-opus-5-5")

    assert (data, tokens) == ({"items": []}, 1050)
    assert counted == [
        ("other", "briefing_qa", "mistral", "mistral-medium-latest", MISTRAL_COUNTS),
        ("other", "briefing_qa", "anthropic", "claude-opus-5-5", ANTHROPIC_COUNTS),
    ]


# --- surfaces ---------------------------------------------------------------------------


@needs_pg
async def test_the_demo_labels_its_calls_demo(client):
    seen: list[str] = []

    async def _embed(texts):
        seen.append(usage.current_surface())
        return [[0.0] * 1024 for _ in texts]

    async def _retrieve(session, **kwargs):
        return []

    with patch("adelia.routers.demo.embed_texts", _embed), patch(
        "adelia.routers.demo.retrieve_evidence", _retrieve
    ):
        resp = await client.post("/demo/ask", json={"question": "¿Y la lactancia?"})

    assert resp.status_code == 200, resp.text
    assert seen and set(seen) == {"demo"}


def _bearer(user_id) -> dict[str, str]:
    from tests.test_auth import make_token

    return {"Authorization": f"Bearer {make_token(str(user_id))}"}


async def _guest_user() -> uuid.UUID:
    from adelia.models import User

    async with AsyncSessionLocal() as session:
        user = User(email=f"guest-{uuid.uuid4().hex}@guest.invalid", is_guest=True)
        session.add(user)
        await session.commit()
        return user.id


@needs_pg
@pytest.mark.parametrize("guest", [False, True], ids=["account", "guest"])
async def test_the_agent_labels_its_turn_agent_or_guest(client, monkeypatch, guest):
    from adelia.agent.events import AgentEvent
    from tests.db_helpers import make_user

    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    user_id = await (_guest_user() if guest else make_user())
    seen: list[str] = []

    async def fake_turn(**kwargs):
        seen.append(usage.current_surface())
        yield AgentEvent(type="error", content="x")

    with patch("adelia.routers.agent.run_turn", fake_turn):
        resp = await client.post("/agent/turn", headers=_bearer(user_id),
                                 json={"message": "hola"})

    assert resp.status_code == 200, resp.text
    assert seen == ["guest" if guest else "agent"]


@needs_pg
@pytest.mark.parametrize("guest", [False, True], ids=["account", "guest"])
async def test_the_chat_labels_its_answer_chat_or_guest(client, monkeypatch, guest):
    from adelia.services.chat_orchestrator import ChatEvent
    from tests.db_helpers import make_user

    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    user_id = await (_guest_user() if guest else make_user())
    seen: list[str] = []

    async def fake_answer(**kwargs):
        seen.append(usage.current_surface())
        yield ChatEvent(type="error", content="x")

    with patch("adelia.routers.chat.answer_question_streaming", fake_answer):
        resp = await client.post("/chat", headers=_bearer(user_id),
                                 json={"question": "¿Es normal que regurgite?"})

    assert resp.status_code == 200, resp.text
    assert seen == ["guest" if guest else "chat"]


async def test_a_document_pipeline_labels_its_calls_ingestion(monkeypatch):
    from adelia.routers import documents

    seen: list[str] = []

    async def fake_inner(*args, **kwargs):
        seen.append(usage.current_surface())

    monkeypatch.setattr(documents, "_process_document_inner", fake_inner)

    await asyncio.create_task(documents.process_document(uuid.uuid4(), "application/pdf"))

    assert seen == ["ingestion"]


async def test_the_briefing_pipeline_is_labelled_briefing():
    from adelia.services import briefing_orchestrator

    assert getattr(briefing_orchestrator.run, "__usage_surface__", None) == "briefing"


async def test_the_boot_corpus_load_is_labelled_corpus(monkeypatch):
    from adelia import main

    seen: list[str] = []

    async def fake_seed():
        seen.append(usage.current_surface())
        return (0, 0)

    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    with patch("adelia.enrichment.evidence_loader.load_seed_if_empty", fake_seed), patch(
        "adelia.enrichment.evidence_loader.load_evidence_file", AsyncMock(return_value=(0, 0))
    ), patch("adelia.enrichment.experience_loader.load_experience_dir",
             AsyncMock(return_value=(0, 0))):
        await main.load_startup_corpora()

    assert seen == ["corpus"]
    assert usage.current_surface() == "other"


async def test_a_guests_seed_embeddings_are_labelled_guest(monkeypatch):
    from adelia.services import guest
    from adelia.workers import embed as embed_mod

    seen: list[str] = []

    async def fake_embed(texts):
        seen.append(usage.current_surface())
        raise RuntimeError("no key")

    monkeypatch.setattr(embed_mod, "embed_texts", fake_embed)

    await guest.fill_seed_embeddings(uuid.uuid4(), {"sha": "Lucía, 7 meses"})

    assert seen == ["guest"]


# --- a counter that fails never changes the answer --------------------------------------


@needs_pg
@pytest.mark.parametrize("failure", ["raises", "hangs"])
async def test_a_broken_counter_never_changes_the_demo_answer(client, monkeypatch, failure):
    from adelia.enrichment.evidence_retrieval import EvidenceMatch

    async def broken_record(*args, **kwargs):
        if failure == "raises":
            raise RuntimeError("usage_counters is gone")
        await asyncio.Event().wait()

    monkeypatch.setattr(usage, "record", broken_record)
    match = EvidenceMatch(
        chunk_id=uuid.uuid4(), source_id=uuid.uuid4(),
        source_title="Pediatric Gastroesophageal Reflux Clinical Practice Guidelines",
        organization="NASPGHAN-ESPGHAN", publication_year=2018, url="https://example.org/n",
        content="Regurgitation is common in infants.", chunk_index=0, distance=0.07,
    )

    async def _retrieve(session, **kwargs):
        return [match]

    def chunk(text, chunk_usage=None):
        return SimpleNamespace(data=SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=text))], usage=chunk_usage))

    async def fake_stream():
        yield chunk("La regurgitación es habitual [ev_1].",
                    SimpleNamespace(prompt_tokens=700, completion_tokens=12))

    fake_client = MagicMock()
    fake_client.chat.stream_async = AsyncMock(side_effect=lambda **kw: fake_stream())
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")

    with patch("adelia.routers.demo.embed_texts", return_value=[[0.0] * 1024]), patch(
        "adelia.routers.demo.retrieve_evidence", _retrieve
    ), patch("adelia.services.chat_orchestrator.get_mistral_client", lambda: fake_client):
        resp = await asyncio.wait_for(client.post(
            "/demo/ask",
            json={"question": "¿Es normal que regurgite tras cada toma?", "locale": "es"},
        ), timeout=30)

    assert resp.status_code == 200, resp.text
    assert "La regurgitación es habitual" in resp.json()["answer"]
    await usage.drain(grace_s=0.05)


# --- what is written is labels and integers -----------------------------------------------


@needs_pg
async def test_a_real_write_through_a_real_path_keeps_no_text(monkeypatch):
    from adelia.services import chat_orchestrator

    the_day = date(2001, 1, 1) + timedelta(days=random.randrange(3000))
    monkeypatch.setattr(usage, "utc_today", lambda: the_day)

    def chunk(text, chunk_usage=None):
        return SimpleNamespace(data=SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=text))], usage=chunk_usage))

    async def fake_stream():
        yield chunk(ANSWER, SimpleNamespace(prompt_tokens=700, completion_tokens=12))

    fake_client = MagicMock()
    fake_client.chat.stream_async = AsyncMock(return_value=fake_stream())
    monkeypatch.setattr(chat_orchestrator, "get_mistral_client", lambda: fake_client)

    try:
        with usage.surface("chat"):
            pieces = [p async for p in chat_orchestrator._stream_mistral_tokens(
                [{"role": "user", "content": QUESTION}])]
        await usage.drain()
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                sa.select(UsageCounter).where(UsageCounter.day == the_day))).scalars().all()
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(sa.delete(UsageCounter).where(UsageCounter.day == the_day))
            await session.commit()

    assert "".join(pieces) == ANSWER
    assert len(rows) == 1
    row = {c: getattr(rows[0], c) for c in UsageCounter.__table__.columns.keys()}
    assert row["surface"] == "chat" and row["calls"] == 1 and row["input_tokens"] == 700
    dumped = json.dumps(row, default=str)
    for fragment in ("regurgit", "Lucía", "habitual"):
        assert fragment not in dumped
