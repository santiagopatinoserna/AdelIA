from adelia.config import settings
from adelia.agent.provider import (
    ToolCall,
    ProviderStep,
    get_provider,
    AnthropicProvider,
    MistralProvider,
    _to_mistral_messages,
    _to_mistral_tools,
)


def test_get_provider_default_is_anthropic(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "x")
    p = get_provider()
    assert isinstance(p, AnthropicProvider)


def test_toolcall_shape():
    tc = ToolCall(id="t1", name="evaluar_labs", args={"name": "Hb", "value": 9})
    step = ProviderStep(text="ok", tool_calls=[tc])
    assert step.tool_calls[0].name == "evaluar_labs"


def test_get_provider_prefers_mistral_when_no_anthropic(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "mistral_api_key", "x")
    p = get_provider()
    assert isinstance(p, MistralProvider)


def test_get_provider_prefers_anthropic_when_key_set(monkeypatch):
    # llm_provider unset/empty -> key-presence fallback, Anthropic first.
    monkeypatch.setattr(settings, "llm_provider", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "x")
    monkeypatch.setattr(settings, "mistral_api_key", "y")
    p = get_provider()
    assert isinstance(p, AnthropicProvider)


def test_get_provider_raises_when_no_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "mistral_api_key", "")
    try:
        get_provider()
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_mistral_translate_messages():
    messages = [
        {"role": "user", "content": "hola"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "dejame revisar"},
                {"type": "tool_use", "id": "t1", "name": "evaluar_labs", "input": {"name": "Hb", "value": 9}},
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "Hb baja"}],
        },
    ]
    out = _to_mistral_messages("system prompt", messages)

    assert out[0] == {"role": "system", "content": "system prompt"}
    assert out[1] == {"role": "user", "content": "hola"}

    assistant_msg = out[2]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] == "dejame revisar"
    assert len(assistant_msg["tool_calls"]) == 1
    tc = assistant_msg["tool_calls"][0]
    assert tc["id"] == "t1"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "evaluar_labs"
    assert tc["function"]["arguments"] == '{"name": "Hb", "value": 9}'

    tool_msg = out[3]
    assert tool_msg == {"role": "tool", "tool_call_id": "t1", "content": "Hb baja"}


def test_mistral_translate_tools():
    tools = [
        {
            "name": "evaluar_labs",
            "description": "Evalua un lab.",
            "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        }
    ]
    out = _to_mistral_tools(tools)
    assert out == [
        {
            "type": "function",
            "function": {
                "name": "evaluar_labs",
                "description": "Evalua un lab.",
                "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            },
        }
    ]
