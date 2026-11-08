"""S5 stability tests: output isolation, dynamic topology, avatar window, evidence."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from oprim.hevi_types import CanvasEdge, CanvasNode

from hevi.canvas import evidence as ev
from hevi.canvas import koubo_executor
from hevi.canvas.incremental_executor import IncrementalExecutor
from hevi.canvas.koubo_template import build_koubo_graph
from hevi.canvas.node_store import InMemoryNodeStore
from hevi.canvas.self_check import _check_avatar_window
from hevi.canvas.topology import archive_node_artifacts, reconcile_koubo_topology
from hevi.canvas.validation import validate_graph


def _graph(script: str) -> dict[str, Any]:
    return build_koubo_graph(script_text=script, topic="橘猫")


def _validate(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    validate_graph(
        [CanvasNode.model_validate(n) for n in nodes],
        [CanvasEdge.model_validate(e) for e in edges],
    )


# ── dynamic topology ────────────────────────────────────────────────────────


def test_topology_grows_three_to_five_and_shrinks_back() -> None:
    graph = _graph("第一句。第二句。第三句。")
    nodes = [dict(n, config=dict(n["config"])) for n in graph["nodes"]]
    edges = list(graph["edges"])
    for node in nodes:
        if node["node_id"] == "script":
            node["config"]["content"] = "一。二。三。四。五。"

    grown = reconcile_koubo_topology(nodes, edges)
    assert grown is not None
    assert grown["sentence_count"] == 5
    ids = {n["node_id"] for n in grown["nodes"]}
    for i in range(1, 6):
        for prefix in ("tts", "evidence", "avatar", "segment"):
            assert f"{prefix}_{i}" in ids
    assert {"segment_4", "segment_5"} <= set(grown["added"])
    _validate(grown["nodes"], grown["edges"])
    assert len([e for e in grown["edges"] if e["to_node_id"] == "edit"]) == 5

    for node in grown["nodes"]:
        if node["node_id"] == "script":
            node["config"]["content"] = "甲。乙。丙。"
    shrunk = reconcile_koubo_topology(grown["nodes"], grown["edges"])
    assert shrunk is not None
    assert shrunk["sentence_count"] == 3
    assert set(shrunk["removed"]) == {
        "tts_4", "evidence_4", "avatar_4", "segment_4",
        "tts_5", "evidence_5", "avatar_5", "segment_5",
    }
    _validate(shrunk["nodes"], shrunk["edges"])
    assert len([e for e in shrunk["edges"] if e["to_node_id"] == "edit"]) == 3


def test_topology_keeps_locked_sentence_branch() -> None:
    graph = _graph("第一句。第二句。第三句。")
    nodes = [dict(n, config=dict(n["config"])) for n in graph["nodes"]]
    for node in nodes:
        if node["node_id"] == "script":
            node["config"]["content"] = "甲。乙。"
    result = reconcile_koubo_topology(nodes, graph["edges"], locked_keys={"segment_3"})
    assert result is not None
    assert "segment_3" in {n["node_id"] for n in result["nodes"]}
    assert "segment_3" not in result["removed"]
    _validate(result["nodes"], result["edges"])


def test_removed_node_artifacts_are_archived_not_overwritten(tmp_path: Path) -> None:
    node = {"node_id": "segment_3", "config": {"out_dir": str(tmp_path)}}
    live = tmp_path / "g-1" / "segment_3"
    live.mkdir(parents=True)
    (live / "segment.mp4").write_bytes(b"old")
    archived = archive_node_artifacts("g-1", node)
    assert archived is not None and Path(archived, "segment.mp4").read_bytes() == b"old"
    assert not live.exists()
    # A re-added node can now render at the same path without touching the archive.
    live.mkdir(parents=True)
    (live / "segment.mp4").write_bytes(b"new")
    assert Path(archived, "segment.mp4").read_bytes() == b"old"


# ── per-graph output isolation (concurrent graphs) ─────────────────────────


def test_out_dir_is_scoped_per_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    a = SimpleNamespace(node_id="segment_1", config={"graph_id": "graph-a"})
    b = SimpleNamespace(node_id="segment_1", config={"graph_id": "graph-b"})
    assert koubo_executor._out_dir(a) != koubo_executor._out_dir(b)


def test_two_graphs_run_concurrently_without_overwriting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    store = InMemoryNodeStore()

    def passthrough(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"result": "pass"}

    async def write_marker(node: Any, upstream: dict[str, Any]) -> dict[str, Any]:
        out = koubo_executor._out_dir(node)
        marker = f"{node.config.get('graph_id')}:{node.node_id}"
        (out / "artifact.txt").write_text(marker, encoding="utf-8")
        return {
            "koubo_step": str(node.config.get("koubo_step") or ""),
            "output": str(out / "artifact.txt"),
            "content_hash": hashlib.sha256(marker.encode()).hexdigest(),
            "artifacts": [{"kind": "text", "path": str(out / "artifact.txt")}],
        }

    engine = IncrementalExecutor(store, executor=write_marker, reviewer=passthrough)

    async def run() -> list[dict[str, Any]]:
        return await asyncio.gather(
            engine.execute("graph-a", _graph("甲。乙。")),
            engine.execute("graph-b", _graph("丙。丁。")),
        )

    results = asyncio.run(run())
    assert all(r["status"] in ("completed", "partial") for r in results)
    for graph_id, other in (("graph-a", "graph-b"), ("graph-b", "graph-a")):
        out = tmp_path / "output" / "canvas" / "koubo" / graph_id / "segment_1" / "artifact.txt"
        assert out.is_file()
        assert out.read_text(encoding="utf-8").startswith(graph_id + ":")
        assert other not in out.read_text(encoding="utf-8")


# ── avatar corner window hard check ────────────────────────────────────────


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


@pytest.mark.skipif(_ffmpeg() is None, reason="ffmpeg unavailable")
def test_blank_pip_window_is_red_and_real_content_passes(tmp_path: Path) -> None:
    ffmpeg = _ffmpeg()
    blank = tmp_path / "blank.mp4"
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=0xf6efe3:s=1080x1920:r=5:d=1",
         "-pix_fmt", "yuv420p", str(blank)],
        capture_output=True, check=True,
    )
    verdict = _check_avatar_window(blank, "segment", {"evidence": True}, duration=1.0)
    assert verdict is not None and verdict["result"] == "fail"

    rich = tmp_path / "rich.mp4"
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=5:duration=1",
         "-pix_fmt", "yuv420p", str(rich)],
        capture_output=True, check=True,
    )
    verdict = _check_avatar_window(rich, "segment", {"evidence": True}, duration=1.0)
    assert verdict is not None and verdict["result"] == "pass"


# ── evidence relevance: the subject wins ───────────────────────────────────


def test_cat_sentence_query_contains_subject_and_scene() -> None:
    query, subject = ev.query_plan("橘猫趴在海边石台上，不看镜头。", topic="AI")
    assert subject == "orange cat"
    assert "orange cat" in query and "beach" in query
    assert "ocean sea waves" not in query


def test_offline_relevance_rejects_scene_only_photo_for_cat_sentence() -> None:
    ocean = {
        "sentence": "橘猫趴在海边石台上。",
        "query": "orange cat beach",
        "subject": "orange cat",
        "meta": {"alt": "ocean waves on a sandy beach", "title": "", "tags": "sea wave"},
    }
    assert ev.judge_relevance("橘猫趴在海边石台上。", ocean) is False

    cat = {
        "sentence": "橘猫趴在海边石台上。",
        "query": "orange cat beach",
        "subject": "orange cat",
        "meta": {"alt": "orange cat sitting on a stone", "title": "", "tags": ""},
    }
    assert ev.judge_relevance("橘猫趴在海边石台上。", cat) is True


# ── GraphService wiring: edit -> reconcile -> node store ───────────────────


class _Repo:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    async def get(self, graph_id: str) -> dict[str, Any] | None:
        return dict(self.row)

    async def update(self, graph_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        self.row = {**self.row, **updates}
        return dict(self.row)


def test_update_graph_adds_and_removes_sentence_branches(tmp_path: Path) -> None:
    from hevi.canvas.graph_service import GraphService

    graph = _graph("甲。乙。丙。")
    graph["id"] = "g-topo"
    graph["nodes_json"] = graph["nodes"]
    graph["edges_json"] = graph["edges"]
    store = InMemoryNodeStore()
    service = GraphService(_Repo(graph), store)

    async def initialise() -> None:
        await store.sync_graph("g-topo", graph["nodes"], graph["edges"])

    asyncio.run(initialise())

    five = [dict(n, config=dict(n["config"])) for n in graph["nodes"]]
    for node in five:
        if node["node_id"] == "script":
            node["config"]["content"] = "一。二。三。四。五。"
    stored = asyncio.run(service.update_graph("g-topo", nodes=five))
    assert stored is not None
    ids = {n["node_id"] for n in stored["nodes_json"]}
    assert {"tts_5", "segment_5"} <= ids
    states = asyncio.run(store.load_nodes("g-topo"))
    assert "segment_5" in states

    three = [dict(n, config=dict(n["config"])) for n in stored["nodes_json"]]
    for node in three:
        if node["node_id"] == "script":
            node["config"]["content"] = "甲。乙。丙。"
    stored = asyncio.run(service.update_graph("g-topo", nodes=three))
    assert stored is not None
    ids = {n["node_id"] for n in stored["nodes_json"]}
    assert "tts_4" not in ids and "segment_5" not in ids
    states = asyncio.run(store.load_nodes("g-topo"))
    assert "tts_4" not in states and "segment_5" not in states


# ── scheduler retention ────────────────────────────────────────────────────


def test_output_retention_keeps_finals_and_verify_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import time

    from hevi.scheduler.retention import purge_intermediate_outputs

    root = tmp_path / "output"
    (root / "run" / "segment").mkdir(parents=True)
    (root / "run" / "verify_manual").mkdir(parents=True)
    (root / "run" / "final").mkdir(parents=True)

    old = time.time() - 10 * 86400
    very_old = time.time() - 40 * 86400
    fresh = time.time()
    files = {
        root / "run" / "tts.wav": old,
        root / "run" / "segment" / "segment.mp4": old,
        root / "run" / "verify_manual" / "frame.png": old,
        root / "run" / "final" / "koubo_cut.mp4": old,
        root / "run" / "final" / "film.mp4": very_old,
        root / "run" / "new.png": fresh,
    }
    for path, mtime in files.items():
        path.write_bytes(b"x" * 10)
        os.utime(path, (mtime, mtime))

    monkeypatch.setenv("HEVI_OUTPUT_ROOT", str(root))
    monkeypatch.delenv("HEVI_OUTPUT_RETENTION_ENABLED", raising=False)
    summary = purge_intermediate_outputs(intermediate_days=7, final_days=30)

    assert summary.deleted_files == 3  # tts.wav + segment.mp4 + 40-day final
    assert not (root / "run" / "tts.wav").exists()
    assert not (root / "run" / "segment" / "segment.mp4").exists()
    assert (root / "run" / "verify_manual" / "frame.png").exists()
    assert (root / "run" / "final" / "koubo_cut.mp4").exists()  # final, 10d < 30d
    assert not (root / "run" / "final" / "film.mp4").exists()  # final, 40d > 30d
    assert (root / "run" / "new.png").exists()
