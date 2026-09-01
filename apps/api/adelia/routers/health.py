"""Liveness (`/health`) and readiness (`/healthz`).

Two endpoints, on purpose, because they answer two different questions and
only one of them is worth waking somebody up for.

`/health` is the container probe: the process is up and serving. It stays
free of I/O so a slow database never restarts a healthy API, and it is the
one path the rate limiter and the access log skip (docker hits it every 10 s).

`/healthz` is the OUTSIDE question, and it is the one the audit found missing
(section 4, "Nada monitoriza adelia.godi.ai"): when the API died at 03:00 the
web container kept answering 200 on `/es`, so every naive check stayed green
while login, uploads, chat and briefings were dead. An endpoint that does not
reach the database cannot tell those two states apart, so this one goes all
the way to Postgres and reads the schema revision out of `alembic_version`:
one round trip that proves the pool, the credentials, the network and the
migrations at once, and hands the monitor the deployed version for free.

Public and unauthenticated by design (nginx maps `/healthz` to it, see
DEPLOY.md), so it says nothing an attacker could use: no host, no user, no
DSN, no exception message. A failure is reported as the exception CLASS name
("OSError", "TimeoutError"), because asyncpg puts the database user inside
the text of an authentication error.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Response, status

from adelia import __version__

router = APIRouter(prefix="", tags=["health"])
logger = logging.getLogger("adelia")

# A monitor that hangs is a monitor that never alerts. Past this the database
# counts as unreachable, whatever it is doing.
DB_CHECK_TIMEOUT_S = 5.0


@router.get("/health")
async def health():
    return {"status": "ok", "service": "adelia-api"}


async def _read_schema_revision() -> str | None:
    """Current alembic revision, read through the normal session factory.

    Deliberately the same pool the product uses: a check on a private
    connection would stay green through the pool exhaustion that actually
    takes the API down.
    """
    from adelia.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        return await session.scalar(
            sa.text("SELECT version_num FROM alembic_version LIMIT 1")
        )


@router.get("/healthz")
async def healthz(response: Response) -> dict[str, Any]:
    """Readiness, all the way through to Postgres.

    200 with `{"status": "ok"}` when the database answered; 503 with
    `{"status": "degraded"}` when it did not. Both bodies carry `version`, so
    a monitor can also see which build is live without a second call.
    """
    started = time.monotonic()
    database: dict[str, Any] = {"status": "ok"}
    ok = True
    try:
        revision = await asyncio.wait_for(_read_schema_revision(), DB_CHECK_TIMEOUT_S)
        database["schema_revision"] = revision
    except asyncio.TimeoutError:
        ok = False
        database = {"status": "down", "error": "TimeoutError"}
    except Exception as exc:  # noqa: BLE001 — the endpoint must answer, always
        ok = False
        # Class name only: never the message. asyncpg spells the database
        # user out inside InvalidPasswordError, and this endpoint is public.
        database = {"status": "down", "error": type(exc).__name__}
        logger.warning("healthz: database check failed (%s)", type(exc).__name__)
    database["latency_ms"] = round((time.monotonic() - started) * 1000, 1)

    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if ok else "degraded",
        "service": "adelia-api",
        "version": __version__,
        "checks": {"database": database},
    }
