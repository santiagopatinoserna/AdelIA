"""Validation tests for Briefing Pydantic schemas."""
from datetime import datetime, UTC
from uuid import uuid4

import pytest
from pydantic import ValidationError

from adelia.schemas import (
    AppliedFilter,
    BriefingCreate,
    BriefingPayload,
    BriefingSections,
    BriefingStatus,
    Citation,
    LLMMeta,
    PatientHeader,
    QAItem,
    Specialty,
)


def test_specialty_enum_has_8_specialties_plus_default():
    assert {s.value for s in Specialty} == {
        "pediatrics",
        "endocrinology",
        "cardiology",
        "gynecology",
        "gastroenterology",
        "dermatology",
        "general_medicine",
        "default",
    }


def test_briefing_status_enum():
    assert {s.value for s in BriefingStatus} == {"processing", "ready", "failed"}


def test_citation_requires_min_quote_length():
    with pytest.raises(ValidationError):
        Citation(document_id=uuid4(), entity_id=None, raw_quote="")


def test_qa_item_accepts_multiple_citations():
    qa = QAItem(
        question="What is the latest HbA1c?",
        answer="6.2% measured 2025-12-10.",
        citations=[
            Citation(document_id=uuid4(), entity_id=uuid4(), raw_quote="HbA1c 6.2%"),
            Citation(document_id=uuid4(), entity_id=uuid4(), raw_quote="2025-12-10"),
        ],
    )
    assert len(qa.citations) == 2


def test_briefing_payload_minimal_valid():
    payload = BriefingPayload(
        schema_version="1.0",
        generated_at=datetime.now(UTC),
        target_specialty=Specialty.ENDOCRINOLOGY,
        patient=PatientHeader(name="J. Doe", age_months=18, sex="F"),
        sections=BriefingSections(
            reason_for_consult=None,
            active_problems=[],
            medications=[],
            allergies="no_known_allergies",
            immunizations=None,
            procedures=[],
            family_history=None,
            relevant_observations=[],
            open_questions=[],
        ),
        applied_filter=AppliedFilter(specialty="endocrinology", rules_version="1.0"),
        llm_meta=LLMMeta(model="mistral-medium-latest", tokens_used=0, cost_estimate_usd=0.0),
    )
    assert payload.schema_version == "1.0"
    assert payload.sections.allergies == "no_known_allergies"


def test_citation_rejects_overlength_quote():
    with pytest.raises(ValidationError):
        Citation(document_id=uuid4(), raw_quote="x" * 2001)


def test_specialty_rejects_unknown_value():
    with pytest.raises(ValidationError):
        BriefingCreate(target_specialty="neurology")
