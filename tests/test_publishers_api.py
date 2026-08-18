"""B2 跨平台一键发布 —— API 端点测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.auth.dependencies import get_current_user

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fake_auth():
    app.dependency_overrides[get_current_user] = lambda: {"id": "test-user"}
    yield
    app.dependency_overrides.clear()


def test_list_publishers() -> None:
    resp = client.get("/api/publishers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 3
    platforms = {p["name"] for p in body["publishers"]}
    assert {"tiktok", "instagram", "youtube"} <= platforms
    stubs = [p for p in body["publishers"] if p["name"] in {"tiktok", "instagram", "youtube"}]
    assert stubs and all(p["available"] is False for p in stubs)
    assert "douyin" in platforms


def test_publish_stub_returns_skipped(tmp_path: Path) -> None:
    media = tmp_path / "out.mp4"
    media.write_bytes(b"fake")
    resp = client.post(
        "/api/publishers/tiktok/publish",
        json={"media_path": str(media), "title": "T", "tags": ["a"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "skipped"
    assert body["platform"] == "tiktok"
    assert "credentials" in body["reason"]


def test_publish_unknown_platform_returns_failed() -> None:
    resp = client.post(
        "/api/publishers/nope/publish",
        json={"media_path": "/tmp/x.mp4"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"
