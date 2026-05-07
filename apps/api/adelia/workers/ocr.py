import base64

import httpx

from adelia.config import settings


MISTRAL_OCR_URL = "https://api.mistral.ai/v1/ocr"


async def extract_text_from_pdf(body: bytes, mime_type: str) -> str:
    """Send the file to Mistral OCR API and return concatenated text from all pages."""
    if not settings.mistral_api_key:
        raise RuntimeError("MISTRAL_API_KEY not set")

    encoded = base64.b64encode(body).decode("ascii")
    headers = {
        "Authorization": f"Bearer {settings.mistral_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "mistral-ocr-latest",
        "document": {
            "type": "document_base64",
            "document_base64": encoded,
            "document_name": f"upload.{_ext_from_mime(mime_type)}",
        },
        "include_image_base64": False,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(MISTRAL_OCR_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    pages = data.get("pages", [])
    return "\n\n".join(page.get("markdown", "") for page in pages)


def _ext_from_mime(mime_type: str) -> str:
    return {
        "application/pdf": "pdf",
        "image/png": "png",
        "image/jpeg": "jpg",
    }.get(mime_type, "bin")
