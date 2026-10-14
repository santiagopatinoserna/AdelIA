"""Shared Mistral SDK client — one instance per event loop.

Per-call construction (the v0.1 pattern) rebuilt the HTTP pool on every
embed/extract/chat/QA call. The cached client reuses connections. Under
uvicorn there is a single loop, so this is one instance per process; the
loop check exists because the SDK's async transport binds to the loop that
created it (pytest-asyncio gives every test its own loop — a plain
singleton dies there with 'Event loop is closed').

The API-key check stays per-call so a missing key still fails loudly at
the call site. The client binds the key present at first use per loop;
changing MISTRAL_API_KEY requires a process restart.
"""

import asyncio
import logging
from typing import Any

from mistralai.client.sdk import Mistral

from adelia.config import settings

logger = logging.getLogger(__name__)

_client: Mistral | None = None
_client_loop: asyncio.AbstractEventLoop | None = None

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
    try:
        loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _client is None or _client_loop is not loop:
        _client = Mistral(api_key=settings.mistral_api_key)
        _client_loop = loop
    return _client
