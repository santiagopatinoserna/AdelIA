"""Genomics persistence: upload stores matches; GET returns them."""
from pathlib import Path

import pytest

from adelia.config import settings
from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE
from tests.test_auth import make_token

FIXTURE = Path(__file__).parent / "fixtures" / "genomics_sample.txt"


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_upload_persists_and_get_returns_saved(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    user_id = await make_user()
    token = make_token(str(user_id))
    headers = {"Authorization": f"Bearer {token}"}

    with FIXTURE.open("rb") as f:
        up = await client.post(
            "/enrichment/genomics/upload",
            headers=headers,
            files={"file": ("genome.txt", f.read(), "text/plain")},
        )
    assert up.status_code == 200
    uploaded = up.json()
    assert uploaded, "fixture should match variants"

    saved = await client.get("/enrichment/genomics", headers=headers)
    assert saved.status_code == 200
    body = saved.json()
    assert body["analyzed_at"] is not None
    assert {v["rsid"] for v in body["variants"]} == {v["rsid"] for v in uploaded}

    # re-upload replaces, not duplicates
    with FIXTURE.open("rb") as f:
        await client.post(
            "/enrichment/genomics/upload",
            headers=headers,
            files={"file": ("genome.txt", f.read(), "text/plain")},
        )
    saved2 = await client.get("/enrichment/genomics", headers=headers)
    assert len(saved2.json()["variants"]) == len(uploaded)
