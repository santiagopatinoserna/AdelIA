"""End-to-end extraction proof over the synthetic clinical corpus.

For each case: render a realistic PDF the system has never seen → run the
REAL pipeline (Mistral OCR → entity extraction) → assert the clinically
critical ground-truth findings were recovered. This is the "real technology
inside" demonstration: no mocks, no canned answers.

Gated on MISTRAL_API_KEY (live OCR + LLM). Run:
    MISTRAL_API_KEY=... uv run pytest tests/test_clinical_extraction.py -v
"""

from __future__ import annotations

import pytest

from adelia.config import settings
from adelia.workers.extract import extract_entities
from adelia.workers.ocr import extract_text_from_pdf
from tests.clinical_corpus.cases import CASES
from tests.clinical_corpus.match import missing_findings
from tests.clinical_corpus.render import case_to_pdf_bytes


@pytest.mark.skipif(not settings.mistral_api_key, reason="needs Mistral API key (live OCR + LLM)")
@pytest.mark.parametrize("case", CASES, ids=[c.slug for c in CASES])
async def test_pipeline_recovers_ground_truth(case):
    pdf = case_to_pdf_bytes(case)

    # Stage 1: OCR the rendered PDF (round-trips through Mistral, like a real upload).
    raw_text = await extract_text_from_pdf(pdf, mime_type="application/pdf")
    assert raw_text.strip(), f"{case.slug}: OCR returned empty text"

    # Stage 2: entity extraction over the OCR'd text.
    entities = await extract_entities(raw_text)
    assert entities, f"{case.slug}: no entities extracted"

    missing = missing_findings(case.must_find, entities)
    if missing:
        found = sorted({f"{e.entity_type}:{e.name}" for e in entities})
        detail = "\n".join(f"  - MISSED {m.entity_type} {m.name_contains} ({m.why})" for m in missing)
        pytest.fail(
            f"{case.slug}: {len(missing)}/{len(case.must_find)} ground-truth findings missed:\n"
            f"{detail}\nExtracted: {found}"
        )


def test_corpus_is_well_formed():
    """Cheap guard (no API): every case has body + at least one finding,
    and the anti-hallucination invariant is satisfiable (ground-truth tokens
    actually appear in the document)."""
    assert CASES, "corpus is empty"
    for case in CASES:
        assert case.body.strip(), f"{case.slug}: empty body"
        assert case.must_find, f"{case.slug}: no ground-truth findings"
        body_lower = case.body.lower()
        for finding in case.must_find:
            assert any(tok.lower() in body_lower for tok in finding.name_contains), (
                f"{case.slug}: finding {finding.name_contains} has no token in the document — "
                "the ground truth would be unrecoverable"
            )
