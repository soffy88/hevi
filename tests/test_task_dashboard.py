"""v9.1:任务大盘 API + WebSocket 实时进度测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.core.db import engine
from hevi.core.models import TaskRun
from hevi.core.workspace import WorkspaceManager


@pytest.fixture(autouse=True)
def _clean_tasks_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hevi.core.workspace.DEFAULT_WORKSPACE_ROOT", tmp_path)
    from hevi.core.db import init_db

    init_db()  # 幂等建表:单独运行本文件时 lifespan 不触发,需显式保证表存在。
    # setup 与 teardown 都清空 TaskRun:防止其他测试(如 lite 管道)残留行干扰 total。
    from sqlmodel import Session, delete

    with Session(engine) as session:
        session.exec(delete(TaskRun))
        session.commit()
    yield
    with Session(engine) as session:
        session.exec(delete(TaskRun))
        session.commit()


def test_dashboard_lists_tasks_with_pagination_and_filter() -> None:
    client = TestClient(app)
    wm1 = WorkspaceManager("dash-1", pipeline_type="main_remotion", workspace_root="data/workspace")
    wm1.update_progress("completed", 100)
    wm2 = WorkspaceManager("dash-2", pipeline_type="lite_html", workspace_root="data/workspace")
    wm2.update_progress("running", 42)

    resp = client.get("/api/dashboard/tasks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    # 按 created_at 倒序:dash-2 后创建,应排前面
    assert [item["task_id"] for item in body["items"]] == ["dash-2", "dash-1"]

    filtered = client.get("/api/dashboard/tasks?status=running").json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["task_id"] == "dash-2"

    paged = client.get("/api/dashboard/tasks?limit=1&offset=0").json()
    assert len(paged["items"]) == 1

    detail = client.get("/api/dashboard/tasks/dash-2").json()
    assert detail["progress"] == 42
    assert detail["pipeline_type"] == "lite_html"
    client.close()


def test_dashboard_404_for_unknown_task() -> None:
    client = TestClient(app)
    resp = client.get("/api/dashboard/tasks/nope")
    assert resp.status_code == 404
    client.close()


def test_dashboard_output_serves_workspace_video(tmp_path: Path) -> None:
    """completed 任务带 result_video_path, 输出端点返回沙盒成片。"""
    from hevi.core.workspace import DEFAULT_WORKSPACE_ROOT

    client = TestClient(app)
    wm = WorkspaceManager(
        "dash-video", pipeline_type="main_remotion", workspace_root=DEFAULT_WORKSPACE_ROOT
    )
    wm.update_progress("running", 30)
    # running 阶段不应暴露 result_video_path。
    running = client.get("/api/dashboard/tasks/dash-video").json()
    assert running["result_video_path"] is None
    # 落一个成片再标记完成。
    (wm.root / "portrait.mp4").write_bytes(b"FAKE-MP4-BYTES")
    wm.update_progress("completed", 100)
    done = client.get("/api/dashboard/tasks/dash-video").json()
    assert done["status"] == "completed"
    assert done["result_video_path"] is not None
    media = client.get("/api/dashboard/tasks/dash-video/output")
    assert media.status_code == 200
    assert media.headers["content-type"] == "video/mp4"
    assert media.content == b"FAKE-MP4-BYTES"
    # 未知任务 → 404。
    assert client.get("/api/dashboard/tasks/nope/output").status_code == 404
    client.close()


def test_dashboard_status_counts() -> None:
    """列表响应携带各状态计数, 供前端统计卡片。"""
    client = TestClient(app)
    WorkspaceManager(
        "cnt-1", pipeline_type="main_remotion", workspace_root="data/workspace"
    ).update_progress("running", 10)
    WorkspaceManager(
        "cnt-2", pipeline_type="lite_html", workspace_root="data/workspace"
    ).update_progress("completed", 100)
    WorkspaceManager(
        "cnt-3", pipeline_type="lite_html", workspace_root="data/workspace"
    ).update_progress("failed", 0, error="boom")
    body = client.get("/api/dashboard/tasks").json()
    counts = body["status_counts"]
    assert counts["running"] == 1
    assert counts["completed"] == 1
    assert counts["failed"] == 1
    client.close()


def test_websocket_ping_pong() -> None:
    client = TestClient(app)
    with client.websocket_connect("/api/ws/tasks") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"
    client.close()
