"""Shared Mistral and Anthropic SDK clients, one instance per event loop.

Per-call construction (the v0.1 pattern) rebuilt the HTTP pool on every
embed/extract/chat/QA call. The cached client reuses connections. Under
uvicorn there is a single loop, so this is one instance per process; the
loop check exists because the SDK's async transport binds to the loop that
created it (pytest-asyncio gives every test its own loop — a plain
singleton dies there with 'Event loop is closed').

The API-key check stays per-call so a missing key still fails loudly at
the call site. The client binds the key present at first use per loop;
changing MISTRAL_API_KEY requires a process restart. The Anthropic client
(settings.llm_provider="anthropic") follows the same rules.
"""

import asyncio
import logging
from typing import Any

from anthropic import AsyncAnthropic, transform_schema
from mistralai.client.sdk import Mistral

from adelia.config import settings

logger = logging.getLogger(__name__)

_client: Mistral | None = None
_client_loop: asyncio.AbstractEventLoop | None = None
_anthropic_client: AsyncAnthropic | None = None
_anthropic_client_loop: asyncio.AbstractEventLoop | None = None

# Mistral model ids that docs.mistral.ai documents as accepting
# `reasoning_effort` (the "Reasoning" page, read 2026-10-14). Deliberately short
# and exact: an id is added here by a code change that also ran the evaluation in
# apps/api/docs/MODELOS.md, never because a name "looks like" it should work.
# An alias such as "mistral-medium-latest" is NOT listed, because Mistral's
# model card does not say what it points to, so a setting aimed at it would
# silently follow whatever the alias becomes. A dated variant of a listed id
# ("mistral-medium-3-5-2604") matches by prefix.
REASONING_EFFORT_MODELS: tuple[str, ...] = (
    "mistral-medium-3-5",
    "mistral-small-latest",
    "mistral-large-4-0",
)

# (setting, model) pairs already warned about, so a misaimed setting logs once per
# process instead of once per chat turn.
_warned_unsupported: set[tuple[str, str]] = set()


def supports_reasoning_effort(model: str) -> bool:
    return any(model == name or model.startswith(f"{name}-") for name in REASONING_EFFORT_MODELS)


def reasoning_effort_kwargs(effort: str | None, model: str, *, setting: str) -> dict[str, str]:
    """Extra chat kwargs for `reasoning_effort`, or {} when the request must not carry it.

    Spread into the SDK call (`**reasoning_effort_kwargs(...)`). An unset effort
    returns an empty dict, so the call is made with exactly the keyword arguments
    it had before this seam existed: that is what keeps the default request
    identical to the one sent today. A set effort on a model that is not on
    REASONING_EFFORT_MODELS also returns {} (one warning naming `setting`),
    because forwarding an unsupported parameter would turn a config typo into
    failed chat turns for a parent who has no way to fix it.
    """
    if not effort:
        return {}
    if not supports_reasoning_effort(model):
        if (setting, model) not in _warned_unsupported:
            _warned_unsupported.add((setting, model))
            logger.warning(
                "%s=%r is ignored: model %r is not in adelia.llm.REASONING_EFFORT_MODELS",
                setting,
                effort,
                model,
            )
        return {}
    return {"reasoning_effort": effort}


def content_text(content: Any) -> str:
    """The answer text of a Mistral message or stream-delta `content`.

    `content` is a plain string normally. With reasoning_effort="high" it is a
    LIST of chunks (a ThinkChunk with the reasoning trace, then TextChunk(s)), and
    while streaming it changes shape mid-response. Only "text" chunks are the
    answer: the thinking trace must never reach a parent, so it is dropped here,
    in the one function every Mistral reader goes through. A string (and None)
    comes back unchanged, which is why the default path behaves as before.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for chunk in content:
            kind = chunk.get("type") if isinstance(chunk, dict) else getattr(chunk, "type", None)
            if kind != "text":
                continue
            text = chunk.get("text") if isinstance(chunk, dict) else getattr(chunk, "text", None)
            if text:
                parts.append(text)
        return "".join(parts)
    return ""


def get_mistral_client() -> Mistral:
    global _client, _client_loop
    if not settings.mistral_api_key:
        raise RuntimeError("MISTRAL_API_KEY not set")
    loop = _running_loop()
    if _client is None or _client_loop is not loop:
        _client = Mistral(api_key=settings.mistral_api_key)
        _client_loop = loop
    return _client


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def uses_anthropic(provider: str | None = None) -> bool:
    """Whether generation goes to Anthropic. An explicit provider (only the
    public demo passes one, settings.demo_llm_provider) wins, else
    settings.llm_provider: the precedence chat_orchestrator and agent.route
    already apply to "openai"."""
    return (provider or settings.llm_provider) == "anthropic"


def anthropic_client_kwargs() -> dict[str, Any]:
    """Constructor arguments every AsyncAnthropic in the app shares.

    The workspace header is set on the client, not per call, so no surface can
    forget it: with a key linked to the organization instead of a workspace,
    one call without it is a 400.
    """
    kwargs: dict[str, Any] = {"api_key": settings.anthropic_api_key}
    if settings.anthropic_workspace_id:
        kwargs["default_headers"] = {"anthropic-workspace-id": settings.anthropic_workspace_id}
    return kwargs


def get_anthropic_client() -> AsyncAnthropic:
    global _anthropic_client, _anthropic_client_loop
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    loop = _running_loop()
    if _anthropic_client is None or _anthropic_client_loop is not loop:
        _anthropic_client = AsyncAnthropic(**anthropic_client_kwargs())
        _anthropic_client_loop = loop
    return _anthropic_client


class AnthropicRefusal(RuntimeError):
    """The model declined (stop_reason "refusal"), so there is no answer to use.

    A RuntimeError on purpose: the pipeline retry treats it like a config error
    and does not ask again (the same input gets the same decision), and the
    chat turns it into its error event instead of a half-written answer.
    """


def raise_on_refusal(message: Any) -> None:
    if getattr(message, "stop_reason", None) == "refusal":
        raise AnthropicRefusal(f"model {getattr(message, 'model', '?')} declined the request")


def anthropic_text(message: Any) -> str:
    """The answer text of an Anthropic Message: its `text` blocks, joined.

    The current Claude models think by default, and the reasoning arrives as
    separate `thinking` blocks. Only text blocks are the answer, the same rule
    content_text applies to Mistral's chunks: the reasoning never reaches a
    parent or a parser. A refusal raises instead of returning partial text.
    """
    raise_on_refusal(message)
    return "".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    )


def anthropic_json_schema(schema: dict) -> dict:
    """`schema` rewritten into the subset Anthropic structured outputs accept.

    The SDK's transform_schema closes every object (additionalProperties false
    is mandatory there) and moves the constraints the API does not enforce
    (minLength, maxItems...) into the description, so the caller keeps
    validating them. It rejects a list `type` such as ["string", "null"], so
    those become the equivalent anyOf first. Not for a schema with a free-form
    object: closing {"type": "object"} turns it into "must be {}", which is
    why workers.extract asks for its JSON by prompt instead.
    """

    def _union_types(node: Any) -> Any:
        if isinstance(node, list):
            return [_union_types(item) for item in node]
        if not isinstance(node, dict):
            return node
        node = {key: _union_types(value) for key, value in node.items()}
        if isinstance(node.get("type"), list):
            node["anyOf"] = [{"type": kind} for kind in node.pop("type")]
        return node

    return transform_schema(_union_types(schema))
