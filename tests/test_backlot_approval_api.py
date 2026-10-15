"""Backlot 分镜联系表审批门 + REPLAY —— HTTP 端点测试。

走真端点(真 TestClient), 质量分来自真实成片的解码结果, 回放用真 ffmpeg。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.auth.dependencies import get_current_user
from hevi.core.config import settings

client = TestClient(app)

REAL_DIR = Path("artifacts/real_video/20261005T160434Z/artifacts")
BROLL = str(REAL_DIR.resolve() / "scene_broll_720p.mp4")
COLLINS = str(REAL_DIR.resolve() / "nasa-collins-0001_finecut.mp4")

pytestmark = pytest.mark.skipif(
    not Path(BROLL).is_file(), reason="real media fixture not present in this checkout"
)


@pytest.fixture(autouse=True)
def _fake_auth():
    app.dependency_overrides[get_current_user] = lambda: {"id": "test-user"}
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _iso_backlot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "backlot_dir", str(tmp_path))
    return tmp_path


def _upsert(scene_id: str, src: str, index: int, cost: float) -> dict:
    r = client.post(
        "/api/backlot/runs/run-api/shots",
        json={
            "scene_id": scene_id,
            "index": index,
            "title": f"scene {scene_id}",
            "prompt": "earth limb from orbit, slow push in",
            "source_path": src,
            "cost_usd": cost,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_upsert_measures_quality_and_thumbnail() -> None:
    body = _upsert("a", BROLL, 0, 0.4)["shot"]
    assert body["quality"]["score"] is not None
    assert body["quality"]["unmeasured"] == []
    assert body["thumbnail"].endswith(".png")


def test_contact_sheet_endpoint_returns_real_png() -> None:
    _upsert("a", BROLL, 0, 0.4)
    _upsert("b", COLLINS, 1, 0.2)
    r = client.get("/api/backlot/runs/run-api/contact-sheet")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["gate"] == "awaiting_review"
    assert body["sheet"] is not None
    assert Path(body["sheet"]["path"]).is_file()


def test_decision_writes_back_and_emits_an_event() -> None:
    _upsert("a", BROLL, 0, 0.4)
    r = client.post(
        "/api/backlot/runs/run-api/shots/a/decision",
        json={"decision": "approved", "reason": "运动达标", "reviewer": "omq"},
    )
    assert r.status_code == 200
    assert r.json()["shot"]["status"] == "approved"

    ev = client.get("/api/backlot/runs/run-api/events").json()["events"]
    assert any(e["event_type"] == "shot_decision" and e["payload"]["scene_id"] == "a" for e in ev)


def test_reject_without_reason_is_a_400() -> None:
    _upsert("a", BROLL, 0, 0.4)
    r = client.post(
        "/api/backlot/runs/run-api/shots/a/decision",
        json={"decision": "rejected", "reason": ""},
    )
    assert r.status_code == 400
    assert "理由" in r.json()["detail"]


def test_decision_on_unknown_scene_is_a_404() -> None:
    r = client.post(
        "/api/backlot/runs/run-api/shots/ghost/decision",
        json={"decision": "approved"},
    )
    assert r.status_code == 404


def test_replay_endpoint_and_render() -> None:
    _upsert("a", BROLL, 0, 0.4)
    _upsert("b", COLLINS, 1, 0.2)
    for sid in ("a", "b"):
        client.post(
            f"/api/backlot/runs/run-api/shots/{sid}/decision",
            json={"decision": "approved", "reason": "ok", "reviewer": "omq"},
        )
    rp = client.get("/api/backlot/runs/run-api/replay").json()
    assert rp["renderable"] is True
    shots = [s for s in rp["segments"] if s["kind"] == "shot"]
    assert [s["scene_id"] for s in shots] == ["a", "b"]
    assert shots[0]["duration_s"] == pytest.approx(14.0, abs=0.2)

    rr = client.post("/api/backlot/runs/run-api/replay/render")
    assert rr.status_code == 200
    render = rr.json()["render"]
    assert render["ok"] is True
    assert Path(render["path"]).is_file()
    assert render["duration_s"] == pytest.approx(36.65, abs=0.5)
    assert len(render["sha256"]) == 64

    # 回放片能从板面媒体端点取到
    media = client.get("/api/backlot/media/run-api/replay_approved.mp4")
    assert media.status_code == 200


def test_media_endpoint_refuses_traversal() -> None:
    assert client.get("/api/backlot/media/../../../etc/passwd").status_code in (400, 404)
    assert client.get("/api/backlot/media/run-api/..%2F..%2Fetc%2Fpasswd").status_code in (400, 404)


def test_quality_measure_failure_does_not_block_registration(monkeypatch) -> None:
    monkeypatch.setattr(
        "hevi.api.routers.backlot.measure_quality",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    r = client.post(
        "/api/backlot/runs/run-api/shots",
        json={"scene_id": "z", "source_path": BROLL, "cost_usd": 0.1},
    )
    assert r.status_code == 200
    shot = r.json()["shot"]
    assert shot["quality"]["error"] == "boom"
    assert shot["status"] == "pending"
