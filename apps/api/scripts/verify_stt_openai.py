"""Manual smoke test for the OpenAI STT provider — no API server, no DB.

Transcribes one local audio file directly through
`adelia.workers.transcribe.transcribe_audio` with STT_PROVIDER forced to
"openai", using whatever OPENAI_API_KEY / openai_stt_model /
openai_stt_base_url are already configured (see config.py — base_url
defaults to the eu.api.openai.com residency endpoint).

Built so Santiago can validate in ~10 seconds the moment the OpenAI account
has credits again: insufficient_quota today raises a clear RuntimeError
instead of hanging through 3 retries.

Usage:
  uv run python scripts/verify_stt_openai.py path/to/audio.wav
  uv run python scripts/verify_stt_openai.py tests/fixtures/sample-audio.wav
"""

import asyncio
import mimetypes
import sys
from pathlib import Path

from adelia.config import settings
from adelia.workers.transcribe import transcribe_audio


async def main(path: str) -> int:
    audio_path = Path(path)
    if not audio_path.is_file():
        print(f"✗ fichero no encontrado: {audio_path}")
        return 1
    if not settings.openai_api_key:
        print("✗ OPENAI_API_KEY no está configurada")
        return 1

    settings.stt_provider = "openai"
    mime_type = mimetypes.guess_type(audio_path.name)[0] or "audio/wav"

    print(f"▶ proveedor: openai · modelo: {settings.openai_stt_model}")
    print(f"▶ endpoint:  {settings.openai_stt_base_url}")
    print(f"▶ fichero:   {audio_path} ({mime_type})")

    body = audio_path.read_bytes()
    try:
        text = await transcribe_audio(body, mime_type=mime_type, diarize=False)
    except RuntimeError as exc:
        print(f"✗ error no reintentable: {exc}")
        return 1

    print("\n── transcripción ──────────────────────────────────────────")
    print(text or "(vacía)")
    print("───────────────────────────────────────────────────────────")
    print("OK")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: uv run python scripts/verify_stt_openai.py <fichero.wav>")
        sys.exit(1)
    sys.exit(asyncio.run(main(sys.argv[1])))
