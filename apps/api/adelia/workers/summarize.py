"""Post-consultation essence: a few strict bullets from the transcript.

Same REST pattern as ocr.py (httpx, no SDK surface) on Mistral; with
settings.llm_provider="anthropic" it goes through the Anthropic SDK instead,
same prompt. The prompt is deliberately narrow: only what was actually said,
no advice, no invention, answer in the transcript's own language. A missing/failed summary must
never block the pipeline — the transcript is the product, the summary is
a courtesy.
"""
from __future__ import annotations

import httpx

from adelia.config import settings
from adelia.llm import anthropic_text, get_anthropic_client, uses_anthropic

MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"

_SYSTEM = (
    "Eres un asistente que resume consultas pediátricas para la madre o el "
    "padre. Devuelve SOLO de 3 a 6 frases cortas con viñetas '- ', cada una "
    "un hecho dicho en la conversación: qué valoró el profesional, qué "
    "indicó (medicación con dosis exacta si se dijo, cuidados, señales de "
    "alarma) y qué quedó pendiente. Prohibido inventar, aconsejar por tu "
    "cuenta o añadir nada que no esté en el texto. Responde en el MISMO "
    "idioma de la transcripción. Sin encabezados, sin guiones largos."
)


async def summarize_consultation(transcript: str) -> str:
    """Summarize a diarized consultation transcript into a few bullets.

    Raises:
        RuntimeError: the provider's API key not set, or (AnthropicRefusal)
            Claude declined. Do NOT retry.
        httpx.HTTPStatusError / anthropic.APIError: error from the API. May be
            transient, caller retries with backoff (_with_retry covers both).
    """
    if uses_anthropic():
        return await _summarize_anthropic(transcript)
    if not settings.mistral_api_key:
        raise RuntimeError("MISTRAL_API_KEY not set")

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            MISTRAL_CHAT_URL,
            headers={"Authorization": f"Bearer {settings.mistral_api_key}"},
            json={
                "model": settings.mistral_chat_model,
                "temperature": 0.2,
                "max_tokens": 400,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": transcript[:12000]},
                ],
            },
        )
        resp.raise_for_status()
    payload = resp.json()
    choices = payload.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message", {}).get("content") or "").strip()


async def _summarize_anthropic(transcript: str) -> str:
    """Effort "low": a few bullets copied out of the transcript need no
    deliberation. max_tokens is well above the 400 the Mistral call caps at
    because the model may think first and that counts against the same limit;
    the prompt, not the cap, is what keeps the summary short."""
    client = get_anthropic_client()
    resp = await client.messages.create(
        model=settings.anthropic_chat_model,
        max_tokens=4000,
        system=_SYSTEM,
        messages=[{"role": "user", "content": transcript[:12000]}],
        output_config={"effort": "low"},
    )
    return anthropic_text(resp).strip()
