"""Generate a realistic Apple Health export.zip (iOS layout) for testing.

Mirrors what `Salud → Perfil → Exportar todos los datos` produces: a ZIP with
`apple_health_export/export.xml`, an XML declaration + DOCTYPE, <HealthData>,
<ExportDate>, <Me>, and many <Record> elements across device sources.
"""

from __future__ import annotations

import io
import zipfile

# (apple_type, unit, sourceName, value, date)
_SAMPLE_RECORDS = [
    ("HKQuantityTypeIdentifierBodyMass", "kg", "Withings", "82.4", "2024-11-18 07:30:00 +0100"),
    ("HKQuantityTypeIdentifierBodyMass", "kg", "Withings", "82.1", "2024-11-19 07:31:00 +0100"),
    ("HKQuantityTypeIdentifierBloodGlucose", "mg/dL", "Accu-Chek", "138", "2024-11-18 08:00:00 +0100"),
    ("HKQuantityTypeIdentifierBloodGlucose", "mg/dL", "Accu-Chek", "126", "2024-11-19 08:02:00 +0100"),
    ("HKQuantityTypeIdentifierBloodPressureSystolic", "mmHg", "Omron", "132", "2024-11-18 09:00:00 +0100"),
    ("HKQuantityTypeIdentifierBloodPressureDiastolic", "mmHg", "Omron", "85", "2024-11-18 09:00:00 +0100"),
    ("HKQuantityTypeIdentifierHeartRate", "count/min", "Apple Watch", "72", "2024-11-18 09:05:00 +0100"),
    ("HKQuantityTypeIdentifierRestingHeartRate", "count/min", "Apple Watch", "58", "2024-11-18 06:00:00 +0100"),
    ("HKQuantityTypeIdentifierStepCount", "count", "iPhone", "8423", "2024-11-18 00:00:00 +0100"),
    ("HKQuantityTypeIdentifierVO2Max", "mL/min·kg", "Apple Watch", "41.2", "2024-11-17 18:00:00 +0100"),
]

_DOCTYPE = """<!DOCTYPE HealthData [
<!ELEMENT HealthData (ExportDate,Me,(Record|Workout)*)>
<!ATTLIST HealthData locale CDATA #REQUIRED>
<!ELEMENT ExportDate EMPTY>
<!ATTLIST ExportDate value CDATA #REQUIRED>
<!ELEMENT Me EMPTY>
<!ELEMENT Record (MetadataEntry)*>
<!ATTLIST Record type CDATA #REQUIRED unit CDATA #IMPLIED value CDATA #IMPLIED sourceName CDATA #REQUIRED startDate CDATA #REQUIRED endDate CDATA #REQUIRED>
]>"""


def build_export_xml(records=_SAMPLE_RECORDS) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        _DOCTYPE,
        '<HealthData locale="es_ES">',
        ' <ExportDate value="2024-11-20 10:30:00 +0100"/>',
        ' <Me HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexMale"'
        ' HKCharacteristicTypeIdentifierDateOfBirth="1979-05-12"/>',
    ]
    for atype, unit, src, val, date in records:
        lines.append(
            f' <Record type="{atype}" sourceName="{src}" unit="{unit}"'
            f' value="{val}" startDate="{date}" endDate="{date}"/>'
        )
    lines.append("</HealthData>")
    return "\n".join(lines)


def build_export_zip(records=_SAMPLE_RECORDS) -> bytes:
    """ZIP with the apple_health_export/ folder iOS uses."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("apple_health_export/export.xml", build_export_xml(records))
        # iOS also bundles a CDA file; include a stub so name-matching is realistic.
        zf.writestr("apple_health_export/export_cda.xml", "<ClinicalDocument/>")
    return buf.getvalue()


SAMPLE_RECORD_COUNT = len(_SAMPLE_RECORDS)
