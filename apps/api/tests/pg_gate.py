"""Env-driven gate for Postgres-backed integration tests.

PG_AVAILABLE resolves once at import:
- explicit override via env var PG_AVAILABLE=1/0,
- otherwise a quick TCP probe against the configured Postgres host/port.

Usage:
    from tests.pg_gate import PG_AVAILABLE

    @pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
"""

import os
import socket

from adelia.config import settings


def _pg_reachable() -> bool:
    override = os.environ.get("PG_AVAILABLE")
    if override is not None:
        return override == "1"
    try:
        with socket.create_connection(
            (settings.postgres_host, settings.postgres_port), timeout=0.5
        ):
            return True
    except OSError:
        return False


PG_AVAILABLE = _pg_reachable()
