"""Test traffic, kept out of the numbers (2026-11-08).

The production smoke suite (apps/web/e2e-prod) and other agents' runs used to
show up as visits, guest signups, /r/ clicks and provider calls in the very
counters Santiago reads to decide what to do next. A request that carries
`X-AdelIA-QA: 1` is served exactly like any other and is only left out of:

* the anonymous funnel (services/funnel.bump_quietly, and the signups and
  activations it derives from users, through the guest's email below),
* the consented analytics (services/analytics: no batch, no consent proof),
* the clicks of the short links (/funnel/link/<code>),
* the usage counter (services/usage.count).

This is hygiene for the figures, not security. Anybody can send the header and
all it buys them is not being counted. It opens no route, skips no rate limit,
and the demo's daily spending ceiling still counts every ask (routers/demo).
Do not hang anything else on it.

The marker is a ContextVar set by a pure ASGI middleware for the length of
the request. asyncio copies the context into every task the request creates,
so the work it spawns (the guest's embedding fill, a document's pipeline)
is test traffic too.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

HEADER = "X-AdelIA-QA"
_HEADER_KEY = HEADER.lower().encode("latin-1")

# A guest created by test traffic gets this in front of her synthetic address
# (services/guest.guest_email). Signups and activations are derived from the
# users table at read time, so the row itself has to say it was a test; the
# address is already ours, in the reserved .invalid TLD, and no migration is
# needed. No real address can match: `.invalid` never receives mail.
GUEST_EMAIL_PREFIX = "qa-"
GUEST_EMAIL_LIKE = "qa-invitado-%@guest.adelia.invalid"

_qa: ContextVar[bool] = ContextVar("adelia_qa_traffic", default=False)


def is_qa() -> bool:
    """True inside a request that sent `X-AdelIA-QA: 1`, or under marked()."""
    return _qa.get()


@contextmanager
def marked() -> Iterator[None]:
    """Treat everything inside the block as test traffic."""
    token = _qa.set(True)
    try:
        yield
    finally:
        _qa.reset(token)


def counted_user(email_column):
    """SQL condition: this users row is not a guest created by test traffic."""
    return email_column.not_like(GUEST_EMAIL_LIKE)


class QATrafficMiddleware:
    """Marks the request when, and only when, the header's value is exactly "1".

    Pure ASGI rather than @app.middleware("http"), so the marker is set in the
    request's own context and reset when it ends: a keep-alive connection
    serves the next request in the same task.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        flagged = any(
            name == _HEADER_KEY and value.strip() == b"1"
            for name, value in scope.get("headers") or ()
        )
        if not flagged:
            await self.app(scope, receive, send)
            return
        with marked():
            await self.app(scope, receive, send)
