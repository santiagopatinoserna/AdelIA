from pathlib import Path

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
    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY not set"):
        await transcribe_audio(b"", mime_type="audio/wav")
