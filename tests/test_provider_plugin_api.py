"""B5 可编程供应商插件 —— API 端点测试。

覆盖 provider_presets.py 的:
  - GET /api/providers/plugins: 未配置目录降级 / 目录加载 / tool 过滤
  - GET /api/providers/plugins/{id}: 单插件详情(含评分) / 404
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.auth.dependencies import get_current_user
from hevi.core.config import settings

client = TestClient(app)

VALID_PLUGIN_YAML = """
providers:
  - id: test_plugin
    tool: video/shot
    kind: stock_video
    scores: {task_fit: 0.7, output_quality: 0.6, cost_efficiency: 0.9}
    meta: {endpoint: "https://example.com"}
  - id: test_tts
    tool: tts/narration
    kind: tts
    scores: {task_fit: 0.8, latency: 0.9}
"""


@pytest.fixture(autouse=True)
def _fake_auth():
    app.dependency_overrides[get_current_user] = lambda: {"id": "test-user"}
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def plugin_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "plugins.yaml").write_text(VALID_PLUGIN_YAML, encoding="utf-8")
    monkeypatch.setattr(settings, "provider_plugin_dir", str(tmp_path))
    return tmp_path


def test_plugins_disabled_when_dir_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "provider_plugin_dir", "")
    resp = client.get("/api/providers/plugins")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["plugins"] == []


def test_plugins_listed_from_dir(plugin_dir: Path) -> None:
    resp = client.get("/api/providers/plugins")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["total"] == 2
    ids = {p["id"] for p in body["plugins"]}
    assert ids == {"test_plugin", "test_tts"}


def test_plugins_filtered_by_tool(plugin_dir: Path) -> None:
    resp = client.get("/api/providers/plugins", params={"tool": "video/shot"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["plugins"][0]["id"] == "test_plugin"
    # tool 过滤时携带 A1 评分层加权分
    assert "weighted_score" in body["plugins"][0]


def test_plugin_detail_with_score(plugin_dir: Path) -> None:
    resp = client.get("/api/providers/plugins/test_plugin")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "test_plugin"
    assert body["kind"] == "stock_video"
    assert body["score"] is not None
    assert body["score"]["provider"] == "test_plugin"
    assert body["meta"]["endpoint"] == "https://example.com"


def test_plugin_detail_unknown_404(plugin_dir: Path) -> None:
    resp = client.get("/api/providers/plugins/nope")
    assert resp.status_code == 404
