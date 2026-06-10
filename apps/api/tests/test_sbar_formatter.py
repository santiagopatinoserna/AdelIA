"""Pure unit tests for sbar_formatter. No DB, no LLM, no API."""
from __future__ import annotations

from uuid import uuid4


from adelia.schemas import Specialty
from adelia.services.sbar_formatter import (
    EntityInput,
    format_sections,
)


def _entity(
    entity_type: str,
    name: str,
    raw_quote: str = "raw quote",
    value: dict | None = None,
    event_date: str | None = None,
    provenance: str = "extracted_from_clinician_doc",
) -> EntityInput:
    return EntityInput(
        id=uuid4(),
        document_id=uuid4(),
        entity_type=entity_type,
        name=name,
        value=value or {},
        event_date=event_date,
        raw_quote=raw_quote,
        provenance=provenance,
    )


def test_no_allergies_renders_no_known_allergies():
    sections = format_sections(
        entities=[_entity("condition", "asthma")],
        specialty=Specialty.DEFAULT,
        reason_for_consult=None,
    )
    assert sections.allergies == "no_known_allergies"


def test_with_allergies_renders_list():
    sections = format_sections(
        entities=[_entity("allergy", "penicillin", raw_quote="allergic to penicillin")],
        specialty=Specialty.DEFAULT,
        reason_for_consult=None,
    )
    assert isinstance(sections.allergies, list)
    assert len(sections.allergies) == 1
    assert sections.allergies[0].substance == "penicillin"


def test_pediatrics_includes_immunizations():
    sections = format_sections(
        entities=[_entity("immunization", "MMR", event_date="2024-03-15")],
        specialty=Specialty.PEDIATRICS,
        reason_for_consult=None,
    )
    assert sections.immunizations is not None
    assert len(sections.immunizations) == 1


def test_default_specialty_hides_immunizations():
    sections = format_sections(
        entities=[_entity("immunization", "tetanus")],
        specialty=Specialty.DEFAULT,
        reason_for_consult=None,
    )
    assert sections.immunizations is None


def test_cardiology_includes_family_history():
    sections = format_sections(
        entities=[_entity("family_history", "father had MI at 55")],
        specialty=Specialty.CARDIOLOGY,
        reason_for_consult=None,
    )
    assert sections.family_history is not None
    assert len(sections.family_history) == 1


def test_default_specialty_hides_family_history():
    sections = format_sections(
        entities=[_entity("family_history", "diabetes")],
        specialty=Specialty.DEFAULT,
        reason_for_consult=None,
    )
    assert sections.family_history is None


def test_reason_for_consult_passed_through():
    sections = format_sections(
        entities=[],
        specialty=Specialty.DEFAULT,
        reason_for_consult="control diabetes",
    )
    assert sections.reason_for_consult == "control diabetes"


def test_active_problems_extracts_conditions():
    sections = format_sections(
        entities=[
            _entity("condition", "type 2 diabetes"),
            _entity("condition", "hypertension"),
        ],
        specialty=Specialty.DEFAULT,
        reason_for_consult=None,
    )
    assert len(sections.active_problems) == 2
    names = {p.name for p in sections.active_problems}
    assert names == {"type 2 diabetes", "hypertension"}


def test_medications_extracted_with_dose():
    sections = format_sections(
        entities=[
            _entity(
                "medication",
                "metformin",
                value={"dose": "500mg", "frequency": "BID"},
            )
        ],
        specialty=Specialty.DEFAULT,
        reason_for_consult=None,
    )
    assert len(sections.medications) == 1
    med = sections.medications[0]
    assert med.name == "metformin"
    assert med.dose == "500mg"
    assert med.frequency == "BID"


def test_observations_filtered_by_endocrinology_whitelist():
    sections = format_sections(
        entities=[
            _entity("observation", "HbA1c", value={"value": "6.2", "unit": "%"}),
            _entity("observation", "random_thing", value={"value": "1"}),
        ],
        specialty=Specialty.ENDOCRINOLOGY,
        reason_for_consult=None,
    )
    obs_names = {o.name for o in sections.relevant_observations}
    assert "HbA1c" in obs_names
    assert "random_thing" not in obs_names


def test_observations_unfiltered_with_default_specialty():
    sections = format_sections(
        entities=[
            _entity("observation", "HbA1c", value={"value": "6.2"}),
            _entity("observation", "random_thing", value={"value": "1"}),
        ],
        specialty=Specialty.DEFAULT,
        reason_for_consult=None,
    )
    obs_names = {o.name for o in sections.relevant_observations}
    assert obs_names == {"HbA1c", "random_thing"}


def test_provenance_passed_through():
    sections = format_sections(
        entities=[
            _entity("allergy", "peanuts", provenance="patient_stated"),
        ],
        specialty=Specialty.DEFAULT,
        reason_for_consult=None,
    )
    assert isinstance(sections.allergies, list)
    assert sections.allergies[0].provenance == "patient_stated"


def test_empty_entities_produces_empty_sections():
    sections = format_sections(
        entities=[],
        specialty=Specialty.DEFAULT,
        reason_for_consult=None,
    )
    assert sections.active_problems == []
    assert sections.medications == []
    assert sections.allergies == "no_known_allergies"
    assert sections.procedures == []
    assert sections.relevant_observations == []
