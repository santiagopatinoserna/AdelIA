import io

import httpx
import openai
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


def _speaker_of(seg: dict) -> object | None:
    return seg.get("speaker_id") if seg.get("speaker_id") is not None else seg.get("speaker")


def _format_diarized(segments: list[dict]) -> str:
    """Group consecutive same-speaker segments into '[Hablante N] …' blocks.

    Speaker labels from the API are opaque (e.g. 'speaker_1'); we map them to
    1, 2, … in order of first appearance. Diarization can't know WHO the
    doctor is — neutral labels, renaming is a v1.1 feature.
    """
    label_of: dict[object, int] = {}
    blocks: list[tuple[int, list[str]]] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        raw = _speaker_of(seg)
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
    data: dict[str, str | list[str]] = {"model": settings.mistral_stt_model}
    if diarize:
        # Real-API contract (verified live 2026-08-18): diarize requires
        # segment-level timestamps or the API rejects with 422.
        data["diarize"] = "true"
        data["timestamp_granularities"] = ["segment"]
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
    # Real-API field is "speaker_id" ("speaker_1", …); keep "speaker" as a
    # defensive fallback in case the contract shifts back.
    if diarize and any(_speaker_of(s) is not None for s in segments):
        return _format_diarized(segments)
    return payload.get("text") or ""


async def _transcribe_openai(body: bytes, mime_type: str, *, diarize: bool = False) -> str:
    """OpenAI whisper-1 via settings.openai_stt_base_url (EU by default, see
    config.py). `diarize` is accepted for signature parity with
    `_transcribe_mistral` but deliberately IGNORED: whisper-1 has no speaker
    labels, so the transcript always comes back flat, without [Hablante N]
    blocks, even when the caller asked for diarization.

    Raises:
        RuntimeError: no API key, bad credentials or a non-EU project (401),
            or the account is out of credits (429 insufficient_quota). All
            are config errors that _with_retry must NOT retry (retrying
            burns time for nothing).
        openai.RateLimitError: a genuine transient 429 (real rate limiting)
            re-raised as-is, so _with_retry's existing OpenAIAPIError handler
            keeps retrying it with backoff.
    """
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_stt_base_url)
    ext = _ext_from_mime(mime_type)
    file_tuple = (f"upload.{ext}", io.BytesIO(body), mime_type)

    try:
        response = await client.audio.transcriptions.create(
            model=settings.openai_stt_model,
            file=file_tuple,
            response_format="text",
        )
    except openai.AuthenticationError as exc:
        # Live contract (2026-08-19): the EU endpoint answers 401 with
        # "only accessible by projects with geography restrictions enabled"
        # for projects that lack EU data residency, and that reads nothing
        # like a bad key. Tell the operator which of the two it is.
        if "geography restrictions" in str(exc):
            raise RuntimeError(
                "OpenAI: el endpoint UE exige un proyecto con residencia de "
                "datos europea activada. Actívala en platform.openai.com, o "
                "cambia STT_PROVIDER=mistral. Apuntar a api.openai.com "
                "enviaría el audio fuera de la UE y contradice el aviso de "
                "privacidad publicado."
            ) from exc
        raise RuntimeError(
            "OpenAI: credenciales inválidas (401). Revisa OPENAI_API_KEY."
        ) from exc
    except openai.RateLimitError as exc:
        # Live contract (2026-08-19): the real body is
        # type="insufficient_quota", code="credit_balance_exhausted".
        # Matching on code alone missed it and burned three retries.
        if exc.type == "insufficient_quota" or exc.code == "credit_balance_exhausted":
            raise RuntimeError(
                "OpenAI sin créditos: recarga en platform.openai.com "
                "o cambia STT_PROVIDER=mistral"
            ) from exc
        raise  # transient rate limit: let _with_retry retry it
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
    return await _transcribe_openai(body, mime_type, diarize=diarize)
