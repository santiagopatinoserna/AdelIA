"""Model names live in settings, and the reasoning-effort seam is inert by default.

Nothing here calls a provider and nothing needs a key: every call is a stub, so
this file runs (and must pass) in CI without secrets.

What it pins
------------
* The shipped default of every model setting. Changing one is a model change,
  which has an approval procedure (apps/api/docs/MODELOS.md); updating the
  value in EXPECTED_DEFAULTS is the visible diff that procedure asks for, in
  the same commit that flips the default in config.py.
* That no model name is a literal inside logic any more (static scan).
* That the workers read their model from settings, and that with the shipped
  defaults the request each one sends is the one it sent before the names moved.
* That the embedding model's dimension is declared in one place and equals the
  real vector columns. Changing the embedding model is a migration, not a config
  edit; a silent dimension mismatch would corrupt retrieval.
* The reasoning-effort seam, both ways: unset adds nothing to the request, set
  adds exactly one field, only on models documented to accept it, and a
  thinking trace never reaches the answer.
"""
from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from mistralai.client.models import TextChunk, ThinkChunk
from pydantic import ValidationError

import adelia
from adelia import llm
from adelia.agent import provider as agent_provider
from adelia.config import EMBEDDING_MODEL_DIMENSIONS, Settings, settings
from adelia.services import chat_orchestrator, qa_pre_baker
from adelia.workers import embed as embed_mod
from adelia.workers import extract as extract_mod
from adelia.workers.ocr import extract_text_from_pdf

# ---------------------------------------------------------------------------
# The shipped defaults
# ---------------------------------------------------------------------------

EXPECTED_DEFAULTS = {
    "agent_model": "claude-sonnet-5",
    "mistral_chat_model": "mistral-medium-latest",
    "openai_chat_model": "gpt-5.1",
    "mistral_extraction_model": "mistral-medium-latest",
    "mistral_briefing_model": "mistral-medium-latest",
    "mistral_ocr_model": "mistral-ocr-latest",
    "mistral_embed_model": "mistral-embed",
    # The two below are named in docs/legal/dpia-grabacion-consulta.md: changing
    # the transcription provider or model is a legal change, not only a
    # technical one (MODELOS.md, section 5).
    "stt_provider": "mistral",
    "mistral_stt_model": "voxtral-mini-latest",
    "openai_stt_model": "whisper-1",
    "llm_provider": "mistral",
    # None means "send no reasoning_effort field", which is today's request.
    "chat_reasoning_effort": None,
    "briefing_reasoning_effort": None,
}


@pytest.mark.parametrize(("name", "expected"), EXPECTED_DEFAULTS.items())
def test_shipped_default(name, expected):
    """Read off the field, not the live `settings`, so a developer's .env cannot
    mask a changed default."""
    assert Settings.model_fields[name].default == expected


def test_no_model_name_is_a_literal_in_logic():
    """A model id may be written in exactly two places: config.py (the defaults)
    and llm.py (the reasoning-effort allow-list). Docstrings and comments are fine."""
    model_id = re.compile(
        r"^(mistral-(medium|small|large|ocr|embed)[a-z0-9.-]*|voxtral-[a-z0-9.-]+"
        r"|whisper-\d|claude-[a-z0-9.-]+|gpt-[a-z0-9.-]+)$"
    )
    allowed = {"config.py", "llm.py"}
    root = Path(adelia.__file__).parent
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if path.relative_to(root).as_posix() in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bare_strings = {
            id(n.value)
            for n in ast.walk(tree)
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in bare_strings
                and model_id.match(node.value)
            ):
                offenders.append(f"{path.relative_to(root)}:{node.lineno} {node.value!r}")
    assert not offenders, "model name hardcoded in logic, move it to config.py: " + "; ".join(
        offenders
    )


# ---------------------------------------------------------------------------
# OCR: the name comes from settings, and the default request is unchanged
# ---------------------------------------------------------------------------


class _OcrResponse:
    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"pages": [{"markdown": "Glucosa 95"}]}


def _capture_ocr_post(monkeypatch) -> dict:
    captured: dict = {}

    async def fake_post(self, url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return _OcrResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    return captured


async def test_ocr_default_request_is_the_one_sent_before_the_name_moved(monkeypatch):
    captured = _capture_ocr_post(monkeypatch)
    monkeypatch.setattr(
        settings, "mistral_ocr_model", Settings.model_fields["mistral_ocr_model"].default
    )

    text = await extract_text_from_pdf(b"%PDF-1.4 body", "application/pdf")

    assert text == "Glucosa 95"
    assert captured["url"] == "https://api.mistral.ai/v1/ocr"
    assert captured["json"] == {
        "model": "mistral-ocr-latest",
        "document": {
            "type": "document_url",
            "document_url": "data:application/pdf;base64,JVBERi0xLjQgYm9keQ==",
        },
        "include_image_base64": False,
    }


async def test_ocr_sends_the_model_from_settings(monkeypatch):
    captured = _capture_ocr_post(monkeypatch)
    monkeypatch.setattr(settings, "mistral_ocr_model", "ocr-from-settings")

    await extract_text_from_pdf(b"%PDF", "application/pdf")

    assert captured["json"]["model"] == "ocr-from-settings"


# ---------------------------------------------------------------------------
# Embeddings: the name comes from settings, and its dimension is one decision
# ---------------------------------------------------------------------------


def _embedding_client(calls: list[dict]) -> MagicMock:
    async def fake_create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.0] * 1024) for _ in kwargs["inputs"]]
        )

    client = MagicMock()
    client.embeddings.create_async = AsyncMock(side_effect=fake_create)
    return client


async def test_embed_default_call_is_the_one_made_before_the_name_moved(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(embed_mod, "get_mistral_client", lambda: _embedding_client(calls))
    monkeypatch.setattr(
        settings, "mistral_embed_model", Settings.model_fields["mistral_embed_model"].default
    )

    await embed_mod.embed_texts(["uno", "dos"])

    assert calls == [{"model": "mistral-embed", "inputs": ["uno", "dos"]}]


async def test_embed_sends_the_model_from_settings(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(embed_mod, "get_mistral_client", lambda: _embedding_client(calls))
    monkeypatch.setattr(settings, "mistral_embed_model", "embed-from-settings")

    await embed_mod.embed_texts(["uno"])

    assert calls[0]["model"] == "embed-from-settings"


def test_configured_embedding_model_matches_the_vector_columns():
    """The one check that makes a silent dimension mismatch impossible to ship:
    the model's declared size must equal the size of both embedding columns."""
    from adelia.models import Chunk, EvidenceChunk

    expected = EMBEDDING_MODEL_DIMENSIONS[settings.mistral_embed_model]
    assert settings.embedding_dimension == expected
    assert Chunk.__table__.c.embedding.type.dim == expected
    assert EvidenceChunk.__table__.c.embedding.type.dim == expected


def test_mistral_embed_is_1024_dimensional():
    assert EMBEDDING_MODEL_DIMENSIONS == {"mistral-embed": 1024}


def test_an_unregistered_embedding_model_is_refused_at_boot():
    """A MISTRAL_EMBED_MODEL env override to a name nobody registered must fail
    loudly, not start serving vectors from a different space."""
    with pytest.raises(ValidationError, match="migration"):
        Settings(_env_file=None, mistral_embed_model="some-other-embed")


# ---------------------------------------------------------------------------
# Extraction and briefing: separate settings, same defaults as the old literals
# ---------------------------------------------------------------------------


def _extract_client(calls: list[dict]) -> MagicMock:
    async def fake_complete(**kwargs):
        calls.append(kwargs)
        message = SimpleNamespace(content='{"entities": []}')
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client = MagicMock()
    client.chat.complete_async = AsyncMock(side_effect=fake_complete)
    return client


async def test_extraction_default_call_is_the_one_made_before_the_name_moved(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(extract_mod, "get_mistral_client", lambda: _extract_client(calls))
    monkeypatch.setattr(
        settings,
        "mistral_extraction_model",
        Settings.model_fields["mistral_extraction_model"].default,
    )

    await extract_mod.extract_entities("nota clinica")

    assert calls == [
        {
            "model": "mistral-medium-latest",
            "messages": [
                {"role": "system", "content": extract_mod.SYSTEM_PROMPT},
                {"role": "user", "content": "Document:\n\nnota clinica"},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }
    ]


async def test_extraction_sends_the_model_from_settings(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(extract_mod, "get_mistral_client", lambda: _extract_client(calls))
    monkeypatch.setattr(settings, "mistral_extraction_model", "extract-from-settings")

    await extract_mod.extract_entities("nota clinica")

    assert calls[0]["model"] == "extract-from-settings"


def _briefing_client(calls: list[dict], content) -> MagicMock:
    async def fake_complete(**kwargs):
        calls.append(kwargs)
        message = SimpleNamespace(content=content)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(total_tokens=7)
        )

    client = MagicMock()
    client.chat.complete_async = AsyncMock(side_effect=fake_complete)
    return client


async def _bake(monkeypatch, calls: list[dict], content='{"items": []}', **kwargs):
    monkeypatch.setattr(
        qa_pre_baker, "_build_client", lambda: _briefing_client(calls, content)
    )
    return await qa_pre_baker.bake_questions(
        specialty=qa_pre_baker.Specialty.DEFAULT,
        entities_text="x",
        specialty_hints="x",
        source_raw_texts={"doc_1": "x"},
        **kwargs,
    )


async def test_briefing_model_defaults_to_the_setting_and_an_explicit_one_wins(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        settings, "mistral_briefing_model", Settings.model_fields["mistral_briefing_model"].default
    )

    _, meta = await _bake(monkeypatch, calls)
    assert calls[0]["model"] == "mistral-medium-latest"
    assert meta.model == "mistral-medium-latest"

    monkeypatch.setattr(settings, "mistral_briefing_model", "briefing-from-settings")
    _, meta = await _bake(monkeypatch, calls)
    assert calls[1]["model"] == "briefing-from-settings"
    assert meta.model == "briefing-from-settings"

    _, meta = await _bake(monkeypatch, calls, model="explicit")
    assert calls[2]["model"] == "explicit"
    assert meta.model == "explicit"


# ---------------------------------------------------------------------------
# The reasoning-effort seam: settings
# ---------------------------------------------------------------------------


def test_reasoning_effort_accepts_the_documented_values():
    s = Settings(_env_file=None, chat_reasoning_effort="high", briefing_reasoning_effort="none")
    assert s.chat_reasoning_effort == "high"
    assert s.briefing_reasoning_effort == "none"


def test_reasoning_effort_rejects_a_typo_at_boot():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, chat_reasoning_effort="hihg")


def test_a_blank_env_line_means_unset(monkeypatch):
    monkeypatch.setenv("CHAT_REASONING_EFFORT", "")
    monkeypatch.setenv("BRIEFING_REASONING_EFFORT", "  ")
    s = Settings(_env_file=None)
    assert s.chat_reasoning_effort is None
    assert s.briefing_reasoning_effort is None


# ---------------------------------------------------------------------------
# The reasoning-effort seam: the kwargs helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("unset", [None, ""])
def test_unset_effort_adds_nothing(unset):
    assert llm.reasoning_effort_kwargs(unset, "mistral-medium-3-5", setting="s") == {}


def test_set_effort_on_a_listed_model_is_forwarded_as_exactly_one_field():
    assert llm.reasoning_effort_kwargs("none", "mistral-medium-3-5", setting="s") == {
        "reasoning_effort": "none"
    }
    assert llm.reasoning_effort_kwargs("high", "mistral-large-4-0", setting="s") == {
        "reasoning_effort": "high"
    }


def test_a_dated_variant_of_a_listed_model_matches_but_a_lookalike_does_not():
    assert llm.supports_reasoning_effort("mistral-medium-3-5-2604")
    assert not llm.supports_reasoning_effort("mistral-medium-3-50")
    assert not llm.supports_reasoning_effort("mistral-medium-3")


def test_the_default_chat_alias_is_deliberately_not_on_the_list():
    """Mistral does not state what mistral-medium-latest points to, so the knob
    cannot reach it: using it means pinning a listed model id on purpose."""
    assert not llm.supports_reasoning_effort("mistral-medium-latest")
    assert (
        llm.reasoning_effort_kwargs("high", "mistral-medium-latest", setting="chat_reasoning_effort")
        == {}
    )


def test_set_effort_on_an_unlisted_model_is_dropped_with_one_warning(monkeypatch, caplog):
    monkeypatch.setattr(llm, "_warned_unsupported", set())
    with caplog.at_level(logging.WARNING, logger="adelia.llm"):
        for _ in range(3):
            assert llm.reasoning_effort_kwargs("high", "other-model", setting="my_setting") == {}
    warnings = [r for r in caplog.records if "my_setting" in r.getMessage()]
    assert len(warnings) == 1
    assert "other-model" in warnings[0].getMessage()


def test_content_text_keeps_strings_and_drops_thinking():
    assert llm.content_text("hola") == "hola"
    assert llm.content_text(None) == ""
    chunks = [
        ThinkChunk(thinking=[TextChunk(text="SECRET REASONING")]),
        TextChunk(text="Hola, "),
        TextChunk(text="mundo"),
    ]
    assert llm.content_text(chunks) == "Hola, mundo"
    dicts = [{"type": "thinking", "thinking": "SECRET"}, {"type": "text", "text": "ok"}]
    assert llm.content_text(dicts) == "ok"


def test_content_text_goes_by_chunk_type_not_by_which_fields_exist():
    """The SDK's thinking chunk happens to have no `text` field, which would drop it
    by accident. The rule is the type: a thinking chunk that did carry `text`
    (a future SDK shape, a stub) must still be dropped."""
    chunks = [
        {"type": "thinking", "text": "SECRET REASONING"},
        SimpleNamespace(type="thinking", text="SECRET TOO"),
        {"type": "text", "text": "ok"},
    ]
    assert llm.content_text(chunks) == "ok"


# ---------------------------------------------------------------------------
# The reasoning-effort seam: the RAG chat stream
# ---------------------------------------------------------------------------


def _delta_event(content) -> SimpleNamespace:
    delta = SimpleNamespace(content=content)
    return SimpleNamespace(data=SimpleNamespace(choices=[SimpleNamespace(delta=delta)]))


def _stream_client(events: list) -> MagicMock:
    async def stream():
        for event in events:
            yield event

    client = MagicMock()
    client.chat.stream_async = AsyncMock(return_value=stream())
    return client


async def _run_chat_stream(monkeypatch, events: list, *, model: str, effort) -> tuple:
    client = _stream_client(events)
    monkeypatch.setattr(chat_orchestrator, "get_mistral_client", lambda: client)
    monkeypatch.setattr(settings, "mistral_chat_model", model)
    monkeypatch.setattr(settings, "chat_reasoning_effort", effort)
    messages = [{"role": "user", "content": "hola"}]
    pieces = [p async for p in chat_orchestrator._stream_mistral_tokens(messages)]
    return pieces, client.chat.stream_async.await_args.kwargs, messages


async def test_chat_request_is_unchanged_when_effort_is_unset(monkeypatch):
    pieces, kwargs, messages = await _run_chat_stream(
        monkeypatch, [_delta_event("Hola ")], model="mistral-medium-latest", effort=None
    )
    assert pieces == ["Hola "]
    assert kwargs == {"model": "mistral-medium-latest", "messages": messages, "temperature": 0.2}


async def test_chat_request_carries_effort_when_set_on_a_listed_model(monkeypatch):
    _, kwargs, messages = await _run_chat_stream(
        monkeypatch, [_delta_event("Hola")], model="mistral-medium-3-5", effort="none"
    )
    assert kwargs == {
        "model": "mistral-medium-3-5",
        "messages": messages,
        "temperature": 0.2,
        "reasoning_effort": "none",
    }


async def test_chat_request_ignores_effort_on_an_unlisted_model(monkeypatch):
    monkeypatch.setattr(llm, "_warned_unsupported", set())
    _, kwargs, messages = await _run_chat_stream(
        monkeypatch, [_delta_event("Hola")], model="mistral-medium-latest", effort="high"
    )
    assert kwargs == {"model": "mistral-medium-latest", "messages": messages, "temperature": 0.2}


async def test_chat_never_streams_the_thinking_trace(monkeypatch):
    """With effort "high" the delta content is a list that opens with a thinking
    chunk. A parent must only ever see the text chunks."""
    events = [
        _delta_event([ThinkChunk(thinking=[TextChunk(text="SECRET REASONING")])]),
        _delta_event([ThinkChunk(thinking=[], closed=True), TextChunk(text="Hola ")]),
        _delta_event("mundo"),
    ]
    pieces, _, _ = await _run_chat_stream(
        monkeypatch, events, model="mistral-medium-3-5", effort="high"
    )
    assert pieces == ["Hola ", "mundo"]
    assert "SECRET" not in "".join(pieces)


# ---------------------------------------------------------------------------
# The reasoning-effort seam: the agent's Mistral fallback
# ---------------------------------------------------------------------------


async def _run_agent_step(monkeypatch, content, *, model: str, effort) -> tuple:
    calls: list[dict] = []

    async def fake_complete(**kwargs):
        calls.append(kwargs)
        message = SimpleNamespace(content=content, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])

    client = MagicMock()
    client.chat.complete_async = AsyncMock(side_effect=fake_complete)
    monkeypatch.setattr(llm, "get_mistral_client", lambda: client)
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    monkeypatch.setattr(settings, "mistral_chat_model", model)
    monkeypatch.setattr(settings, "chat_reasoning_effort", effort)

    messages = [{"role": "user", "content": "hola"}]
    tools = [{"name": "evaluar_labs", "description": "d", "input_schema": {"type": "object"}}]
    events = [
        e
        async for e in agent_provider.MistralProvider().stream_step(
            system="sys", messages=messages, tools=tools
        )
    ]
    expected_base = {
        "model": model,
        "messages": agent_provider._to_mistral_messages("sys", messages),
        "tools": agent_provider._to_mistral_tools(tools),
        "tool_choice": "auto",
        "temperature": 0.2,
    }
    return events, calls[0], expected_base


async def test_agent_request_is_unchanged_when_effort_is_unset(monkeypatch):
    events, kwargs, expected = await _run_agent_step(
        monkeypatch, "Hola", model="mistral-medium-latest", effort=None
    )
    assert kwargs == expected
    assert events[0] == {"type": "token", "text": "Hola"}


async def test_agent_request_carries_effort_when_set_on_a_listed_model(monkeypatch):
    _, kwargs, expected = await _run_agent_step(
        monkeypatch, "Hola", model="mistral-medium-3-5", effort="none"
    )
    assert kwargs == {**expected, "reasoning_effort": "none"}


async def test_agent_never_surfaces_the_thinking_trace(monkeypatch):
    content = [ThinkChunk(thinking=[TextChunk(text="SECRET REASONING")]), TextChunk(text="Hola")]
    events, _, _ = await _run_agent_step(
        monkeypatch, content, model="mistral-medium-3-5", effort="high"
    )
    assert events[0] == {"type": "token", "text": "Hola"}


# ---------------------------------------------------------------------------
# The reasoning-effort seam: the briefing Q&A pre-baker
# ---------------------------------------------------------------------------


def _briefing_expected_kwargs(model: str) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "user"},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "qa_items",
                "schema": qa_pre_baker._QA_JSON_SCHEMA,
                "strict": True,
            },
        },
        "temperature": 0.2,
    }


async def _briefing_call(monkeypatch, content, *, model: str, effort, chat_effort=None):
    calls: list[dict] = []
    monkeypatch.setattr(settings, "briefing_reasoning_effort", effort)
    monkeypatch.setattr(settings, "chat_reasoning_effort", chat_effort)
    parsed, tokens = await qa_pre_baker._llm_structured_call(
        _briefing_client(calls, content), "sys", "user", model
    )
    return parsed, tokens, calls[0]


async def test_briefing_request_is_unchanged_when_effort_is_unset(monkeypatch):
    parsed, tokens, kwargs = await _briefing_call(
        monkeypatch, '{"items": []}', model="mistral-medium-latest", effort=None
    )
    assert parsed == {"items": []}
    assert tokens == 7
    assert kwargs == _briefing_expected_kwargs("mistral-medium-latest")


async def test_briefing_request_carries_effort_when_set_on_a_listed_model(monkeypatch):
    _, _, kwargs = await _briefing_call(
        monkeypatch, '{"items": []}', model="mistral-medium-3-5", effort="high"
    )
    assert kwargs == {**_briefing_expected_kwargs("mistral-medium-3-5"), "reasoning_effort": "high"}


async def test_briefing_ignores_effort_on_an_unlisted_model(monkeypatch):
    monkeypatch.setattr(llm, "_warned_unsupported", set())
    _, _, kwargs = await _briefing_call(
        monkeypatch, '{"items": []}', model="mistral-medium-latest", effort="high"
    )
    assert kwargs == _briefing_expected_kwargs("mistral-medium-latest")


async def test_the_two_knobs_are_independent(monkeypatch):
    """Chat effort must not leak into the briefing call, or a cheap-and-fast chat
    setting would quietly weaken the doctor's briefing."""
    _, _, kwargs = await _briefing_call(
        monkeypatch,
        '{"items": []}',
        model="mistral-medium-3-5",
        effort=None,
        chat_effort="none",
    )
    assert "reasoning_effort" not in kwargs


async def test_briefing_parses_the_json_out_of_the_text_chunk(monkeypatch):
    content = [
        ThinkChunk(thinking=[TextChunk(text='{"items": "SECRET, not the answer"}')]),
        TextChunk(text='{"items": []}'),
    ]
    parsed, _, _ = await _briefing_call(
        monkeypatch, content, model="mistral-medium-3-5", effort="high"
    )
    assert parsed == {"items": []}
