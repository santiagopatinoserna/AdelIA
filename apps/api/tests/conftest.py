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
