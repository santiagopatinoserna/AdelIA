import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    from adelia.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
async def _dispose_engine():
    """pytest-asyncio runs each test in its own event loop; pooled asyncpg
    connections are bound to the loop that created them. Dispose the pool
    after every test so the next loop starts clean."""
    yield
    from adelia.db import engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    """The suite hammers endpoints far past production budgets; the
    dedicated rate-limit test re-enables it explicitly."""
    from adelia import ratelimit
    from adelia.config import settings

    previous = settings.rate_limit_enabled
    settings.rate_limit_enabled = False
    ratelimit.reset()
    yield
    settings.rate_limit_enabled = previous


@pytest.fixture(autouse=True)
def _no_live_routing_classifier(request, monkeypatch):
    """The route node calls a model when its rules abstain, and since build
    step 2 the demo awaits that call on the request path. Without this, a run
    with a key in the environment (server-verify with VERIFY_LIVE=1) routes
    every ambiguous test question by whatever the provider answered that day.
    With it, the model layer fails fast and `route` falls back to `plan`, the
    same decision a key-less run makes.

    Exempt: tests marked `live_routing` (they measure the real provider) and
    modules marked `routing_model_layer` (they drive the model layer with
    their own fakes)."""
    if request.node.get_closest_marker("live_routing") or request.node.get_closest_marker(
        "routing_model_layer"
    ):
        return
    from adelia.agent import route as r

    async def _disabled(system, user, *, provider=None):
        raise RuntimeError("routing model disabled in tests")

    monkeypatch.setattr(r, "_complete_json", _disabled)
