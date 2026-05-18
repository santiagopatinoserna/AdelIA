"""Tests for qa_pre_baker. Follows M2 TDD leaf worker pattern:
- 1 live test gated on MISTRAL_API_KEY
- 1 RuntimeError test that monkeypatches client → always runs (CI sans secrets)
- 1 anti-hallucination filter test using stub client (always runs)
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from adelia.config import settings
from adelia.schemas import Specialty
from adelia.services.qa_pre_baker import (
    QAPrebakerError,
    bake_questions,
)


def _entities_text() -> str:
    """Sample patient context block (entities + raw_quotes)."""
    return (
        "doc_1 [allergy] penicillin — quote: 'patient allergic to penicillin since 2018'\n"
        "doc_1 [observation] HbA1c=6.2% on 2025-12-10 — quote: 'HbA1c 6.2% on 2025-12-10'\n"
        "doc_2 [medication] metformin 500mg BID — quote: 'metformin 500mg twice daily'\n"
    )


@pytest.mark.skipif(
    not settings.mistral_api_key,
    reason="MISTRAL_API_KEY not set — live test skipped",
)
def test_bake_questions_live_returns_qa_items():
    source_texts = {
        "doc_1": "patient allergic to penicillin since 2018. HbA1c 6.2% on 2025-12-10.",
        "doc_2": "metformin 500mg twice daily",
    }
    items, meta = bake_questions(
        specialty=Specialty.ENDOCRINOLOGY,
        entities_text=_entities_text(),
        specialty_hints="Endocrinologist focus: HbA1c, diabetes meds, family history.",
        source_raw_texts=source_texts,
    )
    assert 0 <= len(items) <= 5
    doc_text = " ".join(source_texts.values())
    for item in items:
        assert item.question
        assert item.answer
        assert len(item.citations) >= 1
        for cit in item.citations:
            assert cit.raw_quote
            assert cit.raw_quote in doc_text
    assert meta.tokens_used > 0


def test_bake_questions_raises_on_client_error(monkeypatch):
    from adelia.services import qa_pre_baker as module

    class BoomClient:
        def __init__(self, *args, **kwargs):
            pass

        @property
        def chat(self):
            raise RuntimeError("api error")

    monkeypatch.setattr(module, "_build_client", lambda: BoomClient())

    with pytest.raises(QAPrebakerError):
        bake_questions(
            specialty=Specialty.DEFAULT,
            entities_text="x",
            specialty_hints="x",
            source_raw_texts={"doc_1": "x"},
        )


def test_anti_hallucination_filter_drops_quotes_not_in_source(monkeypatch):
    """Quotes not present verbatim in any source doc are silently dropped."""
    from adelia.services import qa_pre_baker as module

    fake_response = {
        "items": [
            {
                "question": "Q1",
                "answer": "A1",
                "citations": [
                    {
                        "document_id": str(uuid4()),
                        "entity_id": None,
                        "raw_quote": "this quote DOES NOT exist in any source",
                    }
                ],
            },
            {
                "question": "Q2",
                "answer": "A2",
                "citations": [
                    {
                        "document_id": str(uuid4()),
                        "entity_id": None,
                        "raw_quote": "metformin 500mg twice daily",
                    }
                ],
            },
        ]
    }

    def _fake_llm_call(*args, **kwargs):
        return fake_response, 100

    monkeypatch.setattr(module, "_llm_structured_call", _fake_llm_call)
    monkeypatch.setattr(module, "_build_client", lambda: object())

    items, meta = bake_questions(
        specialty=Specialty.DEFAULT,
        entities_text="...",
        specialty_hints="...",
        source_raw_texts={"doc_2": "metformin 500mg twice daily"},
    )
    assert len(items) == 1
    assert items[0].question == "Q2"
