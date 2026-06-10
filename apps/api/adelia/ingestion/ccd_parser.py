"""HL7 C-CDA (Continuity of Care Document) XML parser.

Generic parser for CCD R2.1 documents from any vendor (Epic MyChart, Cerner
HealtheLife, Allscripts, Athena, eClinicalWorks, NextGen, Greenway). Sections
identified by HL7 template OIDs (stable across vendors).

v0.1 supports 7 sections:
- Allergies (2.16.840.1.113883.10.20.22.2.6.1)
- Medications (2.16.840.1.113883.10.20.22.2.1.1)
- Problems (2.16.840.1.113883.10.20.22.2.5.1)
- Procedures (2.16.840.1.113883.10.20.22.2.7.1)
- Vital Signs (2.16.840.1.113883.10.20.22.2.4.1)
- Immunizations (2.16.840.1.113883.10.20.22.2.2.1)
- Results / Lab (2.16.840.1.113883.10.20.22.2.3.1)

Family History + Social History deferred to v0.1.1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import IO

from lxml import etree


_NS = {"hl7": "urn:hl7-org:v3"}


# Map HL7 section template OIDs to internal section keys
SECTION_OIDS = {
    "2.16.840.1.113883.10.20.22.2.6.1": "allergies",
    "2.16.840.1.113883.10.20.22.2.1.1": "medications",
    "2.16.840.1.113883.10.20.22.2.5.1": "problems",
    "2.16.840.1.113883.10.20.22.2.7.1": "procedures",
    "2.16.840.1.113883.10.20.22.2.4.1": "vital_signs",
    "2.16.840.1.113883.10.20.22.2.2.1": "immunizations",
    "2.16.840.1.113883.10.20.22.2.3.1": "results",
}


# Map AdelIA section key to entity_type for downstream Entity row creation
SECTION_TO_ENTITY_TYPE = {
    "allergies": "allergy",
    "medications": "medication",
    "problems": "condition",
    "procedures": "procedure",
    "vital_signs": "observation",
    "immunizations": "immunization",
    "results": "observation",
}


@dataclass(frozen=True)
class CCDPatient:
    """Patient demographics extracted from recordTarget."""

    family_name: str | None = None
    given_name: str | None = None
    birth_date: date | None = None
    sex: str | None = None  # 'M', 'F', or None


@dataclass(frozen=True)
class CCDEntry:
    """Single entity entry extracted from a CCD section."""

    section: str  # 'allergies', 'medications', ...
    entity_type: str  # 'allergy', 'medication', ...
    name: str  # human-readable name (e.g. "penicillin", "metformin", "type 2 diabetes")
    code: str | None  # e.g. SNOMED, RxNorm, LOINC code
    coding_system: str | None  # e.g. "RxNorm", "SNOMED-CT", "LOINC"
    value: dict = field(default_factory=dict)  # extra structured fields (dose, frequency, status, etc.)
    event_date: date | None = None
    raw_quote: str = ""  # verbatim text for citation


@dataclass(frozen=True)
class CCDDocument:
    """Result of parsing a full CCD."""

    patient: CCDPatient
    entries: list[CCDEntry]


def _parse_hl7_date(value: str | None) -> date | None:
    """HL7 dates: YYYYMMDD or YYYYMMDDHHMM[+ZZZZ]. Return date or None."""
    if not value:
        return None
    try:
        y = int(value[:4])
        m = int(value[4:6]) if len(value) >= 6 else 1
        d = int(value[6:8]) if len(value) >= 8 else 1
        return date(y, m, d)
    except (ValueError, IndexError):
        return None


def _text_of(elem) -> str:
    """Concatenated text inside an element including children, normalized whitespace."""
    if elem is None:
        return ""
    text = "".join(elem.itertext())
    return " ".join(text.split())


def _parse_patient(root) -> CCDPatient:
    """Extract recordTarget/patientRole/patient demographics."""
    patient_el = root.find(".//hl7:recordTarget/hl7:patientRole/hl7:patient", _NS)
    if patient_el is None:
        return CCDPatient()

    name = patient_el.find("hl7:name", _NS)
    given = name.findtext("hl7:given", default=None, namespaces=_NS) if name is not None else None
    family = name.findtext("hl7:family", default=None, namespaces=_NS) if name is not None else None

    birth = patient_el.find("hl7:birthTime", _NS)
    birth_date = _parse_hl7_date(birth.get("value")) if birth is not None else None

    gender = patient_el.find("hl7:administrativeGenderCode", _NS)
    sex = gender.get("code") if gender is not None else None  # 'M' or 'F' usually

    return CCDPatient(
        family_name=family,
        given_name=given,
        birth_date=birth_date,
        sex=sex,
    )


def _parse_entry_common(entry_el, section_key: str) -> CCDEntry | None:
    """Best-effort generic extraction for any section entry.

    Reads:
    - code/@displayName or code/@code (text representation)
    - effectiveTime/@value (event date)
    - text/@reference + lookup in section text/list (raw_quote)
    Returns None if no minimal name extractable.
    """
    # Try multiple paths for the "name" of this entry; vendors vary
    code_el = entry_el.find(".//hl7:code[@displayName]", _NS)
    name = None
    code_val = None
    coding_system = None
    if code_el is not None:
        name = code_el.get("displayName")
        code_val = code_el.get("code")
        coding_system = code_el.get("codeSystemName") or code_el.get("codeSystem")
    if not name:
        # Fallback to first text() of the entry (lossy but better than nothing)
        text_el = entry_el.find(".//hl7:text", _NS)
        name = _text_of(text_el)[:160] if text_el is not None else None
    if not name:
        return None

    eff_time = entry_el.find(".//hl7:effectiveTime", _NS)
    eff_value: date | None = None
    if eff_time is not None:
        ev = eff_time.get("value")
        if ev is None:
            low = eff_time.find("hl7:low", _NS)
            ev = low.get("value") if low is not None else None
        eff_value = _parse_hl7_date(ev)

    # Build value dict with section-specific fields
    value: dict = {}
    if section_key == "medications":
        # doseQuantity, routeCode, frequency (rate)
        dose_q = entry_el.find(".//hl7:doseQuantity", _NS)
        if dose_q is not None:
            if dose_q.get("value"):
                value["dose"] = dose_q.get("value")
                if dose_q.get("unit"):
                    value["dose"] = f"{dose_q.get('value')} {dose_q.get('unit')}"
        route = entry_el.find(".//hl7:routeCode", _NS)
        if route is not None and route.get("displayName"):
            value["route"] = route.get("displayName")
    elif section_key == "vital_signs" or section_key == "results":
        # Read observation value
        v_el = entry_el.find(".//hl7:value", _NS)
        if v_el is not None:
            v_val = v_el.get("value") or v_el.text
            if v_val:
                value["value"] = v_val
            if v_el.get("unit"):
                value["unit"] = v_el.get("unit")
    elif section_key == "problems":
        status_el = entry_el.find(".//hl7:statusCode", _NS)
        if status_el is not None and status_el.get("code"):
            value["status"] = status_el.get("code")

    raw_quote = (
        f"{section_key}: {name}"
        + (f" ({code_val})" if code_val else "")
        + (f" on {eff_value.isoformat()}" if eff_value else "")
    )

    return CCDEntry(
        section=section_key,
        entity_type=SECTION_TO_ENTITY_TYPE[section_key],
        name=name,
        code=code_val,
        coding_system=coding_system,
        value=value,
        event_date=eff_value,
        raw_quote=raw_quote,
    )


def parse_ccd(source: IO[bytes] | str) -> CCDDocument:
    """Parse a CCD XML document and return CCDDocument with all extracted entries."""
    tree = etree.parse(source)
    root = tree.getroot()
    patient = _parse_patient(root)

    entries: list[CCDEntry] = []

    # Find all section elements
    sections = root.findall(".//hl7:section", _NS)
    for section in sections:
        # Find templateId matching one of our supported OIDs
        section_key = None
        for tid in section.findall("hl7:templateId", _NS):
            root_attr = tid.get("root", "")
            if root_attr in SECTION_OIDS:
                section_key = SECTION_OIDS[root_attr]
                break
        if section_key is None:
            continue

        # Iterate entry/entryRelationship children
        for entry_el in section.findall("hl7:entry", _NS):
            parsed = _parse_entry_common(entry_el, section_key)
            if parsed is not None:
                entries.append(parsed)

    return CCDDocument(patient=patient, entries=entries)
