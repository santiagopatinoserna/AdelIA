"""In-process fixed-window rate limiter.

Single-instance v0.1.1 scope — per-replica budgets (a multi-replica deploy
moves this to Redis). Identity is a hash of the Authorization header when
present (≈ per user, no JWT decode on the hot path), else the client IP.

Budgets are per (route-group, identity) per minute. 429 + Retry-After on
exhaustion. Memory is bounded by pruning expired windows on each hit.
"""

from __future__ import annotations

import hashlib
import time

# route-prefix → requests/minute. First match wins; order matters.
ROUTE_BUDGETS: list[tuple[str, str, int]] = [
    # (method, path-prefix, per-minute budget)
    ("POST", "/chat", 20),           # LLM cost
    ("POST", "/documents", 10),      # upload + OCR pipeline
    ("POST", "/briefings", 6),       # 5-stage LLM pipeline
    ("POST", "/enrichment/genomics", 5),
    ("POST", "/shares", 20),
    ("GET", "/s/", 60),              # public links — token enumeration brake
]
DEFAULT_BUDGET = 240  # everything else, per identity

WINDOW_SECONDS = 60.0

_windows: dict[tuple[str, str], tuple[float, int]] = {}


def _budget_for(method: str, path: str) -> tuple[str, int]:
    for m, prefix, budget in ROUTE_BUDGETS:
        if method == m and path.startswith(prefix):
            return f"{m} {prefix}", budget
    return "default", DEFAULT_BUDGET


def identity_from(auth_header: str | None, client_ip: str) -> str:
    if auth_header:
        return hashlib.sha256(auth_header.encode()).hexdigest()[:16]
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

    # Opportunistic prune so the dict doesn't grow unbounded.
    if len(_windows) > 10_000:
        cutoff = now - WINDOW_SECONDS
        for k in [k for k, (start, _) in _windows.items() if start < cutoff]:
            del _windows[k]

    return True, 0.0


def reset() -> None:
    """Test helper — drop all state."""
    _windows.clear()
