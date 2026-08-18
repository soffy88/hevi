"""制片厂 HTTP 入口。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.auth.dependencies import get_current_user
from hevi.studio.assets import reset_assets

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fake_auth() -> None:
    reset_assets()
    app.dependency_overrides[get_current_user] = lambda: {"id": "test-user"}
    yield
    app.dependency_overrides.clear()
    reset_assets()


def test_list_tools_and_lines() -> None:
    tools = client.get("/api/studio/tools")
    assert tools.status_code == 200
    assert tools.json()["total"] >= 10
    lines = client.get("/api/studio/lines")
    assert lines.status_code == 200
    ids = {item["id"] for item in lines.json()["lines"]}
    assert "history_scene" in ids
    assert "director_pipeline" in ids
    one = client.get("/api/studio/lines/explainer")
    assert one.status_code == 200
    assert one.json()["handoff"] == "explainer"


def test_create_slate_and_invoke_tool() -> None:
    scored = client.post("/api/studio/tools/score.provider", json={"payload": {}})
    assert scored.status_code == 200
    assert scored.json()["status"] == "ok"

    missing = client.post("/api/studio/tools/nope", json={"payload": {}})
    assert missing.status_code == 404

    slate = client.post(
        "/api/studio/slates",
        json={"line_id": "explainer", "slots": {"topic": "盐税"}},
    )
    assert slate.status_code == 200
    body = slate.json()
    assert body["status"] == "scheduled"
    assert body["production_order"]["target"] == "explainer"

    blocked = client.post(
        "/api/studio/slates",
        json={"line_id": "history_scene", "slots": {}},
    )
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"


def test_timeline_create_patch_split() -> None:
    created = client.post(
        "/api/studio/timelines",
        json={
            "title": "盐税",
            "edit_plan": {
                "cuts": [
                    {"start_s": 0, "duration_s": 6, "text": "钩子"},
                    {"start_s": 6, "duration_s": 4, "text": "展开"},
                ]
            },
        },
    )
    assert created.status_code == 200
    body = created.json()
    tid = body["timeline_id"]
    assert len(body["tracks"]["video"]) == 2

    patched = client.patch(
        f"/api/studio/timelines/{tid}",
        json={"clip_id": "v0", "action": "drop"},
    )
    assert patched.status_code == 200
    assert next(c["action"] for c in patched.json()["clips"] if c["clip_id"] == "v0") == "drop"

    split = client.patch(
        f"/api/studio/timelines/{tid}",
        json={"split_at_s": 8.0},
    )
    assert split.status_code == 200
    assert len(split.json()["tracks"]["video"]) >= 2

    packed = client.patch(
        f"/api/studio/timelines/{tid}",
        json={"ripple": True},
    )
    assert packed.status_code == 200
    kept = sorted(
        (c for c in packed.json()["tracks"]["video"] if c["action"] != "drop"),
        key=lambda c: c["start_s"],
    )
    assert kept and kept[0]["start_s"] == 0

    exported = client.post(f"/api/studio/timelines/{tid}/export", json={})
    assert exported.status_code == 200
    assert exported.json()["status"] in {"ok", "failed"}
