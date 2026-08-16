"""v9.1:WorkspaceManager —— 工单沙盒 + SQLite 状态机 + WebSocket 推流基建测试。

覆盖:
  * 目录沙盒(inputs/assets/outputs)自动创建
  * 颗粒度状态机(tts_status/asr_status)与断点续传跳过
  * save_state/get_state 的 DB 增删改查(不再有 state.json 单文件)
  * 顶层 status/progress/error 字段联动
  * 失败后可重试(register 幂等)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.core.db import engine
from hevi.core.models import TaskRun
from hevi.core.workspace import WorkspaceManager, new_task_id


@pytest.fixture(autouse=True)
def _clean_workspace_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试用独立沙盒根目录,并清理 DB 行(避免跨测试污染)。"""
    monkeypatch.setattr("hevi.core.workspace.DEFAULT_WORKSPACE_ROOT", tmp_path)
    yield
    from sqlmodel import Session, delete

    with Session(engine) as session:
        session.exec(delete(TaskRun))
        session.commit()


def test_workspace_creates_sandbox_directories(tmp_path: Path) -> None:
    tid = new_task_id()
    ws = WorkspaceManager(tid, workspace_root=tmp_path)
    assert ws.root.is_dir()
    assert {p.name for p in ws.root.iterdir()} == {"inputs", "assets", "outputs"}


def test_put_input_and_asset_output_paths(tmp_path: Path) -> None:
    ws = WorkspaceManager("w-path", workspace_root=tmp_path)
    f = ws.put_input("notes.txt", "hello")
    assert f.read_text() == "hello"
    assert f.parent.name == "inputs"
    assert ws.asset_path("voice.mp3").parent.name == "assets"
    assert ws.output_path("final.mp4").parent.name == "outputs"


def test_state_machine_step_done_and_skip(tmp_path: Path) -> None:
    ws = WorkspaceManager("w-state", workspace_root=tmp_path)
    assert ws.is_step_done("tts") is False
    ws.mark_step_done("tts", progress=25)
    assert ws.is_step_done("tts") is True
    assert ws.is_step_done("asr") is False
    ws.mark_step_done("asr", progress=40)
    # 崩溃后重试:重新实例化,已完成步骤仍可跳过
    ws2 = WorkspaceManager("w-state", workspace_root=tmp_path)
    assert ws2.is_step_done("tts") is True
    assert ws2.is_step_done("asr") is True
    assert ws2.get_state("progress") == 40


def test_update_progress_and_failed(tmp_path: Path) -> None:
    ws = WorkspaceManager("w-progress", workspace_root=tmp_path)
    ws.update_progress("running", 10)
    snap = ws.snapshot()
    assert snap["status"] == "running"
    assert snap["progress"] == 10
    ws.mark_failed("boom")
    snap2 = ws.snapshot()
    assert snap2["status"] == "failed"
    assert snap2["error_log"] == "boom"


def test_register_is_idempotent(tmp_path: Path) -> None:
    ws1 = WorkspaceManager("w-dup", workspace_root=tmp_path)
    ws1.mark_step_done("html")
    # 同 task_id 二次实例化不覆盖状态、不炸唯一约束
    ws2 = WorkspaceManager("w-dup", workspace_root=tmp_path)
    assert ws2.is_step_done("html") is True


def test_record_result_sha_binds_output_identity(tmp_path: Path) -> None:
    """v9.1: 成片 SHA-256 写入 state_json[result_sha](返工/审核对同一稿)。"""
    from hevi.core.workspace import WorkspaceManager

    wm = WorkspaceManager("sha-probe", workspace_root=tmp_path)
    out = wm.output_path("final.mp4")
    out.write_bytes(b"fake-mp4-content-v1")
    digest = wm.record_result_sha(out)
    assert digest == "bab6fae24e722e96d8716493ab11070e7c1489d3383b000c148d366f2f3d27dd"
    assert wm.get_state("result_sha") == digest
    # 换内容 → 指纹变化(证明绑定的是当前稿)。
    out.write_bytes(b"fake-mp4-content-v2")
    digest2 = wm.record_result_sha(out)
    assert digest2 != digest

    # 缺失文件 → None 不抛错。
    assert wm.record_result_sha(tmp_path / "nope.mp4") is None
    from sqlmodel import Session, delete

    from hevi.core.db import engine
    from hevi.core.models import TaskRun

    with Session(engine) as session:
        session.exec(delete(TaskRun).where(TaskRun.task_id == "sha-probe"))
        session.commit()
