import io

import httpx
from openai import AsyncOpenAI

from adelia.config import settings

MISTRAL_TRANSCRIBE_URL = "https://api.mistral.ai/v1/audio/transcriptions"


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


def _format_diarized(segments: list[dict]) -> str:
    """Group consecutive same-speaker segments into '[Hablante N] …' blocks.

    Speaker labels from the API are opaque (e.g. 'speaker_0'); we map them to
    1, 2, … in order of first appearance. Diarization can't know WHO the
    doctor is — neutral labels, renaming is a v1.1 feature.
    """
    label_of: dict[object, int] = {}
    blocks: list[tuple[int, list[str]]] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        raw = seg.get("speaker")
        if raw not in label_of:
            label_of[raw] = len(label_of) + 1
        label = label_of[raw]
        if blocks and blocks[-1][0] == label:
            blocks[-1][1].append(text)
        else:
            blocks.append((label, [text]))
    return "\n\n".join(f"[Hablante {n}] {' '.join(parts)}" for n, parts in blocks)


async def _transcribe_mistral(body: bytes, mime_type: str, *, diarize: bool) -> str:
    """Mistral Voxtral via La Plateforme REST (same httpx pattern as ocr.py).

    Raises:
        RuntimeError: MISTRAL_API_KEY not set. Config error — do NOT retry.
        httpx.HTTPStatusError: non-2xx from the API. May be transient —
            caller retries with backoff (_with_retry covers httpx.HTTPError).
    """
    if not settings.mistral_api_key:
        raise RuntimeError("MISTRAL_API_KEY not set")

    bare_mime = mime_type.split(";")[0].strip()
    ext = _ext_from_mime(bare_mime)
    data: dict[str, str] = {"model": settings.mistral_stt_model}
    if diarize:
        data["diarize"] = "true"
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            MISTRAL_TRANSCRIBE_URL,
            headers={"Authorization": f"Bearer {settings.mistral_api_key}"},
            data=data,
            files={"file": (f"upload.{ext}", body, bare_mime)},
        )
        resp.raise_for_status()
    payload = resp.json()
    segments = payload.get("segments") or []
    if diarize and any(s.get("speaker") is not None for s in segments):
        return _format_diarized(segments)
    return payload.get("text") or ""


async def _transcribe_openai(body: bytes, mime_type: str) -> str:
    """OpenAI Whisper fallback (no diarization). Unchanged v0.1 behavior."""
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


async def transcribe_audio(body: bytes, mime_type: str, *, diarize: bool = False) -> str:
    """Transcribe audio via the configured STT provider.

    Args:
        body: raw audio bytes.
        mime_type: audio/* mime (";codecs=" suffix tolerated).
        diarize: label speakers ([Hablante N]) — Mistral only; ignored by
            the OpenAI provider.

    Returns:
        Transcript text. Empty string on silent audio.
    """
    if settings.stt_provider == "mistral":
        return await _transcribe_mistral(body, mime_type, diarize=diarize)
    return await _transcribe_openai(body, mime_type)
