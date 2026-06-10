"""Apple Health export.xml parser — streams biometric records.

Apple Health exports a ZIP containing:
- export.xml: biometric records (HKQuantityType, HKCategoryType, HKWorkout, etc.)
- export_cda.xml: clinical CDA documents (v0.1.1)
- electrocardiograms/: ECG samples folder (v0.1.1)

v0.1 parses ONLY export.xml biometric Record elements. Stream-parses via
lxml.etree.iterparse to bound memory on multi-GB exports.

Output: generator of HealthRecord dicts, ready for bulk insert as Entity rows
with entity_type='observation', provenance='patient_stated'.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import IO, Iterator

from lxml import etree


# Subset of Apple Health types we map to AdelIA observation names (v0.1).
# Extend this dict to cover more types — each entry maps the HK identifier
# to an AdelIA-friendly observation name used in the entities table.
APPLE_HEALTH_TYPES: dict[str, str] = {
    # Anthropometrics
    "HKQuantityTypeIdentifierBodyMass": "weight",
    "HKQuantityTypeIdentifierHeight": "height",
    "HKQuantityTypeIdentifierBodyMassIndex": "bmi",
    "HKQuantityTypeIdentifierLeanBodyMass": "lean_body_mass",
    "HKQuantityTypeIdentifierBodyFatPercentage": "body_fat_pct",
    "HKQuantityTypeIdentifierWaistCircumference": "waist_circumference",
    # Cardiovascular
    "HKQuantityTypeIdentifierBloodPressureSystolic": "bp_systolic",
    "HKQuantityTypeIdentifierBloodPressureDiastolic": "bp_diastolic",
    "HKQuantityTypeIdentifierHeartRate": "heart_rate",
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_heart_rate",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv_sdnn",
    "HKQuantityTypeIdentifierVO2Max": "vo2_max",
    # Metabolic
    "HKQuantityTypeIdentifierBloodGlucose": "glucose",
    "HKQuantityTypeIdentifierInsulinDelivery": "insulin_delivery",
    "HKQuantityTypeIdentifierBloodAlcoholContent": "blood_alcohol",
    # Respiratory
    "HKQuantityTypeIdentifierRespiratoryRate": "respiratory_rate",
    "HKQuantityTypeIdentifierOxygenSaturation": "spo2",
    "HKQuantityTypeIdentifierForcedExpiratoryVolume1": "fev1",
    "HKQuantityTypeIdentifierForcedVitalCapacity": "fvc",
    # Body
    "HKQuantityTypeIdentifierBodyTemperature": "body_temp",
    "HKQuantityTypeIdentifierBasalBodyTemperature": "basal_body_temp",
    # Activity
    "HKQuantityTypeIdentifierStepCount": "steps",
    "HKQuantityTypeIdentifierDistanceWalkingRunning": "distance_walked",
    "HKQuantityTypeIdentifierActiveEnergyBurned": "active_calories",
    "HKQuantityTypeIdentifierBasalEnergyBurned": "basal_calories",
    "HKQuantityTypeIdentifierFlightsClimbed": "flights_climbed",
    # Sleep / Nutrition (subset)
    "HKQuantityTypeIdentifierDietaryWater": "water_intake",
    "HKQuantityTypeIdentifierDietaryCaffeine": "caffeine",
}


@dataclass(frozen=True)
class HealthRecord:
    """Single parsed Apple Health Record entry."""

    name: str  # AdelIA-friendly observation name (e.g. 'glucose')
    apple_type: str  # original HK identifier (e.g. HKQuantityTypeIdentifierBloodGlucose)
    value: str  # raw value as string (preserves precision)
    unit: str | None
    event_date: date | None
    source_name: str | None
    raw_quote: str  # verbatim text reconstructed for citation


def _parse_apple_date(value: str | None) -> datetime | None:
    """Apple Health uses 'YYYY-MM-DD HH:MM:SS +ZZZZ'. Returns datetime or None."""
    if not value:
        return None
    try:
        # Normalize Apple's format to ISO (T separator + colon in offset)
        normalized = value.replace(" ", "T", 1)
        if len(normalized) >= 6 and normalized[-5] in "+-":
            normalized = normalized[:-5] + normalized[-5:-2] + ":" + normalized[-2:]
        return datetime.fromisoformat(normalized)
    except (ValueError, IndexError):
        return None


def parse_health_records(source: IO[bytes] | str, max_records: int | None = None) -> Iterator[HealthRecord]:
    """Stream-parse Apple Health export.xml; yield HealthRecord items.

    Args:
        source: file-like binary stream or path to export.xml
        max_records: optional cap for testing

    Yields HealthRecord per Record element whose `type` is in APPLE_HEALTH_TYPES.
    """
    count = 0
    context = etree.iterparse(source, events=("end",), tag="Record")

    for _event, elem in context:
        apple_type = elem.get("type", "")
        if apple_type in APPLE_HEALTH_TYPES:
            value_raw = elem.get("value")
            if value_raw is None:
                # Some records (e.g. asleep) have no value attribute; skip in v0.1
                elem.clear()
                continue
            unit = elem.get("unit")
            start_str = elem.get("startDate")
            source_name = elem.get("sourceName")
            start_dt = _parse_apple_date(start_str)
            event_date_val: date | None = start_dt.date() if start_dt else None
            raw_quote = (
                f"{apple_type}={value_raw}"
                + (f" {unit}" if unit else "")
                + (f" from {source_name}" if source_name else "")
                + (f" on {start_str}" if start_str else "")
            )
            yield HealthRecord(
                name=APPLE_HEALTH_TYPES[apple_type],
                apple_type=apple_type,
                value=value_raw,
                unit=unit,
                event_date=event_date_val,
                source_name=source_name,
                raw_quote=raw_quote,
            )
            count += 1
            if max_records is not None and count >= max_records:
                elem.clear()
                break

        # Free memory after each Record processed (streaming pattern)
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]


def count_records(source: IO[bytes] | str) -> int:
    """Total count of supported Record elements in the export.xml.

    Useful for progress reporting before bulk insert. O(N) — only call once.
    """
    return sum(1 for _ in parse_health_records(source))
