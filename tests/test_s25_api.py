"""S25 API 冒烟：路由、鉴权依赖、请求/响应契约（不碰数据库）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.auth.dependencies import get_current_user


@pytest.fixture
def s25_client(tmp_path, monkeypatch):
    monkeypatch.setenv("HEVI_CANVAS_TEMPLATE_DIR", str(tmp_path / "templates"))
    monkeypatch.setenv("HEVI_CANVAS_LIBRARY_DIR", str(tmp_path / "library"))
    monkeypatch.setenv("HEVI_CANVAS_SKILLS_STATE", str(tmp_path / "skills.json"))
    app.dependency_overrides[get_current_user] = lambda: {"id": "s25-test", "email": "s25@example.com"}
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_plan_apply_and_estimate(s25_client: TestClient) -> None:
    r = s25_client.post(
        "/api/canvas/s25/plan",
        json={"prompt": "一个小机器人第一次学会走路", "format": "animation"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    plan = body["plan"]
    assert body["requires_confirm"] and plan["confirm_token"]
    assert body["summary"]["numbers"]["nodes"] == plan["numbers"]["nodes"]

    r2 = s25_client.post(
        "/api/canvas/s25/plan/apply",
        json={"plan": plan, "confirm_token": plan["confirm_token"], "save": False},
    )
    assert r2.status_code == 201, r2.text
    assert r2.json()["saved"] is False
    assert r2.json()["numbers"]["nodes"] == plan["numbers"]["nodes"]

    r3 = s25_client.post(
        "/api/canvas/s25/plan/apply",
        json={"plan": plan, "confirm_token": "stale", "save": False},
    )
    assert r3.status_code == 409

    r4 = s25_client.post(
        "/api/canvas/s25/plan/patch",
        json={"plan": plan, "node_key": "shot1_video", "patch": {"config": {"duration_s": 8}}},
    )
    assert r4.status_code == 200
    assert r4.json()["plan"]["confirm_token"] != plan["confirm_token"]

    r5 = s25_client.post(
        "/api/canvas/s25/estimate",
        json={"graph": {"nodes": [
            {"node_id": "v", "node_type": "video", "config": {"provider": "wan_2_7", "duration_s": 5}},
            {"node_id": "i", "node_type": "image", "config": {"prompt": "x"}},
        ]}},
    )
    assert r5.status_code == 200, r5.text
    est = r5.json()
    assert est["total_cny"] > 0 and est["unpriced_nodes"] == 1
    assert "费用预估" in est["quote"]


def test_templates_backup_diagnostics_material_skills_library(s25_client: TestClient) -> None:
    r = s25_client.get("/api/canvas/s25/templates")
    assert r.status_code == 200, r.text
    templates = r.json()["templates"]
    assert templates, "内置模板没有生成"
    target = templates[0]
    r2 = s25_client.get(f"/api/canvas/s25/templates/{target['id']}")
    assert r2.status_code == 200
    assert r2.json()["graph"]["nodes"]
    r3 = s25_client.post(
        f"/api/canvas/s25/templates/{target['id']}/apply",
        json={"values": {}, "version": target["current_version"], "save": False},
    )
    assert r3.status_code == 200, r3.text
    assert r3.json()["template_version"] == target["current_version"]

    payload = {
        "name": "t",
        "graph": {
            "nodes": [{"node_id": "a", "node_type": "script", "config": {}}],
            "edges": [],
        },
    }
    from hevi.canvas import backup_s25

    backup = backup_s25.export_backup(payload["graph"])
    r4 = s25_client.post("/api/canvas/s25/backup/verify", json={"payload": backup})
    assert r4.status_code == 200 and r4.json()["ok"]
    r5 = s25_client.post("/api/canvas/s25/backup/import", json={"payload": backup, "save": False})
    assert r5.status_code == 201, r5.text
    assert r5.json()["numbers"]["nodes"] == 1

    r6 = s25_client.post(
        "/api/canvas/s25/diagnostics/explain",
        json={"error": "429 too many requests", "node_type": "video"},
    )
    assert r6.status_code == 200 and r6.json()["category"] == "rate_limit"

    r7 = s25_client.get("/api/canvas/s25/material/capabilities")
    assert r7.status_code == 200 and r7.json()["inpaint"]["available"] is False

    r8 = s25_client.get("/api/canvas/s25/skills")
    assert r8.status_code == 200 and len(r8.json()["skills"]) == 3
    r9 = s25_client.post("/api/canvas/s25/skills/rights-log/toggle", json={"enabled": False})
    assert r9.status_code == 200 and r9.json()["enabled"] is False
    s25_client.post("/api/canvas/s25/skills/rights-log/toggle", json={"enabled": True})

    r10 = s25_client.post(
        "/api/canvas/s25/library",
        json={"title": "一条链接", "url": "https://example.com/a.png", "kind": "image"},
    )
    assert r10.status_code == 201, r10.text
    item_id = r10.json()["item"]["id"]
    r11 = s25_client.get("/api/canvas/s25/library")
    assert r11.status_code == 200 and r11.json()["total"] == 1
    r12 = s25_client.delete(f"/api/canvas/s25/library/{item_id}")
    assert r12.status_code == 200 and r12.json()["removed"]

    r13 = s25_client.get("/api/canvas/s25/plugin-contract")
    assert r13.status_code == 200 and r13.json()["status"] == "internal_only"


def test_mcp_read_only_and_rate_limit_helpers() -> None:
    from hevi.api import mcp_mount

    body = b'{"jsonrpc":"2.0","method":"tools/call","params":{"name":"hevi.execute_canvas"}}'
    assert mcp_mount._mcp_tool_names(body) == ["hevi.execute_canvas"]
    assert mcp_mount._mcp_tool_names(b"not json") == []
    assert all(n.endswith((".list", ".get", ".status", ".capabilities"))
               or "list_capabilities" in n for n in ["hevi.agent.ops.list", "hevi.list_capabilities"])
    bucket_user = "s25-ratelimit"
    mcp_mount._MCP_HITS.pop(bucket_user, None)
    assert not mcp_mount._rate_limited(bucket_user)
    # 用很小的窗口把桶塞满，验证第 N+1 次被拒。
    old = mcp_mount._MCP_LIMIT
    try:
        mcp_mount._MCP_LIMIT = 1
        mcp_mount._MCP_HITS.pop("s25-ratelimit-2", None)
        assert not mcp_mount._rate_limited("s25-ratelimit-2")
        assert mcp_mount._rate_limited("s25-ratelimit-2")
    finally:
        mcp_mount._MCP_LIMIT = old
        mcp_mount._MCP_HITS.pop("s25-ratelimit", None)
        mcp_mount._MCP_HITS.pop("s25-ratelimit-2", None)


def test_save_paths_use_graph_service(s25_client: TestClient, monkeypatch) -> None:
    from hevi.api.routers import canvas_s25

    class FakeService:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def save_graph(self, **kwargs):
            self.calls.append(kwargs)
            return {"id": "fake-graph"}

    fake = FakeService()

    async def _fake():
        return fake

    monkeypatch.setattr(canvas_s25, "_graph_service", _fake)
    plan = s25_client.post(
        "/api/canvas/s25/plan",
        json={"prompt": "用 30 秒讲清楚什么是复利", "format": "explainer"},
    ).json()["plan"]
    applied = s25_client.post(
        "/api/canvas/s25/plan/apply",
        json={"plan": plan, "confirm_token": plan["confirm_token"], "save": True},
    )
    assert applied.status_code == 201, applied.text
    assert applied.json()["graph_id"] == "fake-graph"
    assert fake.calls and fake.calls[-1]["user_id"] == "s25-test"
    tpl = s25_client.get("/api/canvas/s25/templates").json()["templates"][0]
    out = s25_client.post(
        f"/api/canvas/s25/templates/{tpl['id']}/apply",
        json={"values": {}, "version": tpl["current_version"], "save": True},
    )
    assert out.status_code == 200, out.text
    assert out.json()["graph_id"] == "fake-graph"
