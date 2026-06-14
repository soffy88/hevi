from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from obase.persistence import PgPool

from hevi.api.main import app


@pytest.fixture(autouse=True)
def clear_pool_registry():
    """Clear PgPool registry between tests to avoid loop conflicts."""
    PgPool.clear()
    yield
    PgPool.clear()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
