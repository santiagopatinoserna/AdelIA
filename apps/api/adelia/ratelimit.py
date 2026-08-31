"""In-process fixed-window rate limiter.

Single-instance v0.1.1 scope — per-replica budgets (a multi-replica deploy
moves this to Redis). Identity is the VALIDATED JWT sub when the request
carries a verifiable token, else the client IP.

Budgets are per (route-group, identity) per minute. 429 + Retry-After on
exhaustion. Memory is hard-capped at MAX_KEYS with oldest-window eviction.
"""

from __future__ import annotations

import heapq
import time

# route-prefix → requests/minute. First match wins; order matters.
ROUTE_BUDGETS: list[tuple[str, str, int]] = [
    # (method, path-prefix, per-minute budget)
    ("POST", "/chat", 20),           # LLM cost
    # Half of /chat's: one turn is up to MAX_STEPS model calls, each of which
    # can run a whole RAG answer through `buscar_en_expediente`, so a turn is
    # up to ~10 provider calls where a /chat request is one. A confirm that
    # triggers generar_briefing additionally charges the "POST /briefings"
    # bucket below (routers/agent.post_turn), or the 6/min of the 5-stage
    # pipeline would be bypassable by entering through /agent.
    ("POST", "/agent", 10),
    ("POST", "/documents", 10),      # upload + OCR pipeline
    ("POST", "/briefings", 6),       # 5-stage LLM pipeline
    ("POST", "/enrichment/genomics", 5),
    ("POST", "/shares", 20),
    ("GET", "/s/", 60),              # public links — token enumeration brake
]
DEFAULT_BUDGET = 240  # everything else, per identity

WINDOW_SECONDS = 60.0
MAX_KEYS = 20_000  # hard ceiling — evict oldest windows past this, expired or not

_windows: dict[tuple[str, str], tuple[float, int]] = {}


def _budget_for(method: str, path: str) -> tuple[str, int]:
    for m, prefix, budget in ROUTE_BUDGETS:
        if method == m and path.startswith(prefix):
            return f"{m} {prefix}", budget
    return "default", DEFAULT_BUDGET


def identity_from(auth_header: str | None, client_ip: str) -> str:
    """Identity = VALIDATED JWT sub, else client IP.

    Hashing the raw header was bypassable: rotate a junk Authorization
    value per request → fresh bucket every time, unlimited rate on the
    public share endpoint included. An unverifiable header now falls into
    the caller's IP bucket like any anonymous client.
    """
    if auth_header and auth_header.lower().startswith("bearer "):
        try:
            from adelia.auth import decode_session_token

            payload = decode_session_token(auth_header[7:])
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:  # noqa: BLE001 — invalid/forged token → IP bucket
            pass
    return f"ip:{client_ip}"


def check(method: str, path: str, identity: str, now: float | None = None) -> tuple[bool, float]:
    """Returns (allowed, retry_after_seconds)."""
    now = now if now is not None else time.monotonic()
    group, budget = _budget_for(method, path)
    key = (group, identity)

    window_start, count = _windows.get(key, (now, 0))
    if now - window_start >= WINDOW_SECONDS:
        window_start, count = now, 0

    if count >= budget:
        return False, max(0.0, WINDOW_SECONDS - (now - window_start))

    _windows[key] = (window_start, count + 1)

    # Hard ceiling: under an identity flood every window is still live, so
    # expiry-only pruning frees nothing. Evict the oldest windows outright.
    if len(_windows) > MAX_KEYS:
        cutoff = now - WINDOW_SECONDS
        expired = [k for k, (start, _) in _windows.items() if start < cutoff]
        for k in expired:
            del _windows[k]
        overflow = len(_windows) - MAX_KEYS
        if overflow > 0:
            for k in heapq.nsmallest(
                overflow, _windows, key=lambda k: _windows[k][0]
            ):
                del _windows[k]

    return True, 0.0


def reset() -> None:
    """Test helper — drop all state."""
    _windows.clear()
