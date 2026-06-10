"""Fixed-window rate limiter: unit + middleware integration."""

from adelia import ratelimit
from adelia.config import settings


def test_budget_exhaustion_and_window_reset():
    ratelimit.reset()
    identity = "user-x"
    # /chat budget is 20/min
    for _ in range(20):
        allowed, _ = ratelimit.check("POST", "/chat", identity, now=1000.0)
        assert allowed
    allowed, retry_after = ratelimit.check("POST", "/chat", identity, now=1000.0)
    assert not allowed
    assert 0 < retry_after <= 60
    # new window → allowed again
    allowed, _ = ratelimit.check("POST", "/chat", identity, now=1061.0)
    assert allowed


def test_identities_are_isolated():
    ratelimit.reset()
    for _ in range(20):
        ratelimit.check("POST", "/chat", "user-a", now=2000.0)
    allowed, _ = ratelimit.check("POST", "/chat", "user-b", now=2000.0)
    assert allowed


def test_identity_from_header_vs_ip():
    a = ratelimit.identity_from("Bearer tok1", "1.2.3.4")
    b = ratelimit.identity_from("Bearer tok2", "1.2.3.4")
    c = ratelimit.identity_from(None, "1.2.3.4")
    assert a != b
    assert c == "ip:1.2.3.4"


async def test_middleware_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    ratelimit.reset()
    # public share endpoint: 60/min per IP — exhaust it fast
    for _ in range(60):
        await client.get("/s/some-token")
    response = await client.get("/s/some-token")
    assert response.status_code == 429
    assert "Retry-After" in response.headers
