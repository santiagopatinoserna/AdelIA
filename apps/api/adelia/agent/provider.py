from __future__ import annotations

import json
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


def _to_mistral_messages(system: str, messages: list[dict]) -> list[dict]:
    """Translate the Anthropic-shaped agent history into Mistral/OpenAI chat messages.

    The orchestrator (adelia/agent/orchestrator.py) always builds history in Anthropic's
    shape: assistant turns as a content block-list (text + tool_use), tool results as a
    user turn with a content block-list of tool_result blocks, and plain user turns as a
    bare string. This function is the single place that understands both shapes.
    """
    out: list[dict] = [{"role": "system", "content": system}]
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            for block in content or []:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        }
                    )
            mistral_msg: dict = {"role": "assistant", "content": "".join(text_parts)}
            if tool_calls:
                mistral_msg["tool_calls"] = tool_calls
            out.append(mistral_msg)
            continue

        if role == "user":
            for block in content or []:
                if block.get("type") == "tool_result":
                    tool_msg: dict = {
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": block.get("content", ""),
                    }
                    if "name" in block:
                        tool_msg["name"] = block["name"]
                    out.append(tool_msg)
                else:
                    out.append({"role": "user", "content": str(block)})
            continue

        # Unrecognized shape: pass through best-effort.
        out.append({"role": role, "content": content})
    return out


def _to_mistral_tools(tools: list[dict]) -> list[dict]:
    """Translate Anthropic tool schemas ({"name","description","input_schema"}) into
    Mistral/OpenAI function-tool schemas."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        }
        for t in tools
    ]


def _mistral_text(content) -> str:
    """Mistral assistant message content is usually a plain string, but the SDK types it
    as `str | list[ContentChunk] | None`. Normalize defensively to a string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for chunk in content:
            text = getattr(chunk, "text", None)
            if text is None and isinstance(chunk, dict):
                text = chunk.get("text")
            if text:
                parts.append(text)
        return "".join(parts)
    return str(content)


class MistralProvider:
    """Fallback agent provider used when only MISTRAL_API_KEY is configured (prod)."""

    def __init__(self) -> None:
        if not settings.mistral_api_key:
            raise RuntimeError("MISTRAL_API_KEY not set")

    async def stream_step(
        self, *, system: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[dict]:
        from adelia.llm import get_mistral_client, reasoning_effort_kwargs

        client = get_mistral_client()
        # chat_reasoning_effort is the same knob as the RAG chat's: unset, this
        # call is unchanged. Mistral does not document how reasoning_effort
        # combines with tool calling, so enabling it also needs an agent run
        # (apps/api/docs/MODELOS.md). _mistral_text already drops thinking chunks.
        resp = await client.chat.complete_async(
            model=settings.mistral_chat_model,
            messages=_to_mistral_messages(system, messages),
            tools=_to_mistral_tools(tools),
            tool_choice="auto",
            temperature=0.2,
            **reasoning_effort_kwargs(
                settings.chat_reasoning_effort,
                settings.mistral_chat_model,
                setting="chat_reasoning_effort",
            ),
        )
        choice = resp.choices[0]
        message = choice.message
        yield {"type": "token", "text": _mistral_text(message.content)}
        for tc in message.tool_calls or []:
            yield {
                "type": "tool_call",
                "id": tc.id,
                "name": tc.function.name,
                "args": json.loads(tc.function.arguments),
            }
        yield {"type": "stop", "stop_reason": choice.finish_reason}


def get_provider() -> AgentProvider:
    # llm_provider="anthropic" is a hard requirement: never silently fall back to
    # Mistral, fail loudly instead so a misconfigured deploy is obvious.
    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        return AnthropicProvider()

    # Otherwise (llm_provider unset/"mistral"/anything else): key-presence fallback.
    # Anthropic is the richer streaming agent brain and wins when both keys are
    # configured (e.g. local/dev boxes); Mistral is the prod fallback when only
    # MISTRAL_API_KEY is set, which is what this function exists to unblock.
    if settings.anthropic_api_key:
        return AnthropicProvider()
    if settings.mistral_api_key:
        return MistralProvider()
    raise RuntimeError("No agent LLM key configured")
