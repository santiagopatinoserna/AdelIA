"""In-process fixed-window rate limiter.

Single-instance v0.1.1 scope — per-replica budgets (a multi-replica deploy
moves this to Redis). Identity is the VALIDATED JWT sub when the request
carries a verifiable token, else the client IP.

Budgets are per (route-group, identity) per minute. 429 + Retry-After on
exhaustion. Memory is hard-capped at MAX_KEYS with oldest-window eviction.
"""

from __future__ import annotations

import heapq
import ipaddress
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request

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
    # Public and unauthenticated: one embedding plus one generation per call,
    # bought with nobody's consent. The REAL brake is the hard daily ceiling
    # in routers/demo (a Postgres counter, so it survives a restart); this is
    # only the burst brake.
    #
    # It is deliberately not tighter, because the bucket may not be one
    # visitor. Depending on the reverse proxy, /api/demo/ask either reaches
    # the API directly (bucket = the visitor's IP) or through the Next route
    # handler (bucket = the web container, i.e. ONE bucket for the whole
    # internet). A value tuned for the first case makes the demo unusable in
    # the second, which is the shape of outage nobody would notice until a
    # launch day.
    ("POST", "/demo", 20),
    ("GET", "/demo", 600),           # the fixture: no spend, page-view rate
    # Guest accounts (routers/guest.py, 2026-11-06). Saving and adopting are
    # one click each; "/guest/" comes first so they do not spend the brake on
    # creation below. Creation is public and anti-bot only: a guest spends
    # nothing at birth (no model call), so this caps identities per address,
    # not money. The hourly ceiling lives in the router (GUEST_SIGNUPS_PER_HOUR).
    ("POST", "/guest/", 20),
    ("POST", "/guest", 5),
    ("POST", "/documents", 10),      # upload + OCR pipeline
    ("POST", "/briefings", 6),       # 5-stage LLM pipeline
    ("POST", "/enrichment/genomics", 5),
    ("POST", "/shares", 20),
    # The shared page's stylesheet: static, reveals nothing, fetched on every
    # view. Before "/s/" (first match wins) so it does not spend the token
    # brake, nor go bare once a busy clinic has spent it.
    ("GET", "/s/_assets/", 600),
    ("GET", "/s/", 60),              # public links — token enumeration brake
    # One upsert per call and no identity attached, so the only thing to
    # protect is the write rate itself (audit 4.8). Same caveat as /demo: the
    # bucket may be the whole internet, and a counter that starts 429ing
    # under normal traffic is worse than no counter, because it under-reports
    # silently and exactly when the numbers matter.
    ("POST", "/funnel", 600),
    # Consented journeys (services/analytics). A browser sends one batch every
    # few seconds at most and one per page it leaves, so 120 a minute is far
    # above a person and well below a script filling the table. The Next
    # route (app/api/analytics) forwards CF-Connecting-IP, so behind
    # Cloudflare the bucket is the visitor whichever proxy carries it.
    ("POST", "/analytics/", 120),
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


def client_ip(request: Request) -> str:
    """The one place that decides whose address a request counts against.

    Every per-address limit asks here (the middleware, the hourly brake on
    guests, the briefing charge in routers/agent). Until the PR #57 review the
    answer was request.client behind `uvicorn --forwarded-allow-ips=*`, i.e.
    the first X-Forwarded-For entry, which the client writes: one forged value
    per request was a fresh bucket each time, and the guests it minted spend
    the app's model budget. X-Forwarded-For is never read now (the Dockerfile
    runs uvicorn with --no-proxy-headers, so request.client is the peer).

    Behind the Cloudflare tunnel the peer is the tunnel or the web container,
    the same for everyone, while Cloudflare sets CF-Connecting-IP to the real
    address on each request, overwriting any the client sent. That header is
    the client only where the operator says Cloudflare is in front
    (TRUST_CF_CONNECTING_IP); a home LAN request skips Cloudflare and is
    trusted as it already is. A value that is not an address is ignored.
    """
    from adelia.config import settings

    if settings.trust_cf_connecting_ip:
        forwarded = (request.headers.get("cf-connecting-ip") or "").strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def identity_for(request: Request) -> str:
    """identity_from() for a live request: its bearer token, else client_ip()."""
    return identity_from(request.headers.get("authorization"), client_ip(request))


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


def check_window(
    group: str, identity: str, budget: int, window_seconds: float, now: float | None = None
) -> tuple[bool, float]:
    """One extra fixed window beside the per-minute ones, for a route that also
    needs a longer ceiling (guest creation per hour). Same store and cap."""
    now = now if now is not None else time.monotonic()
    key = (group, identity)
    window_start, count = _windows.get(key, (now, 0))
    if now - window_start >= window_seconds:
        window_start, count = now, 0
    if count >= budget:
        return False, max(0.0, window_seconds - (now - window_start))
    _windows[key] = (window_start, count + 1)
    return True, 0.0


def reset() -> None:
    """Test helper — drop all state."""
    _windows.clear()
