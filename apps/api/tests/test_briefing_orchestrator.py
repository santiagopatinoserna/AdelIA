"""briefing_orchestrator — 3 mocked tests using AsyncMock pattern from M3."""
from __future__ import annotations

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
        "adelia.services.briefing_orchestrator.bake_questions"
    ) as bake, patch.object(
        briefing_orchestrator, "_persist_briefing_status", new_callable=AsyncMock
    ) as persist:
        load.return_value = ([], {})
        patient_load.return_value = PatientHeader(name="J. Doe", age=42, sex="F")
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
        "adelia.services.briefing_orchestrator.bake_questions"
    ) as bake, patch.object(
        briefing_orchestrator, "_persist_briefing_status", new_callable=AsyncMock
    ) as persist:
        load.return_value = ([], {})
        patient_load.return_value = PatientHeader(name="J. Doe", age=42, sex="F")
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
        "adelia.services.briefing_orchestrator.bake_questions"
    ) as bake, patch.object(
        briefing_orchestrator, "_persist_briefing_status", new_callable=AsyncMock
    ) as persist:
        load.return_value = ([], {str(doc_id): "q"})
        patient_load.return_value = PatientHeader(name="J. Doe", age=42, sex="F")
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
