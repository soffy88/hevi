import httpx
import pytest

from hevi.api.main import app
from hevi.api.routers import studio_v2
from hevi.auth.dependencies import get_current_user
from hevi.production_graph import ProductionGraphRepository


@pytest.mark.asyncio
async def test_studio_v2_project_and_source_are_canonical_revision_writes() -> None:
    repo = ProductionGraphRepository()
    user = {"id": "api-user", "is_active": True}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[studio_v2.get_graph_repository] = lambda: repo
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/studio/projects",
                json={"title": "API canonical project", "creative_brief": "one sentence"},
            )
            assert response.status_code == 201
            project = response.json()
            project_id = project["project"]["id"]
            assert project["revision"]["revision_no"] == 1

            source = await client.post(
                f"/api/studio/projects/{project_id}/sources",
                json={"title": "public domain source", "content": "A beginning."},
            )
            assert source.status_code == 201
            assert source.json()["revision"]["revision_no"] == 2

            loaded = await client.get(f"/api/studio/projects/{project_id}")
            assert loaded.status_code == 200
            assert len(loaded.json()["sources"]) == 1
    finally:
        app.dependency_overrides.clear()
