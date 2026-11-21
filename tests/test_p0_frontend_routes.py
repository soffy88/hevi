"""P0 前端路: Publish Studio 挂载 + 三处路径错 + /api/files 代理的路由级回归。

覆盖:
  - 8 条 /api/studio/* 接口挂载 (404 → 200/403, clone 恒 403)
  - /api/production/backlot/{task_id} 挂载 (v1 production_tools)
  - /api/files 代理 (401/403/404/200, token 鉴权 + 产物根约束)
  - /api/mpt/material/search 单数存在、复数不存在; /api/backlot/runs/{id}/status
    存在 (前端曾拼成 /api/backlog/…, 已改前端)

Run: .venv/bin/python -m pytest tests/test_p0_frontend_routes.py -q
(走 tests/conftest.py, 其 JWT_SECRET=dummy。)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.auth.dependencies import get_current_user
from hevi.core.config import settings

_client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _fake_auth():
    # 仓内既有模式 (tests/test_backlot_api.py): 伪造登录用户, 绕开
    # get_current_user → pg 连接 (测试环境无库, 否则依赖先 500)。
    app.dependency_overrides[get_current_user] = lambda: {"id": "test-user"}
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    return _client


@pytest.fixture(scope="module")
def token():
    from hevi.auth.jwt_handler import sign_access_token

    return sign_access_token("p0-test-user")


# --- 1. Publish Studio 8 接口挂载 ---

STUDIO_PATHS = [
    "/api/studio/motion/templates",
    "/api/studio/motion/render",
    "/api/studio/html-video/templates",
    "/api/studio/html-video/render",
    "/api/studio/voice/clone",
    "/api/studio/voice/dub",
    "/api/studio/dance/gpu-check",
    "/api/studio/dance/generate",
]


def test_studio_paths_registered(client):
    paths = client.app.openapi()["paths"]
    for p in STUDIO_PATHS:
        assert p in paths, f"missing route: {p}"


def test_motion_templates_200(client):
    res = client.get("/api/studio/motion/templates")
    assert res.status_code == 200
    assert res.json()["total"] == 20


def test_html_video_templates_200(client):
    res = client.get("/api/studio/html-video/templates")
    assert res.status_code == 200
    assert res.json()["total"] == 21


def test_dance_gpu_check_200(client):
    res = client.get("/api/studio/dance/gpu-check")
    assert res.status_code == 200
    assert "available" in res.json()


def test_motion_render_unknown_template_200_error(client):
    res = client.post("/api/studio/motion/render", json={"template_id": "no-such-template"})
    assert res.status_code == 200
    assert res.json()["success"] is False


def test_html_video_render_empty_200_error(client):
    res = client.post("/api/studio/html-video/render", json={})
    assert res.status_code == 200
    assert res.json()["success"] is False


def test_voice_clone_always_403(client):
    # 合法体也必须 403: 克隆恒 fail, 绝不调用 clone_voice。
    res = client.post(
        "/api/studio/voice/clone",
        json={"reference_audio_path": "/tmp/ref.wav", "target_text": "你好"},
    )
    assert res.status_code == 403
    assert "disabled" in res.json()["detail"].lower()


def test_voice_clone_invalid_body_still_422(client):
    # 体校验仍在门之前: 缺必填字段 → 422, 不是 403。
    res = client.post("/api/studio/voice/clone", json={})
    assert res.status_code == 422


def test_voice_dub_missing_source_200_error(client):
    res = client.post(
        "/api/studio/voice/dub",
        json={"source_video_path": "/nonexistent/x.mp4", "target_language": "en"},
    )
    assert res.status_code == 200
    assert res.json()["success"] is False


def test_dance_generate_with_real_music_200(client, tmp_path):
    music = tmp_path / "music.mp3"
    music.write_bytes(b"\x00" * 100)
    out = tmp_path / "dance.mp4"
    res = client.post(
        "/api/studio/dance/generate",
        json={"music_path": str(music), "genre": "kpop", "duration": 10.0, "output_path": str(out)},
    )
    assert res.status_code == 200
    assert res.json()["success"] is True


# --- 2. 三处路径错 ---


def test_production_backlot_route_registered(client):
    assert "/api/production/backlot/{task_id}" in client.app.openapi()["paths"]


def test_production_backlot_mounted_not_404(client):
    # 无生产库时 handler 在取 pg 连接处失败 → 500; 有库时未知 task → 404。
    # 两种都证明路由已挂载 (未挂载是 404 且 detail 为 "Not Found")。
    res = client.get("/api/production/backlot/no-such-task")
    assert res.status_code in (404, 500)
    if res.status_code == 404:
        assert res.json()["detail"] != "Not Found"


def test_mpt_material_search_singular_only(client):
    paths = client.app.openapi()["paths"]
    assert "/api/mpt/material/search" in paths
    assert "/api/mpt/materials/search" not in paths
    # 已登录调单数路由: 测试环境无 MPT 后端, 客户端依赖失败 → 500,
    # 或就绪探针失败 → 503; 两种都证明路由已匹配 (未挂载是 404)。
    res = client.post(
        "/api/mpt/material/search",
        json={"query": "cat", "source": "pexels", "count": 3, "min_duration": 5},
    )
    assert res.status_code in (500, 503)


def test_backlot_runs_status_route(client, tmp_path, monkeypatch):
    paths = client.app.openapi()["paths"]
    assert "/api/backlot/runs/{run_id}/status" in paths
    assert "/api/backlog/runs/{run_id}/status" not in paths
    monkeypatch.setattr(settings, "backlot_dir", str(tmp_path))
    res = client.get("/api/backlot/runs/p0-probe/status")
    assert res.status_code == 200
    assert res.json()["run_id"] == "p0-probe"


# --- 3. /api/files 代理 ---


def test_files_route_registered(client):
    assert "/api/files" in client.app.openapi()["paths"]


def test_files_no_token_401(client):
    res = client.get("/api/files", params={"path": "/etc/passwd"})
    assert res.status_code == 401


def test_files_bad_token_401(client):
    res = client.get("/api/files", params={"path": "/etc/passwd", "token": "bogus"})
    assert res.status_code == 401


def test_files_missing_file_404(client, token):
    res = client.get(
        "/api/files",
        params={"path": str(Path.cwd() / "output" / "definitely-not-here.mp4"), "token": token},
    )
    assert res.status_code == 404


def test_files_outside_roots_403(client, token, tmp_path):
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"\x00" * 10)
    res = client.get("/api/files", params={"path": str(outside), "token": token})
    assert res.status_code == 403


def test_files_serves_real_artifact_200(client, token):
    target = Path.cwd() / "output" / "dirstyle_e2e" / "fincher.mp4"
    assert target.exists(), "fixture artifact missing from checkout"
    res = client.get("/api/files", params={"path": str(target), "token": token})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("video/mp4")
    assert int(res.headers["content-length"]) == target.stat().st_size
