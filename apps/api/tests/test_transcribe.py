from pathlib import Path

import httpx
import openai
import pytest
from openai.resources.audio.transcriptions import AsyncTranscriptions

from adelia.config import settings
from adelia.workers.transcribe import transcribe_audio


FIXTURE = Path(__file__).parent / "fixtures" / "sample-audio.wav"


@pytest.mark.skipif(not settings.openai_api_key, reason="needs OpenAI API key")
async def test_transcribe_returns_string():
    with open(FIXTURE, "rb") as f:
        body = f.read()
    text = await transcribe_audio(body, mime_type="audio/wav")
    assert isinstance(text, str)
    # 440Hz tone has no speech, so transcript may be empty or short noise.
    # Just verify the call completed without raising.


async def test_transcribe_raises_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY not set"):
        await transcribe_audio(b"", mime_type="audio/wav")


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


def _patch_mistral_post(monkeypatch, payload: dict, captured: dict):
    async def fake_post(self, url, **kwargs):
        captured["url"] = url
        captured["data"] = kwargs.get("data")
        captured["files"] = kwargs.get("files")
        return _FakeResponse(payload)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


async def test_mistral_plain_transcription(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    captured: dict = {}
    _patch_mistral_post(monkeypatch, {"text": "hola bebé"}, captured)

    result = await transcribe_audio(b"fake-audio", "audio/webm")

    assert result == "hola bebé"
    assert captured["data"]["model"] == settings.mistral_stt_model
    assert "diarize" not in captured["data"]


async def test_mistral_diarized_formats_speakers(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    captured: dict = {}
    # Shape verified against the live API (2026-08-18): segments carry
    # "speaker_id" (not "speaker") and diarize requires segment timestamps.
    payload = {
        "text": "ignored when segments have speakers",
        "segments": [
            {"type": "transcription_segment", "speaker_id": "speaker_1", "start": 0.0, "end": 2.5, "text": "El peso está en el percentil 60."},
            {"type": "transcription_segment", "speaker_id": "speaker_1", "start": 2.9, "end": 5.0, "text": "Todo normal."},
            {"type": "transcription_segment", "speaker_id": "speaker_2", "start": 5.8, "end": 8.9, "text": "¿Y la vacuna de los 12 meses?"},
            {"type": "transcription_segment", "speaker_id": "speaker_1", "start": 9.9, "end": 12.6, "text": "Se la ponemos hoy."},
        ],
    }
    _patch_mistral_post(monkeypatch, payload, captured)

    result = await transcribe_audio(b"fake-audio", "audio/webm", diarize=True)

    assert captured["data"]["diarize"] == "true"
    assert captured["data"]["timestamp_granularities"] == ["segment"]
    assert result == (
        "[Hablante 1] El peso está en el percentil 60. Todo normal.\n\n"
        "[Hablante 2] ¿Y la vacuna de los 12 meses?\n\n"
        "[Hablante 1] Se la ponemos hoy."
    )


async def test_mistral_diarized_accepts_legacy_speaker_key(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    payload = {
        "text": "ignored",
        "segments": [
            {"speaker": "a", "text": "Hola."},
            {"speaker": "b", "text": "Buenas."},
        ],
    }
    _patch_mistral_post(monkeypatch, payload, {})

    result = await transcribe_audio(b"fake-audio", "audio/webm", diarize=True)

    assert result == "[Hablante 1] Hola.\n\n[Hablante 2] Buenas."


async def test_mistral_diarize_without_speakers_falls_back_to_text(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    payload = {"text": "texto plano", "segments": [{"text": "texto plano"}]}
    _patch_mistral_post(monkeypatch, payload, {})

    result = await transcribe_audio(b"fake-audio", "audio/webm", diarize=True)

    assert result == "texto plano"


async def test_mistral_raises_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "")

    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
        await transcribe_audio(b"fake-audio", "audio/webm")


async def test_openai_provider_still_selected(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await transcribe_audio(b"fake-audio", "audio/wav")


def _openai_status_error(
    cls,
    *,
    status_code: int,
    code: str | None = None,
    type_: str | None = None,
    message: str = "boom",
):
    """Build a real openai.*Error with a fake httpx.Response, like the SDK does.

    `code` and `type` are separate on purpose: the live API sets them to
    DIFFERENT values (a quota error is type="insufficient_quota" with
    code="credit_balance_exhausted"), and collapsing them into one hid a
    contract bug once already.
    """
    request = httpx.Request("POST", "https://eu.api.openai.com/v1/audio/transcriptions")
    response = httpx.Response(status_code, request=request)
    body = {"code": code, "type": type_, "message": message, "param": None}
    return cls(message, response=response, body=body)


def _patch_openai_create(monkeypatch, *, result=None, exc: Exception | None = None):
    captured: dict = {}

    async def fake_create(self, *, model, file, response_format, **kwargs):
        captured["model"] = model
        captured["base_url"] = str(self._client.base_url)
        if exc is not None:
            raise exc
        return result

    monkeypatch.setattr(AsyncTranscriptions, "create", fake_create)
    return captured


async def test_openai_uses_configured_model_and_base_url(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_stt_model", "whisper-1")
    monkeypatch.setattr(settings, "openai_stt_base_url", "https://eu.api.openai.com/v1")
    captured = _patch_openai_create(monkeypatch, result="hola bebé")

    result = await transcribe_audio(b"fake-audio", "audio/wav")

    assert result == "hola bebé"
    assert captured["model"] == "whisper-1"
    assert captured["base_url"] == "https://eu.api.openai.com/v1/"


async def test_openai_diarize_true_returns_plain_text(monkeypatch):
    """OpenAI doesn't support diarization: diarize=True is silently ignored,
    so the caller gets a flat transcript, not [Hablante N] labels or an error."""
    monkeypatch.setattr(settings, "stt_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    _patch_openai_create(monkeypatch, result="texto plano sin diarizar")

    result = await transcribe_audio(b"fake-audio", "audio/wav", diarize=True)

    assert result == "texto plano sin diarizar"
    assert "[Hablante" not in result


async def test_openai_insufficient_quota_raises_runtime_error(monkeypatch):
    """429 insufficient_quota is a config error (no credits), not a transient
    rate limit: it must become a RuntimeError so _with_retry does NOT retry it."""
    monkeypatch.setattr(settings, "stt_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    # Exact body captured from the live API on 2026-08-19: note that `code`
    # is NOT "insufficient_quota", it is "credit_balance_exhausted".
    exc = _openai_status_error(
        openai.RateLimitError,
        status_code=429,
        type_="insufficient_quota",
        code="credit_balance_exhausted",
        message="You have no credits remaining. Add credits to continue using the API.",
    )
    _patch_openai_create(monkeypatch, exc=exc)

    with pytest.raises(RuntimeError, match="sin créditos"):
        await transcribe_audio(b"fake-audio", "audio/wav")


async def test_openai_authentication_error_raises_runtime_error(monkeypatch):
    """401 is always a config error (bad/missing key): RuntimeError, no retry."""
    monkeypatch.setattr(settings, "stt_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "bad-key")
    exc = _openai_status_error(
        openai.AuthenticationError, status_code=401, code="invalid_api_key"
    )
    _patch_openai_create(monkeypatch, exc=exc)

    with pytest.raises(RuntimeError, match="credenciales"):
        await transcribe_audio(b"fake-audio", "audio/wav")


async def test_openai_non_eu_project_gets_actionable_error(monkeypatch):
    """The EU endpoint 401s for projects without data residency, with a body
    whose code/type are both null. Captured live on 2026-08-19: the operator
    must be told to enable EU residency, not to check the API key."""
    monkeypatch.setattr(settings, "stt_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "valid-key")
    exc = _openai_status_error(
        openai.AuthenticationError,
        status_code=401,
        message=(
            "This endpoint is only accessible by projects with geography "
            "restrictions enabled."
        ),
    )
    _patch_openai_create(monkeypatch, exc=exc)

    with pytest.raises(RuntimeError, match="residencia de datos europea"):
        await transcribe_audio(b"fake-audio", "audio/wav")


async def test_openai_transient_rate_limit_still_propagates_as_sdk_error(monkeypatch):
    """A real (non-quota) 429 must stay an openai.RateLimitError so _with_retry's
    existing OpenAIAPIError handler keeps retrying it with backoff."""
    monkeypatch.setattr(settings, "stt_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    exc = _openai_status_error(
        openai.RateLimitError, status_code=429, type_="requests", code="rate_limit_exceeded"
    )
    _patch_openai_create(monkeypatch, exc=exc)

    with pytest.raises(openai.RateLimitError):
        await transcribe_audio(b"fake-audio", "audio/wav")


@pytest.mark.skipif(not settings.mistral_api_key, reason="MISTRAL_API_KEY not set")
async def test_voxtral_live_transcription(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "mistral")
    body = FIXTURE.read_bytes()
    result = await transcribe_audio(body, "audio/wav")
    assert isinstance(result, str)
