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

from mistralai.client.sdk import Mistral

from adelia.config import settings

_client: Mistral | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


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
