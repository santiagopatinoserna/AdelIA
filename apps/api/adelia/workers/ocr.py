import base64

import httpx

from adelia.config import settings


MISTRAL_OCR_URL = "https://api.mistral.ai/v1/ocr"


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

    Raises:
        RuntimeError: if MISTRAL_API_KEY is not configured. Configuration
            error — do NOT retry; alert.
        httpx.HTTPStatusError: if the Mistral API returns a non-2xx
            response. May be transient (5xx, rate limits) — caller should
            consider retry with backoff or mark document with error state.
    """
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
        "model": "mistral-ocr-latest",
        "document": document,
        "include_image_base64": False,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(MISTRAL_OCR_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    pages = data.get("pages", [])
    return "\n\n".join(page.get("markdown", "") for page in pages)
