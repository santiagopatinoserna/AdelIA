"""LLM_PROVIDER=anthropic: every text-generation surface reaches Claude, and nothing else moves.

No key and no network: each test builds the real AsyncAnthropic client on an
httpx.MockTransport, so what is asserted is the JSON body the SDK would send and
the parsing of a reply in the API's own wire format. That catches what a stub
cannot: a keyword the installed SDK does not accept, or a thinking block that
leaks into the answer. The suite runs (and must pass) in CI without secrets.
"""
from __future__ import annotations

import json

import httpx
import pytest

from adelia import llm
from adelia.agent import route as route_mod
from adelia.config import settings
from adelia.services import chat_orchestrator, qa_pre_baker
from adelia.workers import extract as extract_mod
from adelia.workers import ocr as ocr_mod
from adelia.workers import summarize as summarize_mod

# ---------------------------------------------------------------------------
# A real client on a fake wire
# ---------------------------------------------------------------------------


def _message(text: str, *, stop_reason: str = "end_turn") -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-test",
        "content": [
            {"type": "thinking", "thinking": "SECRET REASONING", "signature": "sig"},
            {"type": "text", "text": text},
        ],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 11, "output_tokens": 4},
    }


def _sse(pieces: list[str], *, stop_reason: str = "end_turn") -> str:
    events = [
        {
            "type": "message_start",
            "message": {**_message(""), "content": [], "stop_reason": None},
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": "", "signature": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "SECRET REASONING"},
        },
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
        *[
            {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": p}}
            for p in pieces
        ],
        {"type": "content_block_stop", "index": 1},
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": 4},
        },
        {"type": "message_stop"},
    ]
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)


class _Wire:
    """Records every request body and answers with the queued reply."""

    def __init__(self, *, json_reply: dict | None = None, sse_reply: str | None = None):
        self.bodies: list[dict] = []
        self._json_reply = json_reply
        self._sse_reply = sse_reply

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        if self._sse_reply is not None:
            return httpx.Response(
                200, text=self._sse_reply, headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(200, json=self._json_reply)

    def client(self):
        from anthropic import AsyncAnthropic

        return AsyncAnthropic(
            api_key="test-key",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self.handler)),
        )


@pytest.fixture
def anthropic_on(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")


def _wire_into(monkeypatch, wire: _Wire, *modules) -> None:
    client = wire.client()
    for module in (llm, *modules):
        monkeypatch.setattr(module, "get_anthropic_client", lambda: client)


# ---------------------------------------------------------------------------
# The helpers in adelia.llm
# ---------------------------------------------------------------------------


def test_an_explicit_provider_wins_over_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mistral")
    assert llm.uses_anthropic("anthropic")
    assert not llm.uses_anthropic()
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    assert llm.uses_anthropic()
    assert not llm.uses_anthropic("mistral")


def test_the_client_refuses_to_start_without_a_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        llm.get_anthropic_client()


def test_the_workspace_header_rides_on_every_client_when_set(monkeypatch):
    """A key linked to the organization, not to a workspace, is answered with a
    400 on every call that does not name the workspace."""
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "anthropic_workspace_id", "")
    assert "default_headers" not in llm.anthropic_client_kwargs()

    monkeypatch.setattr(settings, "anthropic_workspace_id", "wrkspc_test")
    assert llm.anthropic_client_kwargs() == {
        "api_key": "test-key",
        "default_headers": {"anthropic-workspace-id": "wrkspc_test"},
    }


async def test_the_workspace_header_reaches_the_wire(monkeypatch, anthropic_on):
    from anthropic import AsyncAnthropic

    monkeypatch.setattr(settings, "anthropic_workspace_id", "wrkspc_test")
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("anthropic-workspace-id"))
        return httpx.Response(200, json=_message("ok"))

    client = AsyncAnthropic(
        **llm.anthropic_client_kwargs(),
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(summarize_mod, "get_anthropic_client", lambda: client)

    await summarize_mod.summarize_consultation("texto")

    assert seen == ["wrkspc_test"]


def test_anthropic_json_schema_closes_objects_and_leaves_the_mistral_schema_alone():
    """The Mistral briefing call keeps sending _QA_JSON_SCHEMA as it is, so the
    rewrite must work on a copy."""
    original = json.dumps(qa_pre_baker._QA_JSON_SCHEMA, sort_keys=True)
    out = llm.anthropic_json_schema(qa_pre_baker._QA_JSON_SCHEMA)
    assert json.dumps(qa_pre_baker._QA_JSON_SCHEMA, sort_keys=True) == original

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
            assert not isinstance(node.get("type"), list)
            assert "minLength" not in node and "maxItems" not in node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(out)


# ---------------------------------------------------------------------------
# The RAG chat and /demo
# ---------------------------------------------------------------------------


async def _chat_pieces(provider=None, history=None) -> list[str]:
    return [
        p
        async for p in chat_orchestrator._stream_llm_tokens(
            "SYSTEM", "pregunta", history=history, provider=provider
        )
    ]


async def test_chat_streams_only_the_text_and_sends_no_sampling(monkeypatch, anthropic_on):
    wire = _Wire(sse_reply=_sse(["Hola ", "mundo"]))
    _wire_into(monkeypatch, wire, chat_orchestrator)
    history = [
        {"role": "assistant", "content": "una respuesta que abre la ventana"},
        {"role": "user", "content": "antes"},
        {"role": "assistant", "content": "respuesta"},
    ]

    pieces = await _chat_pieces(history=history)

    assert pieces == ["Hola ", "mundo"]
    body = wire.bodies[0]
    assert body["model"] == settings.anthropic_chat_model
    assert body["system"] == "SYSTEM"
    assert body["stream"] is True
    assert body["output_config"] == {"effort": "medium"}
    # The window kept by routers/chat may open on an assistant turn; Anthropic
    # 400s on that, so it is dropped and the conversation starts with the parent.
    assert body["messages"] == [
        {"role": "user", "content": "antes"},
        {"role": "assistant", "content": "respuesta"},
        {"role": "user", "content": "pregunta"},
    ]
    assert not {"temperature", "top_p", "top_k", "thinking"} & body.keys()


async def test_chat_refusal_ends_the_turn_as_an_error(monkeypatch, anthropic_on):
    wire = _Wire(sse_reply=_sse(["Hola"], stop_reason="refusal"))
    _wire_into(monkeypatch, wire, chat_orchestrator)
    with pytest.raises(llm.AnthropicRefusal):
        await _chat_pieces()


async def test_the_demo_provider_reaches_claude_while_the_chat_stays_on_mistral(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mistral")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    wire = _Wire(sse_reply=_sse(["ok"]))
    _wire_into(monkeypatch, wire, chat_orchestrator)

    def no_mistral():
        raise AssertionError("the demo's provider must win over llm_provider")

    monkeypatch.setattr(chat_orchestrator, "get_mistral_client", no_mistral)

    assert await _chat_pieces(provider="anthropic") == ["ok"]
    assert len(wire.bodies) == 1


# ---------------------------------------------------------------------------
# The route classifier
# ---------------------------------------------------------------------------


@pytest.mark.routing_model_layer  # drives the model layer with its own fake wire
async def test_route_uses_the_small_model_at_low_effort(monkeypatch, anthropic_on):
    wire = _Wire(json_reply=_message('{"intent": "question", "confidence": 0.9}'))
    _wire_into(monkeypatch, wire, route_mod)

    decision = await route_mod.route_by_model("¿cuánta leche toma un bebé de 4 meses?")

    assert decision.intent == "question"
    assert decision.via == "model"
    body = wire.bodies[0]
    assert body["model"] == settings.anthropic_routing_model
    assert body["output_config"] == {"effort": "low"}
    assert not {"temperature", "thinking"} & body.keys()


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------


async def test_extraction_keeps_the_value_object_and_still_screens_quotes(
    monkeypatch, anthropic_on
):
    """The reason this path asks by prompt: a schema-enforced reply could only
    carry `value: {}`, and the lab reading below would be stored empty."""
    reply = {
        "entities": [
            {
                "entity_type": "observation",
                "name": "Glucosa",
                "value": {"value": 95, "unit": "mg/dL"},
                "raw_quote": "Glucosa 95 mg/dL",
                "confidence": 0.9,
            },
            {
                "entity_type": "medication",
                "name": "Inventada",
                "raw_quote": "esto no aparece en el documento",
                "confidence": 0.9,
            },
        ]
    }
    wire = _Wire(json_reply=_message(json.dumps(reply)))
    _wire_into(monkeypatch, wire, extract_mod)

    def no_mistral():
        raise AssertionError("extraction must not reach Mistral with llm_provider=anthropic")

    monkeypatch.setattr(extract_mod, "get_mistral_client", no_mistral)

    result = await extract_mod.extract_entities("Analítica: Glucosa 95 mg/dL.")

    assert [e.name for e in result] == ["Glucosa"]
    assert result[0].value == {"value": 95, "unit": "mg/dL"}
    assert result.report.path == "json_object"
    assert result.report.dropped["quote_not_verbatim"] == 1
    body = wire.bodies[0]
    assert body["model"] == settings.anthropic_extraction_model
    assert body["system"] == extract_mod.SYSTEM_PROMPT
    assert body["messages"] == [
        {"role": "user", "content": "Document:\n\nAnalítica: Glucosa 95 mg/dL."}
    ]
    assert body["output_config"] == {"effort": "medium"}
    assert "temperature" not in body


# ---------------------------------------------------------------------------
# The briefing Q&A
# ---------------------------------------------------------------------------


async def _bake(**kwargs):
    return await qa_pre_baker.bake_questions(
        specialty=qa_pre_baker.Specialty.DEFAULT,
        entities_text="x",
        specialty_hints="x",
        source_raw_texts={"doc_1": "x"},
        **kwargs,
    )


async def test_briefing_sends_the_closed_schema_and_counts_tokens(monkeypatch, anthropic_on):
    wire = _Wire(json_reply=_message('{"items": []}'))
    _wire_into(monkeypatch, wire)

    def no_mistral():
        raise AssertionError("the briefing must not build a Mistral client")

    monkeypatch.setattr(qa_pre_baker, "_build_client", no_mistral)

    items, meta = await _bake()

    assert items == []
    assert meta.model == settings.anthropic_briefing_model
    assert meta.tokens_used == 15
    body = wire.bodies[0]
    assert body["model"] == settings.anthropic_briefing_model
    assert body["output_config"] == {
        "effort": "medium",
        "format": {
            "type": "json_schema",
            "schema": llm.anthropic_json_schema(qa_pre_baker._QA_JSON_SCHEMA),
        },
    }
    assert "temperature" not in body

    _, meta = await _bake(model="explicit")
    assert wire.bodies[1]["model"] == "explicit"
    assert meta.model == "explicit"


async def test_briefing_refusal_is_a_prebaker_error(monkeypatch, anthropic_on):
    wire = _Wire(json_reply=_message("", stop_reason="refusal"))
    _wire_into(monkeypatch, wire)
    with pytest.raises(qa_pre_baker.QAPrebakerError):
        await _bake()


# ---------------------------------------------------------------------------
# The consultation summary
# ---------------------------------------------------------------------------


async def test_summary_goes_through_the_sdk_with_the_same_prompt(monkeypatch, anthropic_on):
    wire = _Wire(json_reply=_message("- Fiebre de 38 grados.\n"))
    _wire_into(monkeypatch, wire, summarize_mod)

    async def no_http(*args, **kwargs):
        raise AssertionError("the summary must not POST to Mistral")

    monkeypatch.setattr(httpx.AsyncClient, "post", no_http)

    summary = await summarize_mod.summarize_consultation("[Hablante 1] Tiene 38 de fiebre.")

    assert summary == "- Fiebre de 38 grados."
    body = wire.bodies[0]
    assert body["model"] == settings.anthropic_chat_model
    assert body["system"] == summarize_mod._SYSTEM
    assert body["output_config"] == {"effort": "low"}


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------


def _no_mistral_ocr(monkeypatch):
    async def no_http(*args, **kwargs):
        raise AssertionError("OCR must not POST to Mistral with llm_provider=anthropic")

    monkeypatch.setattr(httpx.AsyncClient, "post", no_http)


@pytest.mark.parametrize(
    ("mime_type", "block_type"),
    [("application/pdf", "document"), ("image/jpeg", "image"), ("image/png", "image")],
)
async def test_ocr_sends_the_file_to_claude_as_the_right_block(
    monkeypatch, anthropic_on, mime_type, block_type
):
    wire = _Wire(sse_reply=_sse(["| Glucosa | 95 mg/dL |"]))
    _wire_into(monkeypatch, wire, ocr_mod)
    _no_mistral_ocr(monkeypatch)

    text = await ocr_mod.extract_text_from_pdf(b"%PDF-1.4 body", mime_type)

    assert text == "| Glucosa | 95 mg/dL |"
    body = wire.bodies[0]
    assert body["model"] == settings.anthropic_ocr_model
    assert body["output_config"] == {"effort": "low"}
    assert body["stream"] is True
    file_block, prompt_block = body["messages"][0]["content"]
    assert file_block == {
        "type": block_type,
        "source": {
            "type": "base64",
            "media_type": mime_type,
            "data": "JVBERi0xLjQgYm9keQ==",
        },
    }
    assert prompt_block["type"] == "text"
    assert "exactly as it is written" in prompt_block["text"]


async def test_ocr_of_a_page_without_text_is_empty(monkeypatch, anthropic_on):
    """documents.py reads "" as "nothing readable": a caption alone must not
    turn an unreadable photo into a ready document."""
    wire = _Wire(sse_reply=_sse(["NO_TEXT"]))
    _wire_into(monkeypatch, wire, ocr_mod)
    _no_mistral_ocr(monkeypatch)

    assert await ocr_mod.extract_text_from_pdf(b"\x89PNG", "image/png") == ""


async def test_ocr_refusal_fails_the_document_instead_of_storing_nothing(
    monkeypatch, anthropic_on
):
    wire = _Wire(sse_reply=_sse([], stop_reason="refusal"))
    _wire_into(monkeypatch, wire, ocr_mod)
    _no_mistral_ocr(monkeypatch)

    with pytest.raises(llm.AnthropicRefusal):
        await ocr_mod.extract_text_from_pdf(b"%PDF", "application/pdf")
