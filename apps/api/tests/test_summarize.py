"""Post-consultation summary worker + read path."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest

from adelia.config import settings
from adelia.models import Document
from adelia.routers.documents import _doc_to_out
from adelia.workers.summarize import summarize_consultation


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


def _patch_chat_post(monkeypatch, payload: dict, captured: dict):
    async def fake_post(self, url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _FakeResponse(payload)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


async def test_summarize_returns_bullets(monkeypatch):
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    captured: dict = {}
    payload = {
        "choices": [
            {"message": {"content": "- Peso en percentil 60.\n- Paracetamol 2 ml cada 8 horas."}}
        ]
    }
    _patch_chat_post(monkeypatch, payload, captured)

    result = await summarize_consultation("[Hablante 1] El peso está bien...")

    assert result.startswith("- Peso")
    assert captured["json"]["model"] == settings.mistral_chat_model
    assert captured["json"]["temperature"] == 0.2
    # The transcript rides as the user message, capped.
    assert captured["json"]["messages"][1]["role"] == "user"


async def test_summarize_raises_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "mistral_api_key", "")
    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
        await summarize_consultation("texto")


async def test_summarize_empty_choices_returns_empty(monkeypatch):
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    _patch_chat_post(monkeypatch, {"choices": []}, {})
    assert await summarize_consultation("texto") == ""


def test_document_out_surfaces_summary():
    doc = Document(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        source="consulta",
        mime_type="audio/webm",
        s3_key=f"users/x/{uuid.uuid4()}-c.webm",
        raw_text="[Hablante 1] Hola.",
        document_metadata={"summary": "- Todo bien.", "audio_deleted_scheduled": True},
        # server_default only fires in the DB; an in-memory Document needs it.
        created_at=datetime.now(timezone.utc),
    )
    out = _doc_to_out(doc)
    assert out.summary == "- Todo bien."
    assert out.speaker_names is None
