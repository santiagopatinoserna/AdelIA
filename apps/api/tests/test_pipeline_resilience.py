"""Pipeline resilience: bounded retry + filename derivation."""
from unittest.mock import AsyncMock

import httpx
import pytest

from adelia.routers import documents as docs_mod
from adelia.routers.documents import _file_name_from_key, _with_retry


def _http_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.mistral.ai/v1/ocr")
    response = httpx.Response(429, request=request)
    return httpx.HTTPStatusError("rate limited", request=request, response=response)


async def test_with_retry_recovers_after_transient_failures(monkeypatch):
    monkeypatch.setattr(docs_mod, "RETRY_DELAYS", (0.0, 0.0))
    call = AsyncMock(side_effect=[_http_error(), _http_error(), "texto"])
    result = await _with_retry("ocr", call)
    assert result == "texto"
    assert call.await_count == 3


async def test_with_retry_exhausts_and_raises(monkeypatch):
    monkeypatch.setattr(docs_mod, "RETRY_DELAYS", (0.0,))
    call = AsyncMock(side_effect=_http_error())
    with pytest.raises(httpx.HTTPStatusError):
        await _with_retry("ocr", call)
    assert call.await_count == 2  # 1 + 1 retry


async def test_with_retry_does_not_retry_config_errors(monkeypatch):
    monkeypatch.setattr(docs_mod, "RETRY_DELAYS", (0.0, 0.0))
    call = AsyncMock(side_effect=RuntimeError("MISTRAL_API_KEY not set"))
    with pytest.raises(RuntimeError):
        await _with_retry("ocr", call)
    assert call.await_count == 1


def test_file_name_strips_uuid_prefix():
    key = "users/u1/123e4567-e89b-42d3-a456-426614174000-informe_lab.pdf"
    assert _file_name_from_key(key) == "informe_lab.pdf"


def test_file_name_passthrough_for_legacy_keys():
    assert _file_name_from_key("users/u1/plain.pdf") == "plain.pdf"
