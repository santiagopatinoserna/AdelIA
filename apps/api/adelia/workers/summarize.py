"""Post-consultation essence: a few strict bullets from the transcript.

Same REST pattern as ocr.py (httpx, no SDK surface) on Mistral; with
settings.llm_provider="anthropic" it goes through the Anthropic SDK instead,
same prompt. The prompt is deliberately narrow: only what was actually said,
no advice, no invention, answer in the transcript's own language. A missing/failed summary must
never block the pipeline — the transcript is the product, the summary is
a courtesy.
"""
from __future__ import annotations

import re

import httpx

from adelia.config import settings
from adelia.llm import anthropic_text, get_anthropic_client, uses_anthropic
from adelia.services import usage

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

# A recording the recorder recovered after a reload or a closed tab, or one the browser
# stopped by itself (a call took the mic, iOS paused it), ends wherever it was cut. Third
# QA wave 2026-11-13: one cut inside "treinta y ocho" was summarised as
# "se preguntó si se puede dar paracetamol si la fiebre sube de 30, y no hubo respuesta",
# a wrong number and an invented silence, with nothing saying the visit was cut. Voxtral
# punctuates the fragment as a whole question, so code cannot tell a cut sentence from a
# finished one: the last sentence is left out of what the model reads (the transcript
# keeps it, followed by CUT_MARK), the model is told why, and the summary ends with one
# coded line in her locale. The line says only what is sure: the recording was cut, so the
# end may be missing. "Antes de terminar la consulta" was false when the browser cut it
# after the visit had ended (review of the third fix round).
_CUT_NOTE = (
    " La grabación se cortó sin que la parasen, quizá antes de terminar la consulta, y su "
    "última frase, que pudo "
    "quedar a medias, no está en el texto. No completes lo que falta ni digas que algo "
    "quedó sin respuesta: la respuesta pudo llegar después del corte."
)
CUT_LINE = {
    "es": "La grabación se cortó: puede faltar el final de la consulta.",
    "en": "The recording was cut off: the end of the visit may be missing.",
    "fr": "L’enregistrement a été coupé : la fin de la consultation peut manquer.",
}
CUT_MARK = {
    "es": "(La grabación se cortó aquí.)",
    "en": "(The recording stopped here.)",
    "fr": "(L’enregistrement s’est arrêté ici.)",
}

_SPEAKER = re.compile(r"\[Hablante \d+\]\s*")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def _lang(locale: str | None) -> str:
    code = (locale or "es")[:2].lower()
    return code if code in CUT_LINE else "es"


def drop_cut_sentence(transcript: str) -> str:
    """The transcript without its last sentence, the one a cut may have left half said.

    Works on the last "[Hablante N]" block, so the speaker label stays with what is
    left; a block that had only that sentence goes as a whole. "38,3" and "38.3" are
    not sentence ends (no space after the mark)."""
    head, sep, last = transcript.rstrip().rpartition("\n\n")
    label_match = _SPEAKER.match(last)
    label = label_match.group(0) if label_match else ""
    sentences = _SENTENCE_END.split(last[len(label):].strip())
    kept = " ".join(sentences[:-1]).strip()
    if not kept:
        return head.rstrip()
    return f"{head}{sep}{label}{kept}"


def mark_cut(transcript: str, locale: str | None) -> str:
    """The stored transcript, with the place the recording stopped said out loud: "Ver
    la transcripción" and the chat about this visit read it right after the fragment.
    Appended to the last speaker block, so the transcript view keeps its blocks."""
    return f"{transcript.rstrip()} {CUT_MARK[_lang(locale)]}"


def _with_cut_line(summary: str, locale: str | None) -> str:
    line = f"- {CUT_LINE[_lang(locale)]}"
    return f"{summary.rstrip()}\n{line}" if summary.strip() else line


async def summarize_consultation(
    transcript: str, *, interrupted: bool = False, locale: str | None = None
) -> str:
    """Summarize a diarized consultation transcript into a few bullets.

    `interrupted`: the recorder uploaded a recording a reload or a closed tab cut
    (third QA wave 2026-11-13). The last sentence is not summarised, and the summary
    ends with CUT_LINE in `locale`, her page locale.

    Raises:
        RuntimeError: the provider's API key not set, or (AnthropicRefusal)
            Claude declined. Do NOT retry.
        httpx.HTTPStatusError / anthropic.APIError: error from the API. May be
            transient, caller retries with backoff (_with_retry covers both).
    """
    if not interrupted:
        return await _summarize(transcript, _SYSTEM)
    kept = drop_cut_sentence(transcript)
    if not kept.strip():
        # One sentence and then the cut: nothing that was surely said whole.
        return _with_cut_line("", locale)
    return _with_cut_line(await _summarize(kept, _SYSTEM + _CUT_NOTE), locale)


async def _summarize(transcript: str, system: str) -> str:
    if uses_anthropic():
        return await _summarize_anthropic(transcript, system)
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
                    {"role": "system", "content": system},
                    {"role": "user", "content": transcript[:12000]},
                ],
            },
        )
        resp.raise_for_status()
    payload = resp.json()
    usage.count(
        "summarize", "mistral", settings.mistral_chat_model, **usage.openai_style_tokens(payload)
    )
    choices = payload.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message", {}).get("content") or "").strip()


async def _summarize_anthropic(transcript: str, system: str = _SYSTEM) -> str:
    """Effort "low": a few bullets copied out of the transcript need no
    deliberation. max_tokens is well above the 400 the Mistral call caps at
    because the model may think first and that counts against the same limit;
    the prompt, not the cap, is what keeps the summary short."""
    client = get_anthropic_client()
    resp = await client.messages.create(
        model=settings.anthropic_chat_model,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": transcript[:12000]}],
        output_config={"effort": "low"},
    )
    usage.count(
        "summarize", "anthropic", settings.anthropic_chat_model, **usage.anthropic_tokens(resp)
    )
    return anthropic_text(resp).strip()
