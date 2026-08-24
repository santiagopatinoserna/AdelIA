"""One-click full data export (GDPR art. 20 portability).

Two layers in one JSON payload, honestly labeled:

- ``fhir_bundle``: a FHIR R4 ``Bundle`` (type ``collection``) with one
  ``Patient`` per profile and the clinical entities mapped to proper
  resource types. Entities already carry ICD-10/SNOMED/LOINC codings, so
  the mapping is faithful where FHIR has a slot and conservative where it
  doesn't (anything unmappable becomes an ``Observation`` with the original
  type preserved in ``code.text``).
- ``adelia``: everything FHIR has no slot for, raw and complete: document
  transcripts/texts, consent events, provenance and confidence per entity.

The export deliberately contains NO embeddings (derived, huge, useless to a
human or another provider) and no S3 keys (internal).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from adelia.models import ConsentEvent, Document, Entity, Profile

EXPORT_FORMAT = "adelia-export-v1"

_CODING_SYSTEM_URIS = {
    "ICD-10": "http://hl7.org/fhir/sid/icd-10",
    "ICD10": "http://hl7.org/fhir/sid/icd-10",
    "SNOMED": "http://snomed.info/sct",
    "SNOMED-CT": "http://snomed.info/sct",
    "LOINC": "http://loinc.org",
    "RXNORM": "http://www.nlm.nih.gov/research/umls/rxnorm",
}

# entity_type (entities_type_check) -> FHIR R4 resourceType. Types with no
# clean FHIR home map to Observation, keeping the original type visible.
_RESOURCE_TYPES = {
    "condition": "Condition",
    "medication": "MedicationStatement",
    "allergy": "AllergyIntolerance",
    "immunization": "Immunization",
    "procedure": "Procedure",
    "observation": "Observation",
    "family_history": "FamilyMemberHistory",
    "device": "Device",
    "allergen_reaction": "AllergyIntolerance",
    "social_history": "Observation",
}


def _codeable_concept(entity: Entity) -> dict[str, Any]:
    concept: dict[str, Any] = {"text": entity.name}
    if entity.code:
        system = _CODING_SYSTEM_URIS.get((entity.coding_system or "").upper())
        coding: dict[str, Any] = {"code": entity.code, "display": entity.name}
        if system:
            coding["system"] = system
        concept["coding"] = [coding]
    return concept


def _iso(d: date | datetime | None) -> str | None:
    return d.isoformat() if d else None


def _entity_resource(entity: Entity, patient_ref: str) -> dict[str, Any]:
    resource_type = _RESOURCE_TYPES.get(entity.entity_type, "Observation")
    resource: dict[str, Any] = {
        "resourceType": resource_type,
        "id": str(entity.id),
        "meta": {"source": f"urn:adelia:document:{entity.document_id}"},
    }
    concept = _codeable_concept(entity)
    when = _iso(entity.event_date)

    if resource_type == "Condition":
        resource["code"] = concept
        resource["subject"] = {"reference": patient_ref}
        if when:
            resource["onsetDateTime"] = when
    elif resource_type == "MedicationStatement":
        resource["medicationCodeableConcept"] = concept
        resource["subject"] = {"reference": patient_ref}
        resource["status"] = "recorded"
        if when:
            resource["effectiveDateTime"] = when
    elif resource_type == "AllergyIntolerance":
        resource["code"] = concept
        resource["patient"] = {"reference": patient_ref}
        if when:
            resource["onsetDateTime"] = when
    elif resource_type == "Immunization":
        resource["vaccineCode"] = concept
        resource["patient"] = {"reference": patient_ref}
        resource["status"] = "completed"
        if when:
            resource["occurrenceDateTime"] = when
    elif resource_type == "Procedure":
        resource["code"] = concept
        resource["subject"] = {"reference": patient_ref}
        resource["status"] = "completed"
        if when:
            resource["performedDateTime"] = when
    elif resource_type == "FamilyMemberHistory":
        resource["patient"] = {"reference": patient_ref}
        resource["status"] = "completed"
        resource["relationship"] = {"text": "family"}
        resource["condition"] = [{"code": concept}]
    elif resource_type == "Device":
        resource["deviceName"] = [{"name": entity.name, "type": "user-friendly-name"}]
        resource["patient"] = {"reference": patient_ref}
    else:  # Observation (also the fallback for unexpected types)
        resource["code"] = concept
        resource["subject"] = {"reference": patient_ref}
        resource["status"] = "final"
        if when:
            resource["effectiveDateTime"] = when
        if entity.entity_type not in _RESOURCE_TYPES:
            resource["code"] = {**concept, "text": f"{entity.entity_type}: {entity.name}"}
        if isinstance(entity.value, dict) and "value" in entity.value:
            val = entity.value.get("value")
            unit = entity.value.get("unit")
            if isinstance(val, (int, float)):
                quantity: dict[str, Any] = {"value": val}
                if unit:
                    quantity["unit"] = unit
                resource["valueQuantity"] = quantity
            elif isinstance(val, str):
                resource["valueString"] = val

    return resource


async def build_export(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    profiles = (
        (
            await db.execute(
                sa.select(Profile).where(
                    Profile.user_id == user_id, Profile.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    documents = (
        (
            await db.execute(
                sa.select(Document).where(
                    Document.user_id == user_id, Document.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    entities = (
        (
            await db.execute(
                sa.select(Entity).where(
                    Entity.user_id == user_id, Entity.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    consents = (
        (await db.execute(sa.select(ConsentEvent).where(ConsentEvent.user_id == user_id)))
        .scalars()
        .all()
    )

    default_patient_ref = "urn:adelia:profile:default"
    patient_entries: list[dict[str, Any]] = [
        {
            "resource": {
                "resourceType": "Patient",
                "id": str(p.id),
                "name": [{"text": p.display_name}],
                **({"birthDate": _iso(p.date_of_birth)} if p.date_of_birth else {}),
                **(
                    {"gender": {"M": "male", "F": "female"}.get((p.sex or "").upper(), "unknown")}
                    if p.sex
                    else {}
                ),
            }
        }
        for p in profiles
    ]

    def patient_ref_for(profile_id: uuid.UUID | None) -> str:
        if profile_id:
            return f"Patient/{profile_id}"
        default = next((p for p in profiles if p.is_default), None)
        return f"Patient/{default.id}" if default else default_patient_ref

    entity_entries = [
        {"resource": _entity_resource(e, patient_ref_for(e.profile_id))} for e in entities
    ]

    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entry": patient_entries + entity_entries,
    }

    return {
        "format": EXPORT_FORMAT,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "fhir_bundle": bundle,
        "adelia": {
            "documents": [
                {
                    "id": str(d.id),
                    "source": d.source,
                    "mime_type": d.mime_type,
                    "created_at": _iso(d.created_at),
                    "raw_text": d.raw_text,
                    "speaker_names": (d.document_metadata or {}).get("speaker_names"),
                    "summary": (d.document_metadata or {}).get("summary"),
                    "profile_id": str(d.profile_id) if d.profile_id else None,
                }
                for d in documents
            ],
            "entities": [
                {
                    "id": str(e.id),
                    "type": e.entity_type,
                    "name": e.name,
                    "coding_system": e.coding_system,
                    "code": e.code,
                    "value": e.value,
                    "event_date": _iso(e.event_date),
                    "provenance": e.provenance,
                    "confidence": e.confidence,
                    "raw_quote": e.raw_quote,
                    "document_id": str(e.document_id),
                }
                for e in entities
            ],
            "consent_events": [
                {
                    "id": str(c.id),
                    "event_type": c.event_type,
                    "policy_version": c.policy_version,
                    "locale": c.locale,
                    "created_at": _iso(c.created_at),
                }
                for c in consents
            ],
        },
    }
