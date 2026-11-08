import base64
import logging

import httpx

from adelia.config import settings
from adelia.llm import anthropic_text, get_anthropic_client, uses_anthropic
from adelia.services import usage

logger = logging.getLogger(__name__)

MISTRAL_OCR_URL = "https://api.mistral.ai/v1/ocr"

# Claude has no OCR endpoint: it reads the PDF or the image and is asked to copy
# the text out. The wording matters more than for any other prompt here, because
# this text is the ground truth of the record: extraction keeps an entity only if
# its quote appears in it verbatim, and the chunks the chat cites are cut from it.
# Anything the model "fixes", translates or summarises here becomes a fact that
# the document never said.
_ANTHROPIC_OCR_PROMPT = (
    "Transcribe all the text in this document exactly as it is written, in its "
    "original language, as Markdown. Keep tables as Markdown tables and keep every "
    "number, unit, date, name and reference range as printed. Do not summarise, "
    "translate, correct, interpret or complete anything, and add nothing that is not "
    "in the document: no headings of your own, no comments, no preamble. If the "
    "document has no readable text, answer exactly {no_text}."
)
_NO_TEXT = "NO_TEXT"


async def extract_text_from_pdf(body: bytes, mime_type: str) -> str:
    """Send the file to Mistral OCR API and return concatenated markdown text.

    Args:
        body: raw bytes of the file (PDF/PNG/JPEG).
        mime_type: one of 'application/pdf', 'image/png', 'image/jpeg'.
            Other non-image values are sent as document_url, which Mistral
            will likely reject — caller should validate before calling.

    Returns:
        Concatenated markdown from all pages, separated by '\\n\\n'.
        Empty string if the API returns no pages or empty markdown.

    With settings.llm_provider="anthropic" Claude reads the file instead
    (_ocr_anthropic); same contract, plus anthropic.APIError as the transient
    error and AnthropicRefusal (a RuntimeError) when the model declines.

    Raises:
        RuntimeError: if MISTRAL_API_KEY is not configured. Configuration
            error — do NOT retry; alert.
        httpx.HTTPStatusError: if the Mistral API returns a non-2xx
            response. May be transient (5xx, rate limits) — caller should
            consider retry with backoff or mark document with error state.
    """
    if uses_anthropic():
        return await _ocr_anthropic(body, mime_type)
    if not settings.mistral_api_key:
        raise RuntimeError("MISTRAL_API_KEY not set")

    encoded = base64.b64encode(body).decode("ascii")
    headers = {
        "Authorization": f"Bearer {settings.mistral_api_key}",
        "Content-Type": "application/json",
    }
    # Mistral OCR only accepts URL chunk types; raw bytes go inline as a data URI.
    data_uri = f"data:{mime_type};base64,{encoded}"
    if mime_type.startswith("image/"):
        document = {"type": "image_url", "image_url": data_uri}
    else:
        document = {"type": "document_url", "document_url": data_uri}
    payload = {
        "model": settings.mistral_ocr_model,
        "document": document,
        "include_image_base64": False,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(MISTRAL_OCR_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    pages = data.get("pages", [])
    pages_processed = (data.get("usage_info") or {}).get("pages_processed")
    usage.count(
        "ocr", "mistral", settings.mistral_ocr_model,
        pages=pages_processed if pages_processed is not None else len(pages),
    )
    return "\n\n".join(page.get("markdown", "") for page in pages)


async def _ocr_anthropic(body: bytes, mime_type: str) -> str:
    """The file's text, transcribed by Claude. "" when it has none.

    A PDF goes as a `document` block and an image as an `image` block, both
    base64. Limits are Claude's, not Mistral's: an image over 10 MB once
    base64-encoded (about 7.5 MB of JPEG) or a PDF over Claude's PDF limits
    (32 MB, 600 pages) is answered with a 400, which fails the document like any
    other OCR error. Oversized image dimensions are downscaled by the API.

    Streaming with a large max_tokens because a long PDF is a long answer and a
    non-streaming call that size would hit the HTTP timeout. Effort "low":
    copying text needs no deliberation. A transcript cut by max_tokens is kept
    but logged, so a thinner record has a reason in the logs.
    """
    if mime_type.startswith("image/"):
        source_block = {"type": "image"}
    else:
        source_block = {"type": "document"}
    source_block["source"] = {
        "type": "base64",
        "media_type": mime_type,
        "data": base64.b64encode(body).decode("ascii"),
    }
    client = get_anthropic_client()
    async with client.messages.stream(
        model=settings.anthropic_ocr_model,
        max_tokens=128000,
        messages=[
            {
                "role": "user",
                "content": [
                    source_block,
                    {"type": "text", "text": _ANTHROPIC_OCR_PROMPT.format(no_text=_NO_TEXT)},
                ],
            }
        ],
        output_config={"effort": "low"},
    ) as stream:
        final = await stream.get_final_message()
    usage.count("ocr", "anthropic", settings.anthropic_ocr_model, **usage.anthropic_tokens(final))
    text = anthropic_text(final).strip()
    if final.stop_reason == "max_tokens":
        logger.warning("ocr: Claude transcript cut at max_tokens (%d chars kept)", len(text))
    return "" if text == _NO_TEXT else text
