"""Connection-pool discipline: the upload endpoint and the processing
pipeline must not hold a pooled connection across slow S3/LLM I/O."""
import asyncio
from uuid import uuid4

import pytest

from adelia.config import settings
from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE
from tests.test_auth import make_token


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
async def test_concurrent_uploads_do_not_exhaust_pool(client, monkeypatch):
    """N concurrent uploads (N > pool size) must all succeed: the endpoint
    holds a DB connection only for the short INSERT, not the S3 put."""
    monkeypatch.setattr(settings, "auth_secret", "test-secret")

    async def _noop_process(*args, **kwargs):
        return None

    # Don't run the real pipeline — this test is about the endpoint's
    # connection discipline, not OCR.
    monkeypatch.setattr("adelia.routers.documents.process_document", _noop_process)

    user_id = await make_user()
    token = make_token(str(user_id))
    headers = {"Authorization": f"Bearer {token}"}
    pdf = (b"%PDF-1.4 minimal", "application/pdf")

    concurrency = settings.db_pool_size + settings.db_max_overflow + 10

    async def upload():
        return await client.post(
            "/documents",
            headers=headers,
            files={"file": ("x.pdf", pdf[0], pdf[1])},
        )

    results = await asyncio.gather(*[upload() for _ in range(concurrency)])
    codes = [r.status_code for r in results]
    assert all(c == 201 for c in codes), f"non-201s: {[c for c in codes if c != 201]}"
