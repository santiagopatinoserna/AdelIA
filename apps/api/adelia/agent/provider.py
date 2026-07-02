from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol

from adelia.config import settings


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ProviderStep:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class AgentProvider(Protocol):
    async def stream_step(
        self, *, system: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[dict]: ...


class AnthropicProvider:
    def __init__(self) -> None:
        from anthropic import AsyncAnthropic

        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def stream_step(
        self, *, system: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[dict]:
        async with self._client.messages.stream(
            model=settings.agent_model,
            max_tokens=2048,
            system=system,
            messages=messages,
            tools=tools,
            thinking={"type": "disabled"},
        ) as stream:
            async for event in stream:
                if event.type == "text":
                    yield {"type": "token", "text": event.text}
            final = await stream.get_final_message()
        for block in final.content:
            if getattr(block, "type", None) == "tool_use":
                yield {"type": "tool_call", "id": block.id, "name": block.name, "args": block.input}
        yield {"type": "stop", "stop_reason": final.stop_reason}


def get_provider() -> AgentProvider:
    provider = settings.llm_provider
    if provider in ("anthropic", "", "mistral"):
        # default agent brain is Claude even if OCR/embeddings use Mistral
        return AnthropicProvider()
    raise RuntimeError(f"Agent provider not implemented: {provider}")
