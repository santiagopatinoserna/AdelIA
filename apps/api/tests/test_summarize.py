"""Post-consultation summary worker + read path."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest

from adelia.config import settings
from adelia.models import Document
from adelia.routers.documents import _doc_to_out
from adelia.workers import summarize as summarize_mod
from adelia.workers.summarize import drop_cut_sentence, mark_cut, summarize_consultation
from tests.pg_gate import PG_AVAILABLE


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


# ---------------------------------------------------------------------------
# A recording the recorder recovered after a reload or a closed tab (third QA wave
# 2026-11-13): a cut inside "treinta y ocho" was summarised as "si la fiebre sube de 30,
# y no hubo respuesta", with nothing saying the visit had been cut.
# ---------------------------------------------------------------------------

_CUT = (
    "[Hablante 1] El peso está muy bien, en el percentil 60.\n\n"
    "[Hablante 2] Vale. La fiebre es normal después de la vacuna. "
    "¿Y le puedo dar paracetamol esta noche si sube de 30?"
)


def test_drop_cut_sentence_leaves_out_only_the_last_sentence():
    assert drop_cut_sentence(_CUT) == (
        "[Hablante 1] El peso está muy bien, en el percentil 60.\n\n"
        "[Hablante 2] Vale. La fiebre es normal después de la vacuna."
    )


def test_drop_cut_sentence_drops_a_block_that_was_only_the_fragment():
    text = "[Hablante 1] Tiene 38,3 de fiebre.\n\n[Hablante 2] Pues dale tres coma"
    assert drop_cut_sentence(text) == "[Hablante 1] Tiene 38,3 de fiebre."


def test_drop_cut_sentence_keeps_decimals_and_handles_flat_text():
    # "38,3" and "38.3" are numbers, not sentence ends; a flat transcript works too.
    assert drop_cut_sentence("Tiene 38.3 de fiebre. Dale 2.5 ml de") == "Tiene 38.3 de fiebre."
    assert drop_cut_sentence("Solo una frase cortada") == ""


async def test_an_interrupted_consult_leaves_the_fragment_out_and_says_it_was_cut(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    captured: dict = {}
    payload = {"choices": [{"message": {"content": "- El peso está en el percentil 60."}}]}
    _patch_chat_post(monkeypatch, payload, captured)

    result = await summarize_consultation(_CUT, interrupted=True, locale="es")

    sent = captured["json"]["messages"]
    # The model never reads the half-said sentence, so it cannot turn it into a fact.
    assert "sube de 30" not in sent[1]["content"]
    assert "percentil 60" in sent[1]["content"]
    # It is told why the end is missing and not to invent an unanswered question.
    assert "se cortó" in sent[0]["content"]
    assert "sin respuesta" in sent[0]["content"]
    # One coded line in her locale, last.
    assert result.splitlines() == [
        "- El peso está en el percentil 60.",
        "- La grabación se cortó: puede faltar el final de la consulta.",
    ]


@pytest.mark.parametrize(
    ("locale", "line"),
    [
        ("en", "- The recording was cut off: the end of the visit may be missing."),
        ("fr", "- L’enregistrement a été coupé : la fin de la consultation peut manquer."),
        ("de", "- La grabación se cortó: puede faltar el final de la consulta."),
        (None, "- La grabación se cortó: puede faltar el final de la consulta."),
    ],
)
async def test_the_cut_line_follows_her_locale(monkeypatch, locale, line):
    monkeypatch.setattr(settings, "llm_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    _patch_chat_post(monkeypatch, {"choices": [{"message": {"content": "- Bien."}}]}, {})

    result = await summarize_consultation(_CUT, interrupted=True, locale=locale)

    assert result.splitlines()[-1] == line


async def test_a_consult_cut_after_one_sentence_calls_no_model(monkeypatch):
    """Nothing in it was surely said whole: the summary is the cut line alone."""
    async def _boom(self, url, **kwargs):
        raise AssertionError("no model call for a one-sentence cut recording")

    monkeypatch.setattr(settings, "llm_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    monkeypatch.setattr(httpx.AsyncClient, "post", _boom)

    result = await summarize_consultation(
        "[Hablante 1] Buenos días, ¿qué le pasa a", interrupted=True, locale="es"
    )

    assert result == "- La grabación se cortó: puede faltar el final de la consulta."


async def test_a_whole_consult_keeps_its_prompt_and_gets_no_cut_line(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mistral")
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    captured: dict = {}
    _patch_chat_post(monkeypatch, {"choices": [{"message": {"content": "- Bien."}}]}, captured)

    result = await summarize_consultation(_CUT)

    assert result == "- Bien."
    assert captured["json"]["messages"][0]["content"] == summarize_mod._SYSTEM
    assert "sube de 30" in captured["json"]["messages"][1]["content"]


def test_mark_cut_ends_the_last_speaker_block():
    marked = mark_cut(_CUT, "es")
    assert marked.endswith("si sube de 30? (La grabación se cortó aquí.)")
    # Still inside the last block: the transcript view splits on "[Hablante N]".
    assert marked.count("[Hablante") == 2


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required: the upload writes a Document row")
async def test_an_interrupted_upload_is_summarised_as_cut(client, monkeypatch):
    """End to end through POST /documents and the pipeline: the recorder's flag is
    kept on the row, the summarizer is told, and the stored transcript says where the
    recording stopped."""
    from adelia.db import AsyncSessionLocal
    from adelia.routers import documents as docs_mod
    from tests.db_helpers import make_user
    from tests.test_auth import make_token

    monkeypatch.setattr(settings, "auth_secret", "test-secret")

    async def _put(key, body, content_type=None):
        return None

    async def _noop_process(document_id, mime_type, is_consulta=False):
        return None

    class _Body:
        def read(self) -> bytes:
            return b"fake-consulta-audio"

    async def _get(key: str):
        return _Body()

    async def _transcribe(body, mime_type, diarize=False):
        return _CUT

    asked: list[dict] = []

    async def _summarize(text, **kw):
        asked.append({"text": text, **kw})
        return "- El peso está en el percentil 60.\n- La grabación se cortó antes de terminar."

    async def _extract(text: str):
        return []

    async def _embed(texts: list[str]):
        return [[0.0] * 1024 for _ in texts]

    monkeypatch.setattr(docs_mod.storage, "put_object", _put)
    monkeypatch.setattr(docs_mod, "process_document", _noop_process)
    monkeypatch.setattr(docs_mod.storage, "get_object", _get)
    monkeypatch.setattr(docs_mod, "transcribe_audio", _transcribe)
    monkeypatch.setattr(docs_mod, "summarize_consultation", _summarize)
    monkeypatch.setattr(docs_mod, "extract_entities", _extract)
    monkeypatch.setattr(docs_mod, "embed_texts", _embed)

    user_id = await make_user()
    headers = {"Authorization": f"Bearer {make_token(str(user_id))}"}
    ids = []
    for flag in ("true", None):
        data = {"source": "consulta", "consent_policy_version": "2026-08-17", "locale": "fr"}
        if flag:
            data["interrupted"] = flag
        resp = await client.post(
            "/documents",
            headers=headers,
            files={"file": ("consulta.webm", b"fake-audio", "audio/webm;codecs=opus")},
            data=data,
        )
        assert resp.status_code == 201, resp.text
        ids.append(uuid.UUID(resp.json()["id"]))
        # Runs the pipeline now, which also sets processed_at: no row is left for the
        # next boot to requeue.
        await docs_mod._process_document_inner(ids[-1], "audio/webm", True)

    assert asked[0] == {"text": _CUT, "interrupted": True, "locale": "fr"}
    # A recording that ended normally is summarised exactly as before.
    assert asked[1] == {"text": _CUT}
    async with AsyncSessionLocal() as session:
        cut = await session.get(Document, ids[0])
        whole = await session.get(Document, ids[1])
    assert cut.document_metadata["interrupted"] is True
    assert cut.raw_text.endswith("(L’enregistrement s’est arrêté ici.)")
    assert cut.document_metadata["summary"].startswith("- El peso")
    assert cut.processed_at is not None
    assert "interrupted" not in (whole.document_metadata or {})
    assert whole.raw_text == _CUT
