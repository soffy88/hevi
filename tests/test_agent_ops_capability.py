"""Tests for agent.ops_bridge capability contract per CAPABILITY_CONTRACT.md.

契约要求：
- 注册后能被 list 查到；
- 用 schema 校验非法参数，必须报错；
- 渲染 2 秒的产物要通过 ffprobe 检查；
- 删除产物后，测试必须失败。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hevi.capabilities.registry import CapabilityError, get, list_capabilities, resolve
from hevi.renderers.ffmpeg import resolve_ffprobe_bin
from hevi.operations.in_memory import InMemoryGraphRepository, InMemoryTaskRepository
from hevi.operations.bridge import OperationBridge, SqliteOperationsStore
from uuid import uuid4
import asyncio


def test_capability_registered_and_discoverable() -> None:
    cap = get("agent.ops_bridge")
    assert cap.name == "agent.ops_bridge"
    assert cap.kind == "line"
    assert "9:16" in cap.aspects and "16:9" in cap.aspects

    # 能被 resolve 与 list 查到
    resolved = resolve("agent.ops_bridge")
    assert resolved.name == cap.name
    all_caps = list_capabilities()
    assert any(c.name == "agent.ops_bridge" for c in all_caps)


def test_capability_schema_validation_rejects_invalid_params() -> None:
    cap = get("agent.ops_bridge")

    # 合法参数通过
    assert cap.validate_params({"format": "preview"}) == {"format": "preview"}
    assert cap.validate_params({}) == {}

    # 非法枚举值报错（统一 registry 契约：失败抛 CapabilityError，绝不返回假成功）
    with pytest.raises(CapabilityError, match="format"):
        cap.validate_params({"format": "invalid_format"})

    # 多余未知参数报错
    with pytest.raises(CapabilityError, match="Additional properties are not allowed"):
        cap.validate_params({"bogus_key": 123})


def test_capability_render_2s_product_and_ffprobe_check(tmp_path: Path) -> None:
    cap = get("agent.ops_bridge")
    out_dir = tmp_path / "cap_render"

    res = cap.render({"format": "preview"}, out_dir, duration=2.0, aspect="9:16", seed=42)

    assert res.duration_s == 2.0
    assert res.mp4 is not None
    mp4_file = Path(res.mp4)
    assert mp4_file.is_file() and mp4_file.stat().st_size > 0
    assert len(res.sha256) == 64
    assert res.qa["count"] == 8

    # ffprobe 检查时长（2.00s ± 0.1s）与分辨率 (320x568)
    probe_cmd = [
        resolve_ffprobe_bin(),
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=width,height",
        "-of",
        "json",
        str(mp4_file),
    ]
    probe_res = subprocess.run(probe_cmd, check=True, capture_output=True, text=True)
    probe_data = json.loads(probe_res.stdout)
    actual_dur = float(probe_data["format"]["duration"])
    assert abs(actual_dur - 2.0) <= 0.1

    video_stream = next(s for s in probe_data["streams"] if "width" in s)
    assert video_stream["width"] == 320
    assert video_stream["height"] == 568

    # 删除产物后，检验必须失败
    mp4_file.unlink()
    assert not mp4_file.exists()
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run(probe_cmd, check=True, capture_output=True, text=True)


def test_ops_canvas_get_reads_existing_graph_repository(tmp_path: Path) -> None:
    graph_repo = InMemoryGraphRepository()
    g_id = str(uuid4())
    asyncio.run(graph_repo.create({"id": g_id, "graph_id": g_id, "nodes": [{"type": "script", "rows": []}], "edges": [], "revision": 1}))
    store = SqliteOperationsStore(tmp_path / "ops.db")
    store._graph_repo = graph_repo
    bridge = OperationBridge(store)
    res = asyncio.run(bridge.execute("canvas.get", {"graph_id": g_id}))
    assert res["graph_id"] == g_id
    assert res["revision"] == 1


def test_propose_no_row_in_existing_tasks_table(tmp_path: Path) -> None:
    task_repo = InMemoryTaskRepository()
    store = SqliteOperationsStore(tmp_path / "ops.db")
    store._task_repo = task_repo
    bridge = OperationBridge(store)
    before_count = len(asyncio.run(task_repo.list_tasks()))
    g_id = str(uuid4())
    asyncio.run(store._graph_repo.create({"id": g_id, "graph_id": g_id, "nodes": [], "edges": [], "revision": 0}))
    res = asyncio.run(bridge.execute("canvas.generation.propose", {"graph_id": g_id, "prompt": "test"}))
    assert "proposalId" in res
    after_count = len(asyncio.run(task_repo.list_tasks()))
    assert after_count == before_count


def test_confirm_creates_task_via_existing_task_repository_local_stub(tmp_path: Path) -> None:
    task_repo = InMemoryTaskRepository()
    store = SqliteOperationsStore(tmp_path / "ops.db")
    store._task_repo = task_repo
    t_id = str(uuid4())
    asyncio.run(store.create_task(t_id, {"topic": "test", "status": "submitted", "provider": "local_stub"}))
    task = asyncio.run(task_repo.get_task(t_id))
    assert task is not None
    assert task["topic"] == "test"


def test_replay_receipt_equals_first(tmp_path: Path) -> None:
    store = SqliteOperationsStore(tmp_path / "ops.db")
    bridge = OperationBridge(store)
    g_id = str(uuid4())
    asyncio.run(store._graph_repo.create({"id": g_id, "graph_id": g_id, "nodes": [{"type": "script", "rows": []}], "edges": [], "revision": 0}))
    params = {"graph_id": g_id, "row": {"effect": "warm", "transition_in": "fade", "duration": 3.0}, "expectedRevision": 0}
    first = asyncio.run(bridge.execute("canvas.script.rows.append", params, op_id="op-A"))
    replay = asyncio.run(bridge.execute("canvas.script.rows.append", params, op_id="op-A"))
    assert replay.get("replayed") is True
    first_clean = {k: v for k, v in first.items() if k != "replayed"}
    replay_clean = {k: v for k, v in replay.items() if k != "replayed"}
    assert first_clean == replay_clean


def test_no_parallel_tables() -> None:
    bridge_code = Path("hevi/operations/bridge.py").read_text(encoding="utf-8")
    import re
    create_tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", bridge_code)
    assert set(create_tables) <= {"agent_op_receipts", "agent_schema_version"}
    assert "agent_graphs" not in create_tables
    assert "agent_tasks" not in create_tables
    assert "agent_assets" not in create_tables
    assert "agent_proposals" not in create_tables

