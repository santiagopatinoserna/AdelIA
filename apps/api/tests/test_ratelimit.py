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


def test_identity_unverifiable_tokens_share_ip_bucket(monkeypatch):
    """Rotating junk Authorization values must NOT mint fresh buckets —
    that was a full limiter bypass. Garbage tokens collapse to the IP."""
    from adelia.config import settings

    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    a = ratelimit.identity_from("Bearer junk1", "1.2.3.4")
    b = ratelimit.identity_from("Bearer junk2", "1.2.3.4")
    c = ratelimit.identity_from(None, "1.2.3.4")
    assert a == b == c == "ip:1.2.3.4"


def test_identity_valid_token_gets_user_bucket(monkeypatch):
    from adelia.config import settings
    from tests.test_auth import make_token

    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    token = make_token("22222222-2222-2222-2222-222222222222")
    ident = ratelimit.identity_from(f"Bearer {token}", "1.2.3.4")
    assert ident == "user:22222222-2222-2222-2222-222222222222"


async def test_middleware_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    ratelimit.reset()
    # public share endpoint: 60/min per IP — exhaust it fast
    for _ in range(60):
        await client.get("/s/some-token")
    response = await client.get("/s/some-token")
    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_shared_page_assets_have_their_own_bucket():
    """Every view of /s/{token} also fetches its stylesheet. Sharing the
    60/min token-enumeration bucket would halve the views a pediatrician gets
    and, once spent, serve the page bare. The asset is static and reveals
    nothing, so it takes a separate, roomier bucket."""
    ratelimit.reset()
    for _ in range(60):
        allowed, _ = ratelimit.check("GET", "/s/some-token", "ip:9.9.9.9", now=3000.0)
        assert allowed
    allowed, _ = ratelimit.check("GET", "/s/some-token", "ip:9.9.9.9", now=3000.0)
    assert not allowed
    allowed, _ = ratelimit.check(
        "GET", "/s/_assets/briefing.css", "ip:9.9.9.9", now=3000.0
    )
    assert allowed


# --- Who the client is (review of PR #57, 2026-11-06) ---------------------------
#
# The API ran `uvicorn --proxy-headers --forwarded-allow-ips=*`, which makes
# request.client the FIRST X-Forwarded-For entry, a value the client writes. A
# bot sending a new one per request got a fresh bucket every time, on every
# per-address limit (guest creation, the demo, anonymous traffic). Production
# traffic arrives through the Cloudflare tunnel, and Cloudflare overwrites
# CF-Connecting-IP with the real address on every request, so that header is
# the one worth trusting, and only where the operator says Cloudflare is in
# front (TRUST_CF_CONNECTING_IP). Everything else uses the connection's peer.

import shlex  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from starlette.requests import Request  # noqa: E402

PEER = "172.18.0.5"  # the container or tunnel the request arrived from


def _request(headers: dict[str, str], peer: str = PEER) -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/", "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 40000),
    })


def test_a_forged_forwarded_for_is_not_the_client():
    assert ratelimit.client_ip(_request({"X-Forwarded-For": "6.6.6.6"})) == PEER


def test_cf_connecting_ip_is_the_client_when_cloudflare_is_trusted(monkeypatch):
    monkeypatch.setattr(settings, "trust_cf_connecting_ip", True)
    request = _request({"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": "6.6.6.6"})
    assert ratelimit.client_ip(request) == "203.0.113.7"


def test_cf_connecting_ip_is_ignored_without_the_setting(monkeypatch):
    """Off by default: an install with no Cloudflare in front would otherwise
    let any client pick its own bucket with that header."""
    monkeypatch.setattr(settings, "trust_cf_connecting_ip", False)
    assert ratelimit.client_ip(_request({"CF-Connecting-IP": "203.0.113.7"})) == PEER


def test_a_malformed_cf_connecting_ip_falls_back_to_the_peer(monkeypatch):
    monkeypatch.setattr(settings, "trust_cf_connecting_ip", True)
    assert ratelimit.client_ip(_request({"CF-Connecting-IP": "not-an-ip"})) == PEER


def _production_uvicorn_app(monkeypatch):
    """The API as the Dockerfile serves it: main.app behind whatever proxy-header
    handling the CMD's uvicorn flags switch on, parsed by uvicorn itself."""
    import uvicorn
    from uvicorn.main import main as uvicorn_cli

    from adelia.main import app

    cmd = next(line for line in (Path(__file__).parents[1] / "Dockerfile").read_text().splitlines()
               if line.startswith("CMD ") and "uvicorn adelia.main:app" in line)
    args = shlex.split(cmd.split("uvicorn adelia.main:app", 1)[1].split('"]', 1)[0])
    params = uvicorn_cli.make_context("uvicorn", ["adelia.main:app", *args]).params
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    config = uvicorn.Config(app, proxy_headers=params["proxy_headers"],
                            forwarded_allow_ips=params["forwarded_allow_ips"],
                            log_config=None, ws="none")
    config.load()
    return config.loaded_app


async def _codes(asgi_app, header_sets: list[dict[str, str]]) -> list[int]:
    transport = httpx.ASGITransport(app=asgi_app, client=(PEER, 40000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        return [(await ac.get("/no-such-route", headers=h)).status_code for h in header_sets]


@pytest.fixture
def _two_per_minute(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(ratelimit, "ROUTE_BUDGETS",
                        [("GET", "/no-such-route", 2), *ratelimit.ROUTE_BUDGETS])
    ratelimit.reset()


@pytest.mark.usefixtures("_two_per_minute")
async def test_a_new_forwarded_for_per_request_does_not_mint_a_bucket(monkeypatch):
    app = _production_uvicorn_app(monkeypatch)
    forged = [{"X-Forwarded-For": f"10.0.0.{i}"} for i in range(3)]
    assert await _codes(app, forged) == [404, 404, 429]


@pytest.mark.usefixtures("_two_per_minute")
async def test_each_cloudflare_visitor_has_her_own_bucket(monkeypatch):
    monkeypatch.setattr(settings, "trust_cf_connecting_ip", True)
    app = _production_uvicorn_app(monkeypatch)
    a, b = {"CF-Connecting-IP": "203.0.113.7"}, {"CF-Connecting-IP": "198.51.100.9"}
    assert await _codes(app, [a, a, a, b]) == [404, 404, 429, 404]


@pytest.mark.usefixtures("_two_per_minute")
async def test_without_the_setting_cf_connecting_ip_does_not_mint_a_bucket(monkeypatch):
    monkeypatch.setattr(settings, "trust_cf_connecting_ip", False)
    app = _production_uvicorn_app(monkeypatch)
    forged = [{"CF-Connecting-IP": f"203.0.113.{i}"} for i in range(3)]
    assert await _codes(app, forged) == [404, 404, 429]


def test_production_trusts_cloudflare_for_the_client_address():
    """Production sits behind the Cloudflare tunnel; compose hands the api only
    the variables it lists, so without this line every visitor would share the
    tunnel's bucket there. Off in config.py for installs without Cloudflare."""
    compose = Path(__file__).resolve().parents[3] / "infra" / "docker-compose.prod.yml"
    text = compose.read_text(encoding="utf-8")
    assert "TRUST_CF_CONNECTING_IP: ${TRUST_CF_CONNECTING_IP:-true}" in text
    assert type(settings).model_fields["trust_cf_connecting_ip"].default is False
