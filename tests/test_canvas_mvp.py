"""Canvas MVP tests: default koubo graph, stale/scope rules, incremental engine.

No database, provider, network or media render happens here: the node executor
and reviewer are fakes, and the store is the in-memory implementation.  The
self-check tests use missing files on purpose (that *is* the red path) and a
tiny local text fixture.
"""

from __future__ import annotations

from typing import Any

import pytest

from hevi.canvas import graph_diff as gd
from hevi.canvas.incremental_executor import ExecuteOptions, IncrementalExecutor
from hevi.canvas.koubo_template import (
    KOUBO_STEPS,
    build_koubo_graph,
    project_execution_plan,
)
from hevi.canvas.node_store import InMemoryNodeStore, normalize_artifacts
from hevi.canvas.self_check import review_node, status_for_review
from hevi.canvas.validation import EDGE_COMPATIBLE, validate_graph
from oprim.hevi_types import CanvasEdge, CanvasNode


def _graph(**kwargs: Any) -> dict[str, Any]:
    return build_koubo_graph(script_text="把一件事讲清楚。第二句。第三句。", topic="讲清楚", **kwargs)


def _model(graph: dict[str, Any]) -> tuple[list[CanvasNode], list[CanvasEdge]]:
    return (
        [CanvasNode.model_validate(n) for n in graph["nodes"]],
        [CanvasEdge.model_validate(e) for e in graph["edges"]],
    )


# ── default graph ────────────────────────────────────────────────────────────


def test_koubo_graph_has_eight_steps_and_legal_edges() -> None:
    graph = _graph()
    nodes, edges = _model(graph)
    assert [n.node_id for n in nodes] == [s["key"] for s in KOUBO_STEPS]
    assert len(nodes) == 8
    validate_graph(nodes, edges)  # raises on illegal edge / cycle
    assert all((e.from_type, e.to_type) in EDGE_COMPATIBLE for e in edges if e.from_type)


def test_koubo_graph_carries_execution_context() -> None:
    graph = _graph(duration_s=7.5, engine="livliv", character_id="d03ft")
    nodes = {n["node_id"]: n for n in graph["nodes"]}
    assert nodes["script"]["config"]["koubo_step"] == "script"
    assert nodes["tts"]["config"]["koubo_step"] == "tts"
    assert nodes["final"]["config"]["duration_s"] == 7.5
    assert nodes["final"]["config"]["engine"] == "livliv"
    assert nodes["avatar"]["node_type"] == "video"
    assert nodes["subtitle"]["node_type"] == "text"


def test_execution_plan_projection_by_key_and_by_order() -> None:
    by_key = {
        "nodes": [
            {"node_key": "script", "prompt": "plan script"},
            {"node_key": "tts", "provider": "edge_tts"},
        ]
    }
    projected = project_execution_plan(by_key)
    assert projected["script"]["prompt"] == "plan script"
    assert projected["tts"]["provider"] == "edge_tts"
    assert "evidence" not in projected

    by_order = {"nodes": [{"prompt": f"n{i}"} for i in range(8)]}
    projected = project_execution_plan(by_order)
    assert projected["script"]["prompt"] == "n0"
    assert projected["final"]["prompt"] == "n7"


# ── stale / scope rules ──────────────────────────────────────────────────────


def test_config_edit_marks_node_and_downstream_stale() -> None:
    old = _graph()["nodes"]
    new = _graph()["nodes"]
    new[0]["config"]["content"] = "改过的脚本"
    affected = gd.affected_nodes(old, new, _graph()["edges"])
    assert affected == {s["key"] for s in KOUBO_STEPS}  # root + 7 downstream


def test_ui_only_edit_does_not_mark_stale() -> None:
    old = _graph()["nodes"]
    new = _graph()["nodes"]
    new[0]["label"] = "新标签"
    new[0]["position"] = {"x": 1, "y": 2}
    assert gd.affected_nodes(old, new, _graph()["edges"]) == set()


def test_compute_run_set_dirty_selected_and_locked() -> None:
    keys = [s["key"] for s in KOUBO_STEPS]
    edges = _graph()["edges"]
    nodes = {k: {"status": "ok", "revision": 1, "locked": False} for k in keys}
    nodes["subtitle"]["status"] = "stale"
    dirty = gd.compute_run_set(scope="dirty", node_keys=keys, edges=edges, nodes=nodes)
    assert dirty["run"] == ["subtitle"]

    selected = gd.compute_run_set(
        scope="selected", node_keys=keys, edges=edges, nodes=nodes,
        selected_ids=["subtitle"],
    )
    assert selected["run"] == ["subtitle", "final"]

    nodes["final"]["locked"] = True
    locked = gd.compute_run_set(
        scope="selected", node_keys=keys, edges=edges, nodes=nodes,
        selected_ids=["subtitle"],
    )
    assert locked["run"] == ["subtitle"]
    assert locked["locked"] == ["final"]


# ── incremental engine ───────────────────────────────────────────────────────


def _executor_factory(calls: list[str]):
    async def execute(node, upstream):
        calls.append(node.node_id)
        return {"type": node.node_type, "output": f"/tmp/{node.node_id}.txt"}

    return execute


def _pass_reviewer(node, output, **kwargs):
    return {"result": "pass", "reasons": [], "suggested_prompt": "", "model": "test"}


@pytest.mark.asyncio
async def test_full_run_then_late_node_edit_reruns_only_tail() -> None:
    graph = _graph()
    store = InMemoryNodeStore()
    await store.sync_graph("g1", graph["nodes"], graph["edges"])
    calls: list[str] = []
    engine = IncrementalExecutor(store, executor=_executor_factory(calls), reviewer=_pass_reviewer)

    first = await engine.execute("g1", graph, options=ExecuteOptions(scope="dirty"))
    assert first["status"] == "completed"
    assert first["ran"] == [s["key"] for s in KOUBO_STEPS]
    states = await store.load_nodes("g1")
    assert all(s.status == "ok" and s.revision == 1 for s in states.values())

    # Edit the subtitle step only: stale = subtitle + final.
    edited = _graph()
    for node in edited["nodes"]:
        if node["node_id"] == "subtitle":
            node["config"]["content"] = "新的字幕要求"
    await store.sync_graph("g1", edited["nodes"], edited["edges"])
    states = await store.load_nodes("g1")
    assert states["subtitle"].status == "stale"
    assert states["final"].status == "stale"
    assert states["edit"].status == "ok"
    assert states["edit"].revision == 1

    calls.clear()
    second = await engine.execute("g1", edited, options=ExecuteOptions(scope="dirty"))
    assert second["ran"] == ["subtitle", "final"]
    assert set(second["skipped"]) == {s["key"] for s in KOUBO_STEPS if s["key"] not in ("subtitle", "final")}
    states = await store.load_nodes("g1")
    assert states["edit"].revision == 1  # upstream untouched
    assert states["subtitle"].revision == 2
    assert states["final"].revision == 2


@pytest.mark.asyncio
async def test_locked_node_is_skipped_and_reported() -> None:
    graph = _graph()
    store = InMemoryNodeStore()
    await store.sync_graph("g1", graph["nodes"], graph["edges"])
    await store.set_locked("g1", "final", True)
    calls: list[str] = []
    engine = IncrementalExecutor(store, executor=_executor_factory(calls), reviewer=_pass_reviewer)
    result = await engine.execute("g1", graph, options=ExecuteOptions(scope="all"))
    assert "final" not in result["ran"]
    assert result["locked_skipped"] == ["final"]
    assert "final" not in calls


@pytest.mark.asyncio
async def test_failed_node_is_retried_once_then_green() -> None:
    graph = _graph()
    store = InMemoryNodeStore()
    await store.sync_graph("g1", graph["nodes"], graph["edges"])
    attempts: dict[str, int] = {}

    async def execute(node, upstream):
        attempts[node.node_id] = attempts.get(node.node_id, 0) + 1
        return {"type": node.node_type, "output": f"/tmp/{node.node_id}.txt"}

    def reviewer(node, output, **kwargs):
        if node["node_id"] == "evidence" and attempts.get("evidence", 0) == 1:
            return {"result": "fail", "reasons": ["证据图缺失"],
                    "suggested_prompt": "换一张切题证据图"}
        return {"result": "pass", "reasons": [], "suggested_prompt": ""}

    engine = IncrementalExecutor(store, executor=execute, reviewer=reviewer)
    result = await engine.execute("g1", graph, options=ExecuteOptions(scope="dirty"))
    assert attempts["evidence"] == 2
    assert result["status"] == "completed"
    assert result["retries"] == {"evidence": 1}
    state = await store.get_node("g1", "evidence")
    assert state is not None and state.status == "ok"
    assert state.revision == 1  # revisions are written on a succeeded node, not per failed attempt


@pytest.mark.asyncio
async def test_always_failing_node_turns_red_after_one_retry() -> None:
    graph = _graph()
    store = InMemoryNodeStore()
    await store.sync_graph("g1", graph["nodes"], graph["edges"])
    attempts: dict[str, int] = {}

    async def execute(node, upstream):
        attempts[node.node_id] = attempts.get(node.node_id, 0) + 1
        return {"type": node.node_type, "output": f"/tmp/{node.node_id}.txt"}

    def reviewer(node, output, **kwargs):
        if node["node_id"] == "tts":
            return {"result": "fail", "reasons": ["音频为空"], "suggested_prompt": "重合成"}
        return {"result": "pass", "reasons": [], "suggested_prompt": ""}

    engine = IncrementalExecutor(store, executor=execute, reviewer=reviewer)
    result = await engine.execute("g1", graph, options=ExecuteOptions(scope="dirty"))
    assert attempts["tts"] == 2
    assert result["status"] == "partial"
    state = await store.get_node("g1", "tts")
    assert state is not None and state.status == "fail"
    assert state.review["result"] == "fail"


@pytest.mark.asyncio
async def test_interrupted_running_node_resumes() -> None:
    graph = _graph()
    store = InMemoryNodeStore()
    await store.sync_graph("g1", graph["nodes"], graph["edges"])
    await store.set_status("g1", "avatar", "running")
    calls: list[str] = []
    engine = IncrementalExecutor(store, executor=_executor_factory(calls), reviewer=_pass_reviewer)
    result = await engine.execute("g1", graph, options=ExecuteOptions(scope="dirty"))
    assert "avatar" in result["ran"]
    assert len(result["ran"]) == 8


# ── self-check ───────────────────────────────────────────────────────────────


def test_text_review_fails_empty_and_banned_words() -> None:
    empty = review_node({"node_type": "text", "config": {}}, {})
    assert empty["result"] == "fail"
    assert status_for_review(empty) == "fail"

    banned = review_node(
        {"node_type": "script", "config": {}},
        {"output": "这是一段 TODO 占位文本，后面再补。"},
    )
    assert banned["result"] == "fail"

    good = review_node(
        {"node_type": "text", "config": {}},
        {"output": "这是一段完整、可读、语气自然的讲稿文本。"},
    )
    assert good["result"] == "pass"


def test_text_review_warns_short_and_accepts_llm_port() -> None:
    short = review_node({"node_type": "text", "config": {}}, {"output": "太短"})
    assert short["result"] == "warn"

    def llm(text, cfg):
        return {"result": "warn", "reasons": ["LLM: 语气更像广告"], "suggested_prompt": "改成口语"}

    ported = review_node(
        {"node_type": "text", "config": {}},
        {"output": "这是一段完整、可读、语气自然的讲稿文本。"},
        llm_reviewer=llm,
    )
    assert ported["result"] == "warn"
    assert any("广告" in r for r in ported["reasons"])


def test_video_review_fails_missing_artifact_and_audio_review_fails_missing() -> None:
    video = review_node(
        {"node_type": "video", "config": {"duration_s": 5}},
        {"output": "/tmp/does-not-exist-canvas-mvp.mp4"},
    )
    assert video["result"] == "fail"
    assert status_for_review(video) == "fail"

    audio = review_node(
        {"node_type": "audio", "config": {}},
        {"output": "/tmp/does-not-exist-canvas-mvp.wav"},
    )
    assert audio["result"] == "fail"


def test_normalize_artifacts_picks_known_paths(tmp_path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"not-a-real-video")
    rows = normalize_artifacts({"output": str(media)})
    assert rows[0]["kind"] == "video"
    assert rows[0]["digest"] and len(rows[0]["digest"]) == 64
    assert rows[0]["size_bytes"] == len(b"not-a-real-video")
