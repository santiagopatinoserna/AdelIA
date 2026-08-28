"""Boot-time corpus embedding must survive Mistral 429s (seen in prod on
2026-08-28: a 146-chunk file was lost entirely on the first rate limit)."""
import pytest
from mistralai.client.errors import MistralError

from adelia.enrichment import evidence_loader as loader


class _RateLimited(MistralError):
    def __init__(self):
        # MistralError.__str__ returns .message; mirror the SDK's attributes.
        self.message = "API error occurred: Status 429. Body: rate_limited"
        Exception.__init__(self, self.message)
        self.status_code = 429


class _Fatal(MistralError):
    def __init__(self):
        self.message = "API error occurred: Status 401. Body: unauthorized"
        Exception.__init__(self, self.message)
        self.status_code = 401


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(loader, "EMBED_RETRY_DELAYS", (0.0, 0.0))

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(loader.asyncio, "sleep", _no_sleep)


async def test_retries_on_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def _embed(texts):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _RateLimited()
        return [[0.0] * 1024 for _ in texts]

    monkeypatch.setattr(loader, "embed_texts", _embed)
    out = await loader.embed_with_retry(["a", "b"])
    assert len(out) == 2 and calls["n"] == 3


async def test_gives_up_after_retries(monkeypatch):
    async def _embed(texts):
        raise _RateLimited()

    monkeypatch.setattr(loader, "embed_texts", _embed)
    with pytest.raises(MistralError):
        await loader.embed_with_retry(["a"])


async def test_non_retryable_propagates_immediately(monkeypatch):
    calls = {"n": 0}

    async def _embed(texts):
        calls["n"] += 1
        raise _Fatal()

    monkeypatch.setattr(loader, "embed_texts", _embed)
    with pytest.raises(MistralError):
        await loader.embed_with_retry(["a"])
    assert calls["n"] == 1
