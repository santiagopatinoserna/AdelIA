from pathlib import Path

import pytest

from adelia.config import settings
from adelia.workers.ocr import extract_text_from_pdf


FIXTURE = Path(__file__).parent / "fixtures" / "sample-lab-result.pdf"


@pytest.mark.skipif(not settings.mistral_api_key, reason="needs Mistral API key")
async def test_ocr_extracts_text():
    with open(FIXTURE, "rb") as f:
        body = f.read()

    text = await extract_text_from_pdf(body, mime_type="application/pdf")

    assert "Glucose" in text or "glucose" in text.lower()
    assert "95" in text
