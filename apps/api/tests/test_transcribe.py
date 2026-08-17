from pathlib import Path

import httpx
import pytest

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
    payload = {
        "text": "ignored when segments have speakers",
        "segments": [
            {"speaker": "speaker_0", "text": "El peso está en el percentil 60."},
            {"speaker": "speaker_0", "text": "Todo normal."},
            {"speaker": "speaker_1", "text": "¿Y la vacuna de los 12 meses?"},
            {"speaker": "speaker_0", "text": "Se la ponemos hoy."},
        ],
    }
    _patch_mistral_post(monkeypatch, payload, captured)

    result = await transcribe_audio(b"fake-audio", "audio/webm", diarize=True)

    assert captured["data"]["diarize"] == "true"
    assert result == (
        "[Hablante 1] El peso está en el percentil 60. Todo normal.\n\n"
        "[Hablante 2] ¿Y la vacuna de los 12 meses?\n\n"
        "[Hablante 1] Se la ponemos hoy."
    )


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


@pytest.mark.skipif(not settings.mistral_api_key, reason="MISTRAL_API_KEY not set")
async def test_voxtral_live_transcription(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "mistral")
    body = FIXTURE.read_bytes()
    result = await transcribe_audio(body, "audio/wav")
    assert isinstance(result, str)
