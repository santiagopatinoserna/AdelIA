"""Pure entity-to-section formatter for briefings.

NO DB, NO LLM, NO API. Takes a list of EntityInput + specialty + optional
reason_for_consult; returns a BriefingSections payload with the 8 universal
sections, filtered per specialty filter rules.

Trade-off: this is intentionally NOT a service that loads from DB. The orchestrator
loads entities first (with the user_id + deleted_at filter), then passes them here
as a pure transformation. Keeps this module testable without Postgres.
"""
from __future__ import annotations

import re
import unicodedata
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
    status: str | None = None
    provenance: Literal["extracted_from_clinician_doc", "patient_stated"]


def _to_citation(e: EntityInput) -> Citation:
    return Citation(
        document_id=e.document_id,
        entity_id=e.id,
        raw_quote=e.raw_quote,
    )


# Statuses meaning "not a current medication" — a planned/recommended drug
# from a PLAN section must not land on the doctor's active medication list.
_NON_CURRENT_MED_STATUS = {
    "planned", "recommended", "proposed", "suspended",
    "discontinued", "stopped", "held",
}


def _norm_words(name: str) -> list[str]:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return [w for w in re.split(r"\W+", ascii_name.lower()) if w]


def _group_key(name: str, key_words: int) -> tuple[str, ...]:
    words = _norm_words(name)
    return tuple(words[:key_words]) if words else (name.lower(),)


def _dedupe_items(entities: list[EntityInput], key_words: int) -> list[tuple[EntityInput, list[Citation]]]:
    """Collapse entities whose names share their first `key_words` significant
    words (same clinical concept). Returns (representative, merged citations):
    keeps the most specific (longest) name, preserves every variant's citation
    so traceability survives the dedup."""
    groups: dict[tuple[str, ...], list[EntityInput]] = {}
    order: list[tuple[str, ...]] = []
    for e in entities:
        key = _group_key(e.name, key_words)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(e)
    return [
        (max(groups[k], key=lambda e: len(e.name)), [_to_citation(e) for e in groups[k]])
        for k in order
    ]


def _is_current_medication(e: EntityInput) -> bool:
    # status lives on the entity; older docs may also carry it in value.
    status = e.status or ((e.value or {}).get("status") if isinstance(e.value, dict) else None)
    return str(status).lower() not in _NON_CURRENT_MED_STATUS


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

    # Dedupe the same condition stated twice (e.g. "DM2 mal controlada" +
    # "DM2 descompensada") into one problem, merging citations.
    active_problems = [
        ProblemItem(
            name=e.name,
            status=e.value.get("status") if isinstance(e.value, dict) else None,
            onset_date=e.event_date,
            citations=cites,
            provenance=e.provenance,
        )
        for e, cites in _dedupe_items(by_type.get("condition", []), key_words=3)
    ]

    # Only CURRENT meds reach the active list; a planned/recommended drug
    # ("add an SGLT2 inhibitor") is filtered out. Then dedupe by drug name.
    current_meds = [e for e in by_type.get("medication", []) if _is_current_medication(e)]
    medications = [
        MedicationItem(
            name=e.name,
            dose=e.value.get("dose") if isinstance(e.value, dict) else None,
            route=e.value.get("route") if isinstance(e.value, dict) else None,
            frequency=e.value.get("frequency") if isinstance(e.value, dict) else None,
            started=e.event_date,
            citations=cites,
            provenance=e.provenance,
        )
        for e, cites in _dedupe_items(current_meds, key_words=1)
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
