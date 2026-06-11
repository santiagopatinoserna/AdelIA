"""Briefing clinical-quality: dedupe conditions, drop planned meds.

Pure/deterministic — no API. Guards what the doctor sees: no duplicate
diagnoses, no recommended-but-not-prescribed drug on the active list, and
traceability preserved across the dedup (every variant's citation kept).
"""
from uuid import uuid4

from adelia.schemas import Specialty
from adelia.services.sbar_formatter import EntityInput, format_sections


def _ent(entity_type, name, *, status=None, raw_quote=None, value=None):
    return EntityInput(
        id=uuid4(),
        document_id=uuid4(),
        entity_type=entity_type,
        name=name,
        value=value or {},
        raw_quote=raw_quote or name,
        status=status,
        provenance="extracted_from_clinician_doc",
    )


def test_duplicate_condition_collapses_and_merges_citations():
    sections = format_sections(
        [
            _ent("condition", "Diabetes mellitus tipo 2 mal controlada", raw_quote="mal controlada"),
            _ent("condition", "Diabetes mellitus tipo 2 descompensada", raw_quote="descompensada"),
            _ent("condition", "Dislipemia mixta", raw_quote="Dislipemia mixta"),
        ],
        Specialty.ENDOCRINOLOGY,
        reason_for_consult=None,
    )
    names = [p.name for p in sections.active_problems]
    assert len(names) == 2, f"expected diabetes deduped + dyslipidemia, got {names}"
    diabetes = next(p for p in sections.active_problems if "iabetes" in p.name)
    # most specific name kept, BOTH source quotes preserved for the doctor's audit
    assert len(diabetes.citations) == 2
    quotes = {c.raw_quote for c in diabetes.citations}
    assert quotes == {"mal controlada", "descompensada"}


def test_planned_medication_is_dropped_from_active_list():
    sections = format_sections(
        [
            _ent("medication", "Metformina", status="current"),
            _ent("medication", "Atorvastatina", status=None),  # unstated → current
            _ent("medication", "inhibidor SGLT2", status="planned"),  # PLAN — must drop
        ],
        Specialty.ENDOCRINOLOGY,
        reason_for_consult=None,
    )
    names = {m.name for m in sections.medications}
    assert "Metformina" in names
    assert "Atorvastatina" in names
    assert not any("sglt2" in n.lower() for n in names), f"planned drug leaked: {names}"


def test_same_drug_deduped_by_name():
    sections = format_sections(
        [
            _ent("medication", "Metformina 1000 mg", raw_quote="Metformina 1000 mg"),
            _ent("medication", "Metformina", raw_quote="Metformina"),
        ],
        Specialty.ENDOCRINOLOGY,
        reason_for_consult=None,
    )
    assert len(sections.medications) == 1
    assert len(sections.medications[0].citations) == 2  # traceability preserved
