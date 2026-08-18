"""Veya 调 Hevi 成品合同。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.auth.dependencies import get_current_user
from hevi.studio.assets import reset_assets
from hevi.studio.daily import reset_daily
from hevi.studio.veya import produce, reset_veya

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_assets()
    reset_veya()
    reset_daily()
    app.dependency_overrides[get_current_user] = lambda: {"id": "test-user"}
    yield
    app.dependency_overrides.clear()
    reset_assets()
    reset_veya()
    reset_daily()


@pytest.mark.asyncio
async def test_produce_explainer_slate_only() -> None:
    job = await produce(line_id="explainer", slots={"topic": "盐税"})
    assert job.status == "scheduled"
    assert job.product == "解说中心"
    assert job.production_order["target"] == "explainer"
    assert job.artifact == ""


@pytest.mark.asyncio
async def test_produce_hyperframes_execute(tmp_path: Path) -> None:
    job = await produce(
        line_id="kinetic_promo",
        slots={"topic": "盐税"},
        execute=True,
        output_dir=tmp_path,
    )
    assert job.render_runtime == "hyperframes"
    assert job.status == "ready"
    assert job.artifact
    assert Path(job.artifact).exists()


def test_veya_http_and_daily_tick() -> None:
    caps = client.get("/api/studio/veya/capabilities")
    assert caps.status_code == 200
    ids = {item["id"] for item in caps.json()["lines"]}
    assert "explainer" in ids
    assert "history_scene" in ids
    assert "kinetic_promo" in ids

    produced = client.post(
        "/api/studio/veya/produce",
        json={"line_id": "explainer", "slots": {"topic": "盐税"}},
    )
    assert produced.status_code == 200
    body = produced.json()
    assert body["status"] == "scheduled"
    fetched = client.get(f"/api/studio/veya/jobs/{body['job_id']}")
    assert fetched.status_code == 200

    added = client.post(
        "/api/studio/daily/calendars/explainer-daily/topics",
        json={"topics": [{"title": "盐税日更", "scheduled_date": "2026-08-18"}]},
    )
    assert added.status_code == 200
    ticked = client.post(
        "/api/studio/daily/tick",
        json={"now": "2026-08-18", "calendar_id": "explainer-daily"},
    )
    assert ticked.status_code == 200
    assert ticked.json()["count"] == 1
