"""Pure unit tests for HL7 C-CDA parser."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from adelia.ingestion.ccd_parser import (
    SECTION_OIDS,
    SECTION_TO_ENTITY_TYPE,
    parse_ccd,
)


_FIXTURE = Path(__file__).parent / "fixtures" / "ingestion" / "ccd_sample.xml"


def test_parser_extracts_patient_demographics():
    doc = parse_ccd(str(_FIXTURE))
    assert doc.patient.given_name == "Jane"
    assert doc.patient.family_name == "Doe"
    assert doc.patient.birth_date == date(1985, 3, 15)
    assert doc.patient.sex == "F"


def test_parser_extracts_allergies_section():
    doc = parse_ccd(str(_FIXTURE))
    allergies = [e for e in doc.entries if e.section == "allergies"]
    assert len(allergies) == 2
    names = {e.name for e in allergies}
    assert "Allergy to penicillin" in names
    assert "Allergy to peanuts" in names
    for a in allergies:
        assert a.entity_type == "allergy"


def test_parser_extracts_medications_with_dose_and_route():
    doc = parse_ccd(str(_FIXTURE))
    meds = [e for e in doc.entries if e.section == "medications"]
    assert len(meds) == 1
    metformin = meds[0]
    assert metformin.name == "metformin"
    assert metformin.code == "6809"
    assert metformin.coding_system == "RxNorm"
    assert metformin.value.get("dose") == "500 mg"
    assert metformin.value.get("route") == "Oral"


def test_parser_extracts_problems_with_status():
    doc = parse_ccd(str(_FIXTURE))
    problems = [e for e in doc.entries if e.section == "problems"]
    assert len(problems) == 1
    diabetes = problems[0]
    assert diabetes.entity_type == "condition"
    assert "diabetes" in diabetes.name.lower()
    assert diabetes.value.get("status") == "active"
    assert diabetes.event_date == date(2024, 1, 1)


def test_parser_extracts_procedures():
    doc = parse_ccd(str(_FIXTURE))
    procs = [e for e in doc.entries if e.section == "procedures"]
    assert len(procs) == 1
    assert procs[0].name == "Colonoscopy"
    assert procs[0].event_date == date(2025, 10, 10)


def test_parser_extracts_vital_signs_with_value_and_unit():
    doc = parse_ccd(str(_FIXTURE))
    vitals = [e for e in doc.entries if e.section == "vital_signs"]
    assert len(vitals) == 1
    weight = vitals[0]
    assert weight.entity_type == "observation"
    assert weight.value.get("value") == "68.5"
    assert weight.value.get("unit") == "kg"


def test_parser_extracts_lab_results():
    doc = parse_ccd(str(_FIXTURE))
    results = [e for e in doc.entries if e.section == "results"]
    assert len(results) == 1
    hba1c = results[0]
    assert "A1c" in hba1c.name or "Hemoglobin" in hba1c.name
    assert hba1c.value.get("value") == "6.2"
    assert hba1c.value.get("unit") == "%"


def test_parser_extracts_immunizations():
    doc = parse_ccd(str(_FIXTURE))
    imms = [e for e in doc.entries if e.section == "immunizations"]
    assert len(imms) == 1
    flu = imms[0]
    assert "nfluenza" in flu.name
    assert flu.event_date == date(2025, 10, 15)


def test_parser_builds_raw_quote_for_every_entry():
    doc = parse_ccd(str(_FIXTURE))
    for entry in doc.entries:
        assert entry.raw_quote
        assert entry.section in entry.raw_quote


def test_section_oid_map_covers_7_v01_sections():
    """v0.1 supports exactly 7 CCD sections (per spec §10)."""
    assert len(SECTION_OIDS) == 7
    assert set(SECTION_TO_ENTITY_TYPE.values()) == {
        "allergy",
        "medication",
        "condition",
        "procedure",
        "observation",
        "immunization",
    }


def test_parser_total_entry_count_matches_fixture():
    doc = parse_ccd(str(_FIXTURE))
    # 2 allergies + 1 medication + 1 problem + 1 procedure + 1 vital + 1 lab + 1 immunization = 8
    assert len(doc.entries) == 8
