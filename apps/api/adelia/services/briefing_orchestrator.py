"""Briefing orchestrator — 5-stage pipeline coordinator.

Stages:
  1. Load entities + source raw_texts (scoped to user_id, deleted_at IS NULL)
  2. sbar_formatter → BriefingSections.sections (8 sections, filtered)
  3. qa_pre_baker → top-5 QA + citations (with anti-hallucination filter)
  4. Assemble BriefingPayload
  5. briefing_html_renderer → HTML string
  finally: update briefing row with status (ready/failed) + payload + html + completed_at
"""
from __future__ import annotations

import logging
from datetime import datetime, UTC
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.db import AsyncSessionLocal
from adelia.enrichment.evidence_retrieval import (
    evidence_citations_for_response,
    format_evidence_for_prompt,
    retrieve_evidence,
)
from adelia.models import Document, Entity, User
from adelia.schemas import (
    AppliedFilter,
    BriefingPayload,
    EvidenceCitation,
    PatientHeader,
    Specialty,
)
from adelia.services import briefing_repo
from adelia.services.briefing_html_renderer import render_briefing_html
from adelia.services.qa_pre_baker import bake_questions, QAPrebakerError
from adelia.services.sbar_formatter import EntityInput, format_sections
from adelia.specialty_templates import load_template
from adelia.workers.embed import embed_texts

logger = logging.getLogger(__name__)


async def _load_user_entities_and_sources(
    user_id: UUID,
) -> tuple[list[EntityInput], dict[str, str]]:
    """Load entities + source raw_texts for user, filtered by deleted_at IS NULL.

    Opens its own session so tests can mock this function without needing
    to mock AsyncSessionLocal too.
    """
    async with AsyncSessionLocal() as session:
        entity_stmt = (
            select(Entity)
            .where(Entity.user_id == user_id)
            .where(Entity.deleted_at.is_(None))
            .limit(500)
        )
        result = await session.execute(entity_stmt)
        rows = result.scalars().all()

        entities = [
            EntityInput(
                id=e.id,
                document_id=e.document_id,
                entity_type=e.entity_type,
                name=e.name or "",
                value=e.value or {},
                event_date=e.event_date.isoformat() if e.event_date else None,
                raw_quote=e.raw_quote or "",
                provenance=e.provenance or "extracted_from_clinician_doc",
            )
            for e in rows
            if e.raw_quote
        ]

        doc_ids = {e.document_id for e in entities}
        if doc_ids:
            doc_stmt = select(Document).where(Document.id.in_(doc_ids))
            doc_result = await session.execute(doc_stmt)
            sources = {str(d.id): (d.raw_text or "") for d in doc_result.scalars().all()}
        else:
            sources = {}

        return entities, sources


async def _load_user_patient_header(user_id: UUID) -> PatientHeader:
    """Build a minimal PatientHeader from the User row.

    M5 placeholder until UserSettings (age, sex, full_name) is wired. v0.1.1 enhancement.
    Opens its own session for testability.
    """
    async with AsyncSessionLocal() as session:
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            return PatientHeader(name="Unknown", age=0, sex="?")
        return PatientHeader(
            name=(user.email or "Unknown").split("@", 1)[0],
            age=0,
            sex="?",
        )


async def _persist_briefing_status(
    *,
    briefing_id: UUID,
    payload: BriefingPayload | None,
    html_render: str | None,
    status: str,
    error_message: str | None,
) -> None:
    """Wrap update_payload_html_status with a session — owns its transaction."""
    async with AsyncSessionLocal() as session:
        await briefing_repo.update_payload_html_status(
            session,
            briefing_id=briefing_id,
            payload=payload,
            html_render=html_render,
            status=status,
            error_message=error_message,
        )
        await session.commit()


def _entities_to_text_block(entities: list[EntityInput]) -> str:
    """Format entities as a text block for the qa_pre_baker prompt."""
    lines = []
    for e in entities:
        line = f"doc_{e.document_id} [{e.entity_type}] {e.name}"
        if e.event_date:
            line += f" ({e.event_date})"
        line += f" — quote: '{e.raw_quote}'"
        lines.append(line)
    return "\n".join(lines)


async def _retrieve_specialty_evidence(
    *,
    target_specialty: Specialty,
    entities_text: str,
    top_k: int = 5,
) -> tuple[str, list[EvidenceCitation]]:
    """Retrieve evidence relevant to the specialty.

    Embeds a synthetic query from specialty + recent entities, runs evidence
    retrieval filtered by specialty tag. Returns (formatted_prompt_block, citations).
    Gracefully degrades to empty on error.
    """
    try:
        query_text = f"{target_specialty.value} clinical guidelines for: {entities_text[:1500]}"
        embeds = await embed_texts([query_text])
        if not embeds:
            return "", []
        async with AsyncSessionLocal() as session:
            matches = await retrieve_evidence(
                session,
                query_embedding=embeds[0],
                specialties=[target_specialty.value],
                top_k=top_k,
                max_distance=0.55,  # slightly more lenient for briefings
            )
        prompt_block = format_evidence_for_prompt(matches)
        citation_dicts = evidence_citations_for_response(matches)
        citations = [EvidenceCitation(**c) for c in citation_dicts]
        return prompt_block, citations
    except Exception as e:
        logger.warning("specialty evidence retrieval failed (continuing): %s", e)
        return "", []


async def run(
    *,
    briefing_id: UUID,
    user_id: UUID,
    target_specialty: Specialty,
) -> None:
    """Execute the 5-stage pipeline for a single briefing_id.

    Idempotent semantics: always updates the briefing row (status to ready or failed
    + completed_at always set in finally).

    Dual-RAG: enriches Q&A pre-baker with specialty-relevant clinical evidence
    (ADA, AHA, NICE, etc. — depending on target_specialty). Evidence citations
    flow into BriefingPayload.evidence_citations for UI rendering.
    """
    status = "failed"
    error_message: str | None = None
    payload: BriefingPayload | None = None
    html: str | None = None

    try:
        entities, sources = await _load_user_entities_and_sources(user_id)
        patient = await _load_user_patient_header(user_id)

        sections = format_sections(
            entities=entities,
            specialty=target_specialty,
            reason_for_consult=None,
        )

        template = load_template(target_specialty)
        entities_text = _entities_to_text_block(entities)

        # Dual-RAG: pull specialty-relevant clinical evidence
        evidence_block, evidence_citations = await _retrieve_specialty_evidence(
            target_specialty=target_specialty,
            entities_text=entities_text,
        )

        # Append evidence to specialty_hints (non-breaking, qa_pre_baker prompt grows)
        enriched_hints = template.qa_pre_baker_hints
        if evidence_block:
            enriched_hints = (
                f"{template.qa_pre_baker_hints}\n\n"
                f"Use the following clinical guidelines to inform the Q&A "
                f"(but still ground each answer in patient citations):\n\n{evidence_block}"
            )

        qa_items, llm_meta = bake_questions(
            specialty=target_specialty,
            entities_text=entities_text,
            specialty_hints=enriched_hints,
            source_raw_texts=sources,
        )
        sections.open_questions = qa_items

        payload = BriefingPayload(
            schema_version="1.0",
            generated_at=datetime.now(UTC),
            target_specialty=target_specialty,
            patient=patient,
            sections=sections,
            applied_filter=AppliedFilter(
                specialty=target_specialty.value, rules_version=template.rules_version
            ),
            llm_meta=llm_meta,
            evidence_citations=evidence_citations,
        )

        html = render_briefing_html(payload)
        status = "ready"

    except QAPrebakerError as e:
        error_message = f"qa_pre_baker failed: {e}"
        logger.error("briefing %s qa_pre_baker error: %s", briefing_id, e)
    except Exception as e:
        error_message = f"orchestrator error: {e}"
        logger.exception("briefing %s orchestrator unexpected error", briefing_id)

    try:
        await _persist_briefing_status(
            briefing_id=briefing_id,
            payload=payload,
            html_render=html,
            status=status,
            error_message=error_message,
        )
    except Exception as e:
        logger.exception("briefing %s failed to write final status: %s", briefing_id, e)
