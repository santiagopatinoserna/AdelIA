"""The public demo may use a different generation provider than the product.

Why: the chat and briefings read real medical records, and the privacy notice and
the DPIA name Mistral (EU) as the processor for them. The public demo reads one
invented baby plus whatever a visitor types, so moving only the demo to another
provider does not change what the notice promises about real data. A global
`llm_provider` flip would. These tests pin that the override reaches the demo
and nothing else.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from adelia.config import Settings, settings
from adelia.services import chat_orchestrator as orch


def test_the_shipped_demo_provider_is_unset():
    """Unset means "follow llm_provider": shipping this change moves nothing."""
    assert Settings.model_fields["demo_llm_provider"].default == ""


async def _collect(provider):
    pieces = []
    async for piece in orch._stream_llm_tokens("system", "user", provider=provider):
        pieces.append(piece)
    return "".join(pieces)


async def test_an_explicit_provider_wins_over_the_global_setting(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mistral")

    async def openai_stream(messages):
        yield "from-openai"

    async def mistral_stream(messages):
        yield "from-mistral"

    with patch.object(orch, "_stream_openai_tokens", openai_stream), patch.object(
        orch, "_stream_mistral_tokens", mistral_stream
    ):
        assert await _collect("openai") == "from-openai"


async def test_without_a_provider_the_global_setting_decides(monkeypatch):
    """The chat and the briefings never pass a provider: they must keep reading
    llm_provider exactly as before."""
    monkeypatch.setattr(settings, "llm_provider", "mistral")

    async def openai_stream(messages):
        yield "from-openai"

    async def mistral_stream(messages):
        yield "from-mistral"

    with patch.object(orch, "_stream_openai_tokens", openai_stream), patch.object(
        orch, "_stream_mistral_tokens", mistral_stream
    ):
        assert await _collect(None) == "from-mistral"
        monkeypatch.setattr(settings, "llm_provider", "openai")
        assert await _collect(None) == "from-openai"


async def test_generate_answer_forwards_the_provider(monkeypatch):
    seen = {}

    async def fake_stream(system_prompt, user_message, history=None, *, provider=None):
        seen["provider"] = provider
        yield "ok"

    monkeypatch.setattr(orch, "_stream_llm_tokens", fake_stream)
    assert await orch.generate_answer("s", "u", provider="openai") == "ok"
    assert seen["provider"] == "openai"
    assert await orch.generate_answer("s", "u") == "ok"
    assert seen["provider"] is None


@pytest.mark.parametrize("configured, expected", [("openai", "openai"), ("", None)])
async def test_the_demo_router_passes_its_own_setting(client, monkeypatch, configured, expected):
    """Only /demo/ask reads demo_llm_provider. An empty value must reach
    generate_answer as None (follow llm_provider), not as an empty string."""
    import uuid

    from adelia.enrichment.evidence_retrieval import EvidenceMatch
    from tests.pg_gate import PG_AVAILABLE

    if not PG_AVAILABLE:
        pytest.skip("needs Postgres for the demo budget counter")

    monkeypatch.setattr(settings, "demo_llm_provider", configured)
    match = EvidenceMatch(
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        source_title="Guideline",
        organization="NICE",
        publication_year=2019,
        url="https://example.org/g",
        content="Regurgitation is common in infants.",
        chunk_index=0,
        distance=0.07,
    )
    captured = {}

    async def _retrieve(session, **kwargs):
        return [match]

    async def _generate(system_prompt, user_message, **kwargs):
        captured.update(kwargs)
        return "Respuesta [ev_1]."

    with patch("adelia.routers.demo.embed_texts", return_value=[[0.0] * 1024]), patch(
        "adelia.routers.demo.retrieve_evidence", _retrieve
    ), patch("adelia.routers.demo.generate_answer", _generate):
        resp = await client.post(
            "/demo/ask", json={"question": "¿Es normal que regurgite?", "locale": "es"}
        )

    assert resp.status_code == 200, resp.text
    assert captured.get("provider") == expected
