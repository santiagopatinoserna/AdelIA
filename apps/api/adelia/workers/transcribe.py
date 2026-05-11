import io

from openai import AsyncOpenAI

from adelia.config import settings


def _ext_from_mime(mime_type: str) -> str:
    return {
        "audio/wav": "wav",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/mp4": "m4a",
        "audio/x-m4a": "m4a",
        "audio/ogg": "ogg",
        "audio/webm": "webm",
        "audio/flac": "flac",
    }.get(mime_type, "wav")


async def transcribe_audio(body: bytes, mime_type: str) -> str:
    """Transcribe audio via OpenAI Whisper API.

    Args:
        body: raw audio bytes.
        mime_type: one of audio/wav, audio/mpeg, audio/mp4, audio/ogg, audio/webm, audio/flac.

    Returns:
        Transcribed text. Empty string if Whisper returns empty (e.g., silent audio).

    Raises:
        RuntimeError: if OPENAI_API_KEY is not configured. Configuration error —
            do NOT retry; alert.
        openai.APIError: if the OpenAI API returns an error. May be transient
            (rate limits, 5xx) — caller should consider retry with backoff.
    """
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    ext = _ext_from_mime(mime_type)
    file_tuple = (f"upload.{ext}", io.BytesIO(body), mime_type)

    response = await client.audio.transcriptions.create(
        model="whisper-1",
        file=file_tuple,
        response_format="text",
    )
    return response if isinstance(response, str) else str(response)
