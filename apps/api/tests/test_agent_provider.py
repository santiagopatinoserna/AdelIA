from adelia.config import settings
from adelia.agent.provider import ToolCall, ProviderStep, get_provider, AnthropicProvider


def test_get_provider_default_is_anthropic(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "x")
    p = get_provider()
    assert isinstance(p, AnthropicProvider)


def test_toolcall_shape():
    tc = ToolCall(id="t1", name="evaluar_labs", args={"name": "Hb", "value": 9})
    step = ProviderStep(text="ok", tool_calls=[tc])
    assert step.tool_calls[0].name == "evaluar_labs"
