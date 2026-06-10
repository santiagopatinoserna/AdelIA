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
