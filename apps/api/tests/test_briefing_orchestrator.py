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
