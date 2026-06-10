"""Pure unit tests for briefing_html_renderer. No DB, no LLM, no API."""
from __future__ import annotations

from datetime import datetime, UTC
from uuid import uuid4


from adelia.schemas import (
    AppliedFilter,
    BriefingPayload,
    BriefingSections,
    Citation,
    LLMMeta,
    MedicationItem,
    PatientHeader,
    QAItem,
    Specialty,
)
from adelia.services.briefing_html_renderer import render_briefing_html


def _payload(allergies="no_known_allergies", immunizations=None, qa: list[QAItem] | None = None) -> BriefingPayload:
    return BriefingPayload(
        schema_version="1.0",
        generated_at=datetime(2026, 5, 13, 10, 0, 0, tzinfo=UTC),
        target_specialty=Specialty.ENDOCRINOLOGY,
        patient=PatientHeader(name="J. Doe", age=42, sex="F"),
        sections=BriefingSections(
            reason_for_consult="control diabetes",
            active_problems=[],
            medications=[
                MedicationItem(
                    name="metformin",
                    dose="500mg",
                    frequency="BID",
                    citations=[
                        Citation(
                            document_id=uuid4(),
                            entity_id=uuid4(),
                            raw_quote="metformin 500mg BID",
                        )
                    ],
                    provenance="extracted_from_clinician_doc",
                )
            ],
            allergies=allergies,
            immunizations=immunizations,
            procedures=[],
            family_history=None,
            relevant_observations=[],
            open_questions=qa or [],
        ),
        applied_filter=AppliedFilter(specialty="endocrinology", rules_version="1.0"),
        llm_meta=LLMMeta(model="mistral-medium-latest", tokens_used=1500, cost_estimate_usd=0.008),
    )


def test_renders_basic_briefing_html():
    html = render_briefing_html(_payload())
    assert "<html" in html.lower() or "<!doctype" in html.lower()
    assert "J. Doe" in html
    assert "endocrinology" in html.lower()
    assert "metformin" in html


def test_no_known_allergies_string_renders():
    html = render_briefing_html(_payload(allergies="no_known_allergies"))
    assert "No known allergies" in html


def test_hidden_immunizations_section_not_rendered():
    html = render_briefing_html(_payload(immunizations=None))
    assert "Immunizations" not in html


def test_qa_items_rendered_with_citations():
    qa = [
        QAItem(
            question="Latest HbA1c?",
            answer="6.2% on 2025-12-10.",
            citations=[
                Citation(
                    document_id=uuid4(),
                    entity_id=uuid4(),
                    raw_quote="HbA1c 6.2%",
                )
            ],
        )
    ]
    html = render_briefing_html(_payload(qa=qa))
    assert "Latest HbA1c?" in html
    assert "6.2%" in html
    assert "data-citation-id" in html


def test_nh3_strips_script_from_narrative():
    qa = [
        QAItem(
            question="X?",
            answer='<script>alert("xss")</script>Safe answer',
            citations=[
                Citation(
                    document_id=uuid4(),
                    entity_id=uuid4(),
                    raw_quote="quote",
                )
            ],
        )
    ]
    html = render_briefing_html(_payload(qa=qa))
    assert "<script>" not in html
    assert "alert" not in html
    assert "Safe answer" in html


def test_disclaimer_footer_present():
    html = render_briefing_html(_payload())
    assert "AI" in html or "disclaimer" in html.lower()
