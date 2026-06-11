"""Apple Health import: realistic iOS export.zip end-to-end + XXE safety.

The user can't use a HealthKit API (none for third parties), but ANYONE can
export their data (Salud → Perfil → Exportar todos los datos) and upload the
resulting export.zip. These tests prove that path works on a realistic export
and is safe against malicious uploads.
"""
import io
import zipfile

import pytest

from adelia.config import settings
from adelia.ingestion.apple_health_parser import parse_health_records
from tests.clinical_corpus.apple_health import (
    SAMPLE_RECORD_COUNT,
    build_export_xml,
    build_export_zip,
)
from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE
from tests.test_auth import make_token


def test_parser_recovers_records_from_realistic_export():
    records = list(parse_health_records(io.BytesIO(build_export_xml().encode())))
    assert len(records) == SAMPLE_RECORD_COUNT
    by_name = {r.name for r in records}
    # The biometrics a clinician/patient cares about must come through.
    for expected in {"weight", "glucose", "bp_systolic", "bp_diastolic", "heart_rate", "steps"}:
        assert expected in by_name, f"missing {expected}"
    glucose = next(r for r in records if r.name == "glucose")
    assert glucose.value == "138" and glucose.unit == "mg/dL"
    assert glucose.source_name == "Accu-Chek"
    assert glucose.event_date is not None  # Apple date parsed


def test_parser_is_not_vulnerable_to_xxe():
    """A malicious export must NOT be able to read server files via an
    external XML entity."""
    xxe = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE HealthData [<!ENTITY x SYSTEM "file:///etc/passwd">]>\n'
        '<HealthData locale="x">\n'
        ' <Record type="HKQuantityTypeIdentifierBodyMass" unit="kg" value="&x;"'
        ' sourceName="evil" startDate="2024-01-01 00:00:00 +0000"/>\n'
        "</HealthData>"
    )
    leaked = ""
    try:
        recs = list(parse_health_records(io.BytesIO(xxe.encode())))
        leaked = recs[0].value if recs else ""
    except Exception:
        pass  # rejecting the entity is also safe
    assert "root:" not in leaked, "XXE: parser leaked file contents"


def test_export_zip_has_ios_layout():
    z = build_export_zip()
    with zipfile.ZipFile(io.BytesIO(z)) as zf:
        names = zf.namelist()
    assert any(n.endswith("export.xml") for n in names)
    assert any("apple_health_export/" in n for n in names)


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_import_endpoint_creates_observations(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    user_id = await make_user()
    token = make_token(str(user_id))

    resp = await client.post(
        "/ingestion/apple-health/import",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("export.zip", build_export_zip(), "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    result = resp.json()
    assert result["entity_count"] == SAMPLE_RECORD_COUNT
