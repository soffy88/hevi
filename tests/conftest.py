from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from obase.persistence import PgPool

from hevi.api.main import app
from hevi.core.config import settings
from hevi.provider_policy.permission import resolver_from_settings


@pytest.fixture(autouse=True)
def enable_debug_mode():
    """Tests run as a dev environment: enable debug so dev-only paths
    (manual /credits/topup, OAuth test_code shortcut) are exercisable."""
    prev = settings.debug
    settings.debug = True
    yield
    settings.debug = prev


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


# P0-4.1 — the admission seam denies by default: an undeclared tenant is not a
# permitted tenant. Tests that drive run_task end to end are exercising cost,
# fallback or lifecycle behaviour, not permission, so they declare the scope they
# run under instead of the seam being relaxed. Deny-side coverage lives in
# tests/architecture/test_permission_authority.py.
TEST_TENANT_SCOPE = (
    # tenant|providers|targets|capabilities|operations|ceiling_usd
    # Providers are named explicitly; capability and target are left blank so they
    # do not become a second thing these tests could accidentally depend on.
    "test-tenant|ltx2_cloud,v,wan_local,wan_secret|||render,regenerate,qualification|"
    "1000000.0"
)


@pytest.fixture
def admission_scope():
    """A resolver admitting the fixture tenants, for tests that are not about
    permission. Returning the resolver rather than the raw string keeps the
    declaration in one place if the grammar ever changes."""
    return resolver_from_settings(TEST_TENANT_SCOPE)


@pytest.fixture
def configure_admission_scopes():
    """Declare the fixture tenant for tests that go through the HTTP API.

    The API path resolves its resolver from ``settings`` at service-construction
    time, so it cannot be handed an injected resolver the way a direct
    ``TaskService(...)`` test can. This fixture mutates the setting and restores
    it, rather than letting one test's declaration leak into the next.
    """
    previous = settings.admission_tenant_scopes
    settings.admission_tenant_scopes = TEST_TENANT_SCOPE
    yield
    settings.admission_tenant_scopes = previous
