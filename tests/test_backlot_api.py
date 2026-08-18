"""B7 活态制片状态板后端 —— API 端点测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.auth.dependencies import get_current_user
from hevi.backlot import EVENT_STAGE_DONE, EVENT_STAGE_START
from hevi.core.config import settings

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fake_auth():
    app.dependency_overrides[get_current_user] = lambda: {"id": "test-user"}
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def iso_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "backlot_dir", str(tmp_path))
    return tmp_path


def test_emit_and_read_events(iso_dir: Path) -> None:
    r1 = client.post(
        "/api/backlot/runs/run-9/events",
        json={"stage": "script", "event_type": EVENT_STAGE_START},
    )
    assert r1.status_code == 200
    assert r1.json()["ok"] is True
    client.post(
        "/api/backlot/runs/run-9/events",
        json={"stage": "script", "event_type": EVENT_STAGE_DONE},
    )
    r2 = client.get("/api/backlot/runs/run-9/events")
    assert r2.status_code == 200
    body = r2.json()
    assert body["total"] == 2
    assert [e["event_type"] for e in body["events"]] == [EVENT_STAGE_START, EVENT_STAGE_DONE]


def test_status_summary(iso_dir: Path) -> None:
    client.post(
        "/api/backlot/runs/run-9/events",
        json={"stage": "script", "event_type": EVENT_STAGE_START},
    )
    client.post(
        "/api/backlot/runs/run-9/events",
        json={"stage": "script", "event_type": EVENT_STAGE_DONE},
    )
    client.post(
        "/api/backlot/runs/run-9/events",
        json={"stage": "cost", "event_type": "cost", "payload": {"usd": 0.5}},
    )
    resp = client.get("/api/backlot/runs/run-9/status")
    assert resp.status_code == 200
    st = resp.json()
    assert st["event_count"] == 3
    assert st["stages"] == {"script": EVENT_STAGE_DONE}
    assert st["cost_usd"] == 0.5
    assert st["failed"] is False


def test_status_empty_run(iso_dir: Path) -> None:
    resp = client.get("/api/backlot/runs/ghost/status")
    assert resp.status_code == 200
    assert resp.json()["event_count"] == 0


def test_events_limit_clamped(iso_dir: Path) -> None:
    for i in range(5):
        client.post(
            "/api/backlot/runs/run-9/events",
            json={"stage": "s", "event_type": "note", "payload": {"i": i}},
        )
    resp = client.get("/api/backlot/runs/run-9/events", params={"limit": 2})
    assert resp.json()["total"] == 2
    resp = client.get("/api/backlot/runs/run-9/events", params={"limit": 99999})
    assert resp.json()["total"] == 5
