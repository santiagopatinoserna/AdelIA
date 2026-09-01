"""briefing_orchestrator: mocked pipeline tests, plus the header (audit 3.10)."""

from __future__ import annotations

from datetime import date as _date
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from adelia.schemas import LLMMeta, QAItem, Specialty


@pytest.mark.asyncio
async def test_orchestrator_happy_path_transitions_to_ready():
    """Full success path: entities loaded → sections formatted → QA baked → HTML rendered → persisted."""
    from adelia.services import briefing_orchestrator
    from adelia.schemas import PatientHeader

    user_id = uuid4()
    briefing_id = uuid4()

    with patch.object(
        briefing_orchestrator, "_load_user_entities_and_sources", new_callable=AsyncMock
    ) as load, patch.object(
        briefing_orchestrator, "_load_user_patient_header", new_callable=AsyncMock
    ) as patient_load, patch(
        "adelia.services.briefing_orchestrator.bake_questions", new_callable=AsyncMock
    ) as bake, patch.object(
        briefing_orchestrator, "_persist_briefing_status", new_callable=AsyncMock
    ) as persist:
        load.return_value = ([], {})
        patient_load.return_value = PatientHeader(name="J. Doe", age_months=18, sex="F")
        bake.return_value = ([], LLMMeta(model="m", tokens_used=10, cost_estimate_usd=0.001))

        await briefing_orchestrator.run(
            briefing_id=briefing_id,
            user_id=user_id,
            target_specialty=Specialty.DEFAULT,
        )

        persist.assert_called_once()
        kwargs = persist.call_args.kwargs
        assert kwargs["status"] == "ready"
        assert kwargs["error_message"] is None


@pytest.mark.asyncio
async def test_orchestrator_failure_transitions_to_failed_with_message():
    """If bake_questions raises, status='failed' + error_message set."""
    from adelia.services import briefing_orchestrator
    from adelia.services.qa_pre_baker import QAPrebakerError
    from adelia.schemas import PatientHeader

    user_id = uuid4()
    briefing_id = uuid4()

    with patch.object(
        briefing_orchestrator, "_load_user_entities_and_sources", new_callable=AsyncMock
    ) as load, patch.object(
        briefing_orchestrator, "_load_user_patient_header", new_callable=AsyncMock
    ) as patient_load, patch(
        "adelia.services.briefing_orchestrator.bake_questions", new_callable=AsyncMock
    ) as bake, patch.object(
        briefing_orchestrator, "_persist_briefing_status", new_callable=AsyncMock
    ) as persist:
        load.return_value = ([], {})
        patient_load.return_value = PatientHeader(name="J. Doe", age_months=18, sex="F")
        bake.side_effect = QAPrebakerError("simulated LLM failure")

        await briefing_orchestrator.run(
            briefing_id=briefing_id,
            user_id=user_id,
            target_specialty=Specialty.DEFAULT,
        )

        kwargs = persist.call_args.kwargs
        assert kwargs["status"] == "failed"
        assert "simulated LLM failure" in (kwargs["error_message"] or "")


@pytest.mark.asyncio
async def test_orchestrator_payload_includes_qa_items():
    """End-to-end: orchestrator wires QA items into briefing payload."""
    from adelia.services import briefing_orchestrator
    from adelia.schemas import Citation, PatientHeader

    user_id = uuid4()
    briefing_id = uuid4()
    doc_id = uuid4()

    qa_items = [
        QAItem(
            question="Q1",
            answer="A1",
            citations=[Citation(document_id=doc_id, entity_id=None, raw_quote="q")],
        )
    ]

    with patch.object(
        briefing_orchestrator, "_load_user_entities_and_sources", new_callable=AsyncMock
    ) as load, patch.object(
        briefing_orchestrator, "_load_user_patient_header", new_callable=AsyncMock
    ) as patient_load, patch(
        "adelia.services.briefing_orchestrator.bake_questions", new_callable=AsyncMock
    ) as bake, patch.object(
        briefing_orchestrator, "_persist_briefing_status", new_callable=AsyncMock
    ) as persist:
        load.return_value = ([], {str(doc_id): "q"})
        patient_load.return_value = PatientHeader(name="J. Doe", age_months=18, sex="F")
        bake.return_value = (qa_items, LLMMeta(model="m", tokens_used=5, cost_estimate_usd=0.0))

        await briefing_orchestrator.run(
            briefing_id=briefing_id,
            user_id=user_id,
            target_specialty=Specialty.DEFAULT,
        )

        kwargs = persist.call_args.kwargs
        payload = kwargs["payload"]
        assert payload is not None
        assert len(payload.sections.open_questions) == 1
        assert payload.sections.open_questions[0].question == "Q1"


# --- The briefing's evidence cut-off (audit follow-up, 2026-08-31) ----------
#
# _retrieve_specialty_evidence passed a hand-written `max_distance=0.55`,
# "slightly more lenient for briefings". 0.55 sits above the corpus's own
# diameter (0.3386 over 33.153 pairs), so on that path the cut-off could not
# reject anything: the 5-stage pipeline always attached the nearest fragments
# as specialty evidence, there is no refusal branch like the chat's, and the
# result is the one artifact a parent prints and hands to a specialist, also
# published without auth at /s/{token} and /s/{token}/pdf.


@pytest.mark.asyncio
async def test_briefing_evidence_uses_the_calibrated_cutoff():
    from adelia.config import settings
    from adelia.services import briefing_orchestrator

    with patch.object(
        briefing_orchestrator, "embed_texts", new_callable=AsyncMock
    ) as embed, patch.object(
        briefing_orchestrator, "retrieve_evidence", new_callable=AsyncMock
    ) as retrieve, patch.object(
        briefing_orchestrator, "AsyncSessionLocal"
    ):
        embed.return_value = [[0.1] * 1024]
        retrieve.return_value = []

        await briefing_orchestrator._retrieve_specialty_evidence(
            target_specialty=Specialty.DEFAULT, entities_text="Hb 10.5"
        )

    kwargs = retrieve.call_args.kwargs
    assert kwargs["max_distance"] == settings.evidence_max_distance
    assert settings.evidence_max_distance < 0.3386, (
        "a briefing cut-off above the corpus diameter cannot reject anything"
    )


@pytest.mark.asyncio
async def test_briefing_evidence_never_leaves_the_pediatric_corpus():
    """It used to filter by the TARGET specialty tag. Now that the array bind
    works (it used to raise DataError and this whole function returned "" and
    []), that tag would let the adult sources in: a gastroenterology briefing
    would match "Colorectal cancer screening — USPSTF 2021", a cardiology one
    "Atrial fibrillation — ESC 2024". The specialty steers the embedded query;
    the tag filter keeps the search inside the pediatric corpus."""
    from adelia.services import briefing_orchestrator

    with patch.object(
        briefing_orchestrator, "embed_texts", new_callable=AsyncMock
    ) as embed, patch.object(
        briefing_orchestrator, "retrieve_evidence", new_callable=AsyncMock
    ) as retrieve, patch.object(
        briefing_orchestrator, "AsyncSessionLocal"
    ):
        embed.return_value = [[0.1] * 1024]
        retrieve.return_value = []

        await briefing_orchestrator._retrieve_specialty_evidence(
            target_specialty=Specialty.GASTROENTEROLOGY, entities_text="reflujo"
        )

    assert retrieve.call_args.kwargs["specialties"] == ["pediatrics"]


# ---------------------------------------------------------------------------
# The header comes from Profile (audit 3.10)
#
# Every briefing used to say the patient was 0 years old, of unknown sex, and
# named after the local part of the mother's email, from an "M5 placeholder"
# comment. In pediatrics the age is the first determinant of every
# interpretation: "0 años" on an 18-month-old invalidates percentiles, doses
# and the vaccination schedule, and costs the document its credibility in
# front of the professional reading it.
# ---------------------------------------------------------------------------



async def test_header_reads_name_age_and_sex_from_the_profile():
    """The facts are now resolved once by run() and handed in, so the header
    and the entities it describes are the same child (audit 4.1); the header
    itself no longer opens a session when the profile has a name."""
    from uuid import uuid4

    from adelia.enrichment.profile_service import ProfileFacts
    from adelia.services import briefing_orchestrator

    facts = ProfileFacts(profile_id=uuid4(), display_name="Adel",
                         date_of_birth=_date(2025, 3, 1), sex="M", age_months=18)
    header = await briefing_orchestrator._load_user_patient_header(uuid4(), facts)

    assert header.name == "Adel"
    assert header.age_months == 18
    assert header.sex == "M"
    assert header.age_label == "18 meses"


async def test_header_says_the_age_is_not_recorded_instead_of_printing_zero():
    from uuid import uuid4

    from adelia.enrichment.profile_service import ProfileFacts
    from adelia.services import briefing_orchestrator

    facts = ProfileFacts(profile_id=uuid4(), display_name="Adel",
                         date_of_birth=None, sex=None, age_months=None)
    header = await briefing_orchestrator._load_user_patient_header(uuid4(), facts)

    assert header.age_months is None
    assert header.age_label == "edad no registrada"
    assert "0" not in header.age_label


def test_age_label_uses_months_under_two_years_and_years_above():
    from adelia.schemas import PatientHeader

    assert PatientHeader(name="x", age_months=1).age_label == "1 mes"
    assert PatientHeader(name="x", age_months=18).age_label == "18 meses"
    assert PatientHeader(name="x", age_months=23).age_label == "23 meses"
    assert PatientHeader(name="x", age_months=24).age_label == "2 años"
    assert PatientHeader(name="x", age_months=12 * 42).age_label == "42 años"


def test_the_rendered_header_never_prints_a_zero_age():
    from datetime import datetime, UTC

    from adelia.schemas import (
        AppliedFilter, BriefingPayload, BriefingSections, LLMMeta, PatientHeader, Specialty,
    )
    from adelia.services.briefing_html_renderer import render_briefing_html

    sections = BriefingSections(
        reason_for_consult=None, active_problems=[], medications=[], allergies=[],
        immunizations=[], procedures=[], family_history=[], relevant_observations=[],
        open_questions=[],
    )
    for locale, needle in (("es", "edad no registrada"),
                           ("en", "age not recorded"),
                           ("fr", "âge non renseigné")):
        payload = BriefingPayload(
            schema_version="1.0",
            patient=PatientHeader(name="Adel", age_months=None, sex=None),
            target_specialty=Specialty.PEDIATRICS,
            generated_at=datetime.now(UTC),
            sections=sections,
            citations=[],
            applied_filter=AppliedFilter(specialty="pediatrics", rules_version="1"),
            llm_meta=LLMMeta(model="test", tokens_used=0, cost_estimate_usd=0.0),
            locale=locale,
        )
        html = render_briefing_html(payload)
        assert needle in html, locale
        assert "0 años" not in html and "0 years" not in html
