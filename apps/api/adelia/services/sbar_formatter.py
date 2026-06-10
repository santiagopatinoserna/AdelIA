"""Pure entity-to-section formatter for briefings.

NO DB, NO LLM, NO API. Takes a list of EntityInput + specialty + optional
reason_for_consult; returns a BriefingSections payload with the 8 universal
sections, filtered per specialty filter rules.

Trade-off: this is intentionally NOT a service that loads from DB. The orchestrator
loads entities first (with the user_id + deleted_at filter), then passes them here
as a pure transformation. Keeps this module testable without Postgres.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from adelia.schemas import (
    AllergyItem,
    BriefingSections,
    Citation,
    FamilyHistoryItem,
    ImmunizationItem,
    MedicationItem,
    ObservationItem,
    ProblemItem,
    ProcedureItem,
    Specialty,
)
from adelia.specialty_templates import SpecialtyTemplate, load_template


class EntityInput(BaseModel):
    """Subset of Entity ORM fields needed by sbar_formatter.

    Decoupled from ORM so the formatter remains pure.
    """
    id: UUID
    document_id: UUID
    entity_type: str
    name: str
    value: dict = Field(default_factory=dict)
    event_date: str | None = None
    raw_quote: str
    provenance: Literal["extracted_from_clinician_doc", "patient_stated"]


def _to_citation(e: EntityInput) -> Citation:
    return Citation(
        document_id=e.document_id,
        entity_id=e.id,
        raw_quote=e.raw_quote,
    )


def _filter_observations(
    entities: list[EntityInput], template: SpecialtyTemplate
) -> list[EntityInput]:
    """Apply specialty whitelist/blacklist to observation entities.

    Empty whitelist = include all (subject to blacklist).
    """
    obs = [e for e in entities if e.entity_type == "observation"]

    if template.highlight_observations:
        whitelist = set(template.highlight_observations)
        obs = [e for e in obs if e.name in whitelist]

    if template.exclude_observations:
        blacklist = set(template.exclude_observations)
        obs = [e for e in obs if e.name not in blacklist]

    return obs


def format_sections(
    entities: list[EntityInput],
    specialty: Specialty,
    reason_for_consult: str | None,
) -> BriefingSections:
    """Transform a list of entities into a BriefingSections payload.

    Applies specialty filter rules. Idempotent and deterministic given
    the same inputs.
    """
    template = load_template(specialty)

    by_type: dict[str, list[EntityInput]] = {}
    for e in entities:
        by_type.setdefault(e.entity_type, []).append(e)

    active_problems = [
        ProblemItem(
            name=e.name,
            status=e.value.get("status") if isinstance(e.value, dict) else None,
            onset_date=e.event_date,
            citations=[_to_citation(e)],
            provenance=e.provenance,
        )
        for e in by_type.get("condition", [])
    ]

    medications = [
        MedicationItem(
            name=e.name,
            dose=e.value.get("dose") if isinstance(e.value, dict) else None,
            route=e.value.get("route") if isinstance(e.value, dict) else None,
            frequency=e.value.get("frequency") if isinstance(e.value, dict) else None,
            started=e.event_date,
            citations=[_to_citation(e)],
            provenance=e.provenance,
        )
        for e in by_type.get("medication", [])
    ]

    allergy_entities = by_type.get("allergy", [])
    if allergy_entities:
        allergies: list[AllergyItem] | str = [
            AllergyItem(
                substance=e.name,
                reaction=e.value.get("reaction") if isinstance(e.value, dict) else None,
                severity=e.value.get("severity") if isinstance(e.value, dict) else None,
                citations=[_to_citation(e)],
                provenance=e.provenance,
            )
            for e in allergy_entities
        ]
    else:
        allergies = "no_known_allergies"

    immunizations: list[ImmunizationItem] | None = None
    if template.include_immunizations:
        immunizations = [
            ImmunizationItem(
                name=e.name,
                date=e.event_date,
                citations=[_to_citation(e)],
                provenance=e.provenance,
            )
            for e in by_type.get("immunization", [])
        ]

    procedures = [
        ProcedureItem(
            name=e.name,
            date=e.event_date,
            citations=[_to_citation(e)],
            provenance=e.provenance,
        )
        for e in by_type.get("procedure", [])
    ]

    family_history: list[FamilyHistoryItem] | None = None
    if template.include_family_history:
        fh_entities = by_type.get("family_history", [])
        family_history = [
            FamilyHistoryItem(
                relation=e.value.get("relation", "unknown") if isinstance(e.value, dict) else "unknown",
                condition=e.name,
                citations=[_to_citation(e)],
                provenance=e.provenance,
            )
            for e in fh_entities
        ]

    obs_filtered = _filter_observations(entities, template)
    relevant_observations = [
        ObservationItem(
            name=e.name,
            value=str(e.value.get("value", "")) if isinstance(e.value, dict) else "",
            unit=e.value.get("unit") if isinstance(e.value, dict) else None,
            date=e.event_date,
            trend=None,
            citations=[_to_citation(e)],
            provenance=e.provenance,
        )
        for e in obs_filtered
    ]

    return BriefingSections(
        reason_for_consult=reason_for_consult,
        active_problems=active_problems,
        medications=medications,
        allergies=allergies,
        immunizations=immunizations,
        procedures=procedures,
        family_history=family_history,
        relevant_observations=relevant_observations,
        open_questions=[],
    )
