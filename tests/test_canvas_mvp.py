"""Canvas MVP tests: parallel koubo graph, content-hash reuse, evidence, LLM review.

No database, provider, network or media render happens here: the node executor
and reviewer are fakes, and the store is the in-memory implementation.  Evidence
and LLM tests inject fakes/mocks, so no real call is made.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from oprim.hevi_types import CanvasEdge, CanvasNode

from hevi.canvas import graph_diff as gd
from hevi.canvas.graph_service import GraphService
from hevi.canvas.incremental_executor import ExecuteOptions, IncrementalExecutor
from hevi.canvas.koubo_template import (
    build_koubo_graph,
    project_execution_plan,
    split_script_lines,
)
from hevi.canvas.node_store import InMemoryNodeStore, normalize_artifacts
from hevi.canvas.self_check import review_node, status_for_review
from hevi.canvas.validation import EDGE_COMPATIBLE, validate_graph


def _graph(**kwargs: Any) -> dict[str, Any]:
    return build_koubo_graph(
        script_text="把一件事讲清楚。第二句很重要。第三句收尾。",
        topic="讲清楚",
        **kwargs,
    )


def _model(graph: dict[str, Any]) -> tuple[list[CanvasNode], list[CanvasEdge]]:
    return (
        [CanvasNode.model_validate(n) for n in graph["nodes"]],
        [CanvasEdge.model_validate(e) for e in graph["edges"]],
    )


def _keys(graph: dict[str, Any]) -> list[str]:
    return [n["node_id"] for n in graph["nodes"]]


# ── default graph ────────────────────────────────────────────────────────────


def test_koubo_graph_is_parallel_per_sentence_and_edges_are_legal() -> None:
    graph = _graph()
    nodes, edges = _model(graph)
    validate_graph(nodes, edges)  # raises on illegal edge / cycle
    assert all((e.from_type, e.to_type) in EDGE_COMPATIBLE for e in edges if e.from_type)
    keys = _keys(graph)
    assert graph["sentence_count"] == 3
    assert keys[:2] == ["script", "sentences"]
    assert keys[-3:] == ["edit", "subtitle", "final"]
    for index in range(1, 4):
        assert f"tts_{index}" in keys
        assert f"evidence_{index}" in keys
        assert f"avatar_{index}" in keys
        assert f"segment_{index}" in keys
    # Every sentence branch feeds the edit node.
    incoming = {e.to_node_id for e in edges}
    assert "edit" in incoming
    assert len([e for e in edges if e.to_node_id == "edit"]) == 3


def test_koubo_graph_carries_execution_context_and_sentence_index() -> None:
    graph = _graph(duration_s=7.5, engine="livliv", character_id="d03ft")
    nodes = {n["node_id"]: n for n in graph["nodes"]}
    assert nodes["script"]["config"]["koubo_step"] == "script"
    assert nodes["sentences"]["config"]["koubo_step"] == "sentences"
    assert nodes["tts_1"]["config"]["sentence_index"] == 0
    assert nodes["segment_3"]["config"]["sentence_index"] == 2
    assert nodes["final"]["config"]["duration_s"] == 7.5
    assert nodes["avatar_1"]["node_type"] == "video"
    assert nodes["subtitle"]["node_type"] == "text"


def test_split_uses_pipeline_rule_for_placeholder_scripts() -> None:
    lines = split_script_lines(script_text="第一句。第二句！第三句？", topic="测试")
    assert lines == ["第一句。", "第二句！", "第三句？"]


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
    new[0]["config"]["content"] = "改过的脚本。"
    affected = gd.affected_nodes(old, new, _graph()["edges"])
    assert affected == set(_keys(_graph()))  # root + every downstream


def test_ui_only_edit_does_not_mark_stale() -> None:
    old = _graph()["nodes"]
    new = _graph()["nodes"]
    new[0]["label"] = "新标签"
    new[0]["position"] = {"x": 1, "y": 2}
    assert gd.affected_nodes(old, new, _graph()["edges"]) == set()


def test_compute_run_set_dirty_selected_and_locked() -> None:
    graph = _graph()
    keys = _keys(graph)
    edges = graph["edges"]
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


# ── incremental engine + content hash ───────────────────────────────────────


def _sha(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _fake_koubo_executor(calls: list[str]):
    """Mirror the real outputs' shape enough for content-hash slicing."""

    def sentence_list(node, upstream):
        """Return [(text, start, end)] from the script/sentences upstream."""
        for out in upstream.values():
            if isinstance(out, dict) and out.get("koubo_step") == "sentences":
                return list(out.get("sentences") or [])
            if isinstance(out, dict) and out.get("koubo_step") == "script":
                lines = list(out.get("lines") or [])
                return [
                    {"text": text, "start": i * 1.0, "end": (i + 1) * 1.0}
                    for i, text in enumerate(lines)
                ]
        return []

    def index_of(node):
        return int((node.config or {}).get("sentence_index") or 0)

    async def execute(node, upstream):
        calls.append(node.node_id)
        step = str((node.config or {}).get("koubo_step") or "")
        idx = index_of(node)
        if step == "script":
            lines = [p for p in str(node.config.get("content") or "").split("。") if p]
            lines = [p + "。" for p in lines]
            return {"koubo_step": "script", "lines": lines, "output": "\n".join(lines),
                    "content_hash": _sha(lines)}
        if step == "sentences":
            text = str(next(iter(upstream.values())).get("output") or "")
            lines = [p.strip() for p in text.splitlines() if p.strip()]
            sents = [
                {"text": line, "start": i * 1.0, "end": (i + 1) * 1.0}
                for i, line in enumerate(lines)
            ]
            return {"koubo_step": "sentences", "sentences": sents, "output": text,
                    "content_hash": _sha(sents)}
        sents = sentence_list(node, upstream)
        sent = sents[idx] if idx < len(sents) else {"text": "", "start": 0, "end": 1}
        if step in ("tts", "tts_sentence"):
            return {"koubo_step": "tts", "sentence_index": idx, "text": sent["text"],
                    "duration_s": 1.0, "content_hash": _sha(sent["text"])}
        if step in ("evidence", "evidence_sentence"):
            return {"koubo_step": "evidence", "sentence_index": idx, "sentence": sent["text"],
                    "evidence": [{"ok": True, "path": f"/tmp/e{idx}.jpg",
                                  "sentence": sent["text"], "relevant": True}],
                    "content_hash": _sha({"e": sent["text"]})}
        if step in ("avatar", "avatar_sentence"):
            return {"koubo_step": "avatar", "sentence_index": idx, "duration_s": 1.0,
                    "content_hash": _sha({"a": idx})}
        if step == "segment":
            hashes = []
            for out in upstream.values():
                if isinstance(out, dict) and out.get("sentence_index") == idx:
                    hashes.append(out.get("content_hash"))
            return {"koubo_step": "segment", "sentence_index": idx, "text": sent["text"],
                    "duration_s": 1.0, "content_hash": _sha(hashes)}
        if step in ("edit", "edit_segments"):
            seg_outputs = sorted(
                [
                    v
                    for v in upstream.values()
                    if isinstance(v, dict) and v.get("koubo_step") == "segment"
                ],
                key=lambda v: int(v.get("sentence_index") or 0),
            )
            segments = [
                {"index": int(o.get("sentence_index") or 0), "start": i * 1.0,
                 "end": (i + 1) * 1.0, "text": ""}
                for i, o in enumerate(seg_outputs)
            ]
            hashes = [o.get("content_hash") for o in seg_outputs]
            return {"koubo_step": "edit", "segments": segments, "duration_s": 3.0,
                    "content_hash": _sha({"segments": segments, "hashes": hashes})}
        if step == "subtitle":
            edit = next(iter(upstream.values()), {})
            note = str((node.config or {}).get("note") or "")
            return {"koubo_step": "subtitle",
                    "content_hash": _sha({"edit": edit.get("content_hash"), "note": note})}
        return {"koubo_step": step, "content_hash": _sha(node.node_id)}

    return execute


def _pass_reviewer(node, output, **kwargs):
    return {"result": "pass", "reasons": [], "suggested_prompt": "",
            "review_mode": "deterministic", "model": "test"}


@pytest.mark.asyncio
async def test_full_run_then_subtitle_edit_reruns_only_tail() -> None:
    graph = _graph()
    store = InMemoryNodeStore()
    await store.sync_graph("g1", graph["nodes"], graph["edges"])
    calls: list[str] = []
    engine = IncrementalExecutor(
        store, executor=_fake_koubo_executor(calls), reviewer=_pass_reviewer
    )

    first = await engine.execute("g1", graph, options=ExecuteOptions(scope="dirty"))
    assert first["status"] == "completed"
    assert set(first["ran"]) == set(_keys(graph))
    states = await store.load_nodes("g1")
    assert all(s.status == "ok" and s.revision == 1 for s in states.values())

    edited = _graph()
    for node in edited["nodes"]:
        if node["node_id"] == "subtitle":
            node["config"]["note"] = "新的字幕要求"
    await store.sync_graph("g1", edited["nodes"], edited["edges"])
    states = await store.load_nodes("g1")
    assert states["subtitle"].status == "stale"
    assert states["final"].status == "stale"
    assert states["segment_1"].status == "ok"
    assert states["segment_1"].revision == 1

    calls.clear()
    second = await engine.execute("g1", edited, options=ExecuteOptions(scope="dirty"))
    assert second["ran"] == ["subtitle", "final"]
    states = await store.load_nodes("g1")
    assert states["segment_1"].revision == 1  # upstream untouched
    assert states["subtitle"].revision == 2
    assert states["final"].revision == 2


@pytest.mark.asyncio
async def test_content_hash_reuse_only_reruns_changed_sentence_branch() -> None:
    """Edit one sentence of the script: other sentence branches are reused."""
    graph = _graph()
    store = InMemoryNodeStore()
    await store.sync_graph("g1", graph["nodes"], graph["edges"])
    calls: list[str] = []
    engine = IncrementalExecutor(
        store, executor=_fake_koubo_executor(calls), reviewer=_pass_reviewer
    )
    await engine.execute("g1", graph, options=ExecuteOptions(scope="dirty"))
    hashes = {
        key: (await store.get_node("g1", key)).output["_engine"]["content_hash"]
        for key in _keys(graph)
    }

    edited = _graph()
    for node in edited["nodes"]:
        if node["node_id"] == "script":
            node["config"]["content"] = "把一件事讲清楚。第二句改过了。第三句收尾。"
    await store.sync_graph("g1", edited["nodes"], edited["edges"])
    calls.clear()
    result = await engine.execute("g1", edited, options=ExecuteOptions(scope="dirty"))

    # Only sentence 2's branch + edit/subtitle/final + the two text roots run.
    ran = set(result["ran"])
    assert {"script", "sentences", "tts_2", "evidence_2", "avatar_2", "segment_2",
            "edit", "subtitle", "final"} <= ran
    assert "segment_1" not in ran and "segment_3" not in ran
    assert {"tts_1", "evidence_1", "avatar_1", "segment_1",
            "tts_3", "evidence_3", "avatar_3", "segment_3"} <= set(result["reused"])

    states = await store.load_nodes("g1")
    assert states["segment_1"].revision == 1
    assert states["segment_3"].revision == 1
    assert states["segment_2"].revision == 2
    # Unchanged branches keep exactly the same artifact content hash.
    for key in ("segment_1", "segment_3"):
        assert states[key].output["_engine"]["content_hash"] == hashes[key]


@pytest.mark.asyncio
async def test_locked_node_is_skipped_and_reported() -> None:
    graph = _graph()
    store = InMemoryNodeStore()
    await store.sync_graph("g1", graph["nodes"], graph["edges"])
    await store.set_locked("g1", "final", True)
    calls: list[str] = []
    engine = IncrementalExecutor(
        store, executor=_fake_koubo_executor(calls), reviewer=_pass_reviewer
    )
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
        return {"type": node.node_type, "output": f"/tmp/{node.node_id}.txt",
                "content_hash": _sha(node.node_id)}

    def reviewer(node, output, **kwargs):
        if node["node_id"] == "evidence_2" and attempts.get("evidence_2", 0) == 1:
            return {"result": "fail", "reasons": ["证据图缺失"],
                    "suggested_prompt": "换一张切题证据图"}
        return {"result": "pass", "reasons": [], "suggested_prompt": ""}

    engine = IncrementalExecutor(store, executor=execute, reviewer=reviewer)
    result = await engine.execute("g1", graph, options=ExecuteOptions(scope="dirty"))
    assert attempts["evidence_2"] == 2
    assert result["status"] == "completed"
    assert result["retries"] == {"evidence_2": 1}
    state = await store.get_node("g1", "evidence_2")
    assert state is not None and state.status == "ok"
    assert state.revision == 1


@pytest.mark.asyncio
async def test_always_failing_node_turns_red_after_one_retry() -> None:
    graph = _graph()
    store = InMemoryNodeStore()
    await store.sync_graph("g1", graph["nodes"], graph["edges"])
    attempts: dict[str, int] = {}

    async def execute(node, upstream):
        attempts[node.node_id] = attempts.get(node.node_id, 0) + 1
        return {"type": node.node_type, "output": f"/tmp/{node.node_id}.txt",
                "content_hash": _sha(node.node_id)}

    def reviewer(node, output, **kwargs):
        if node["node_id"] == "tts_1":
            return {"result": "fail", "reasons": ["音频为空"], "suggested_prompt": "重合成"}
        return {"result": "pass", "reasons": [], "suggested_prompt": ""}

    engine = IncrementalExecutor(store, executor=execute, reviewer=reviewer)
    result = await engine.execute("g1", graph, options=ExecuteOptions(scope="dirty"))
    assert attempts["tts_1"] == 2
    assert result["status"] == "partial"
    state = await store.get_node("g1", "tts_1")
    assert state is not None and state.status == "fail"
    assert state.review["result"] == "fail"


@pytest.mark.asyncio
async def test_interrupted_running_node_resumes() -> None:
    graph = _graph()
    store = InMemoryNodeStore()
    await store.sync_graph("g1", graph["nodes"], graph["edges"])
    await store.set_status("g1", "segment_1", "running")
    calls: list[str] = []
    engine = IncrementalExecutor(
        store, executor=_fake_koubo_executor(calls), reviewer=_pass_reviewer
    )
    result = await engine.execute("g1", graph, options=ExecuteOptions(scope="dirty"))
    assert "segment_1" in result["ran"]


# ── self-check ───────────────────────────────────────────────────────────────


def test_text_review_fails_empty_and_banned_words() -> None:
    empty = review_node({"node_type": "text", "config": {}}, {})
    assert empty["result"] == "fail"
    assert status_for_review(empty) == "fail"
    assert empty["review_mode"] == "offline_rules"

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
    assert good["review_mode"] == "offline_rules"


def test_text_review_warns_short_and_accepts_llm_port() -> None:
    short = review_node({"node_type": "text", "config": {}}, {"output": "太短"})
    assert short["result"] == "warn"

    def llm(text, cfg):
        return {"result": "warn", "issues": ["LLM: 语气更像广告"],
                "suggested_prompt": "改成口语", "model": "mock/llm"}

    ported = review_node(
        {"node_type": "text", "config": {}},
        {"output": "这是一段完整、可读、语气自然的讲稿文本。"},
        llm_reviewer=llm,
    )
    assert ported["result"] == "warn"
    assert ported["review_mode"] == "llm"
    assert ported["model"] == "mock/llm"
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


# ── evidence ─────────────────────────────────────────────────────────────────


def test_evidence_query_and_source_label() -> None:
    from hevi.canvas import evidence

    q = evidence.query_for_sentence("一只橘猫坐在海边")
    assert "cat" in q or "sea" in q
    assert evidence.query_for_sentence("完全未知的中文句子") == "abstract background texture"
    label = evidence.source_label(
        {"provider": "pexels", "photographer": "Alice"}
    )
    assert "Pexels" in label and "Alice" in label
    web = evidence.source_label({"provider": "web", "domain": "en.wikipedia.org"})
    assert "en.wikipedia.org" in web


def test_evidence_skips_when_both_sources_fail(monkeypatch, tmp_path) -> None:
    from hevi.canvas import evidence

    monkeypatch.setattr(evidence, "_web_screenshot", lambda *a, **k: None)
    import hevi.collage_broll.assets as assets

    monkeypatch.setattr(assets, "pexels_photo_meta", lambda *a, **k: None)
    item = evidence.fetch_for_sentence("测试句子。", out_dir=tmp_path)
    assert item["ok"] is False
    assert "未取得" in item["skipped_reason"]

    review = review_node(
        {"node_type": "video", "config": {"koubo_step": "evidence_sentence"}},
        {"evidence": [item]},
    )
    assert review["result"] == "warn"


def test_evidence_real_source_and_relevance(monkeypatch, tmp_path) -> None:
    from PIL import Image

    from hevi.canvas import evidence

    image = tmp_path / "raw.jpg"
    Image.new("RGB", (64, 64), (30, 80, 120)).save(image)

    def fake_pexels(query, out_path, orientation="portrait", *, per_page=1, pick=0):
        return {
            "path": str(image),
            "provider": "pexels",
            "query": query,
            "photo_id": "1",
            "photographer": "Alice",
            "alt": "orange cat sitting by the sea",
            "page_url": "https://www.pexels.com/photo/1/",
        }

    import hevi.collage_broll.assets as assets

    monkeypatch.setattr(assets, "pexels_photo_meta", fake_pexels)
    item = evidence.fetch_for_sentence("一只橘猫坐在海边。", out_dir=tmp_path)
    assert item["ok"] is True
    assert item["relevant"] is True
    assert "Alice" in item["source_label"]

    review = review_node(
        {"node_type": "video", "config": {"koubo_step": "evidence_sentence"}},
        {"evidence": [{**item, "card_path": str(image)}]},
    )
    assert review["result"] == "pass"


def test_evidence_irrelevant_fails_and_retry_bumps_pick() -> None:
    from hevi.canvas.self_check import retry_config

    review = review_node(
        {"node_type": "video", "config": {"koubo_step": "evidence_sentence"}},
        {
            "evidence": [
                {"ok": True, "path": __file__, "sentence": "橘猫", "relevant": False}
            ]
        },
    )
    assert review["result"] == "fail"
    cfg = retry_config(
        {"node_type": "video", "config": {"koubo_step": "evidence_sentence"}}, review
    )
    assert cfg and cfg["_evidence_retry"] == 1


# ── LLM review (mocked, no network) ─────────────────────────────────────────


def test_llm_review_parses_structured_json_and_rewrites() -> None:
    from hevi.canvas import llm_review

    async def fake_caller(**kwargs):
        prompt = kwargs["messages"][0]["content"]
        if "审阅" in prompt:
            return {"content": '{"result":"fail","issues":["空泛"],"suggested_prompt":"写具体一点"}'}
        return {"content": "这是一段重写后的、具体可读的口播文本。"}

    reviewer = llm_review._reviewer_factory("mock", fake_caller)
    rewriter = llm_review._rewriter_factory("mock", fake_caller)
    review = reviewer("这段很空泛。", {})
    assert review["result"] == "fail"
    assert review["issues"] == ["空泛"]
    assert review["suggested_prompt"] == "写具体一点"
    assert review["model"].endswith("/mock")
    rewritten = rewriter("这段很空泛。", "写具体一点", {})
    assert rewritten.startswith("这是一段重写后的")


def test_llm_review_non_json_is_warn_not_crash() -> None:
    from hevi.canvas import llm_review

    async def fake_caller(**kwargs):
        return {"content": "我觉得还行"}

    reviewer = llm_review._reviewer_factory("mock", fake_caller)
    review = reviewer("文本", {})
    assert review["result"] == "warn"
    assert review["issues"]


@pytest.mark.asyncio
async def test_failing_llm_review_rewrites_node_once() -> None:
    graph = _graph()
    store = InMemoryNodeStore()
    await store.sync_graph("g1", graph["nodes"], graph["edges"])
    seen: list[str] = []
    calls: list[str] = []
    fake_exec = _fake_koubo_executor([])

    async def execute(node, upstream):
        calls.append(node.node_id)
        cfg = node.config or {}
        if str(cfg.get("koubo_step")) == "script":
            seen.append(str(cfg.get("content") or ""))
        return await fake_exec(node, upstream)

    reviews: dict[str, int] = {}

    def reviewer(node, output, **kwargs):
        if str((node.get("config") or {}).get("koubo_step")) == "script":
            reviews["script"] = reviews.get("script", 0) + 1
            if reviews["script"] == 1:
                return {"result": "fail", "reasons": ["太干"], "suggested_prompt": "加细节",
                        "review_mode": "llm", "model": "mock/llm"}
        return {"result": "pass", "reasons": [], "suggested_prompt": "",
                "review_mode": "llm", "model": "mock/llm"}

    def rewriter(text, suggestion, cfg):
        return text + "补充一个具体细节。"

    engine = IncrementalExecutor(store, executor=execute, reviewer=reviewer)
    result = await engine.execute(
        "g1", graph,
        options=ExecuteOptions(scope="dirty", llm_reviewer=reviewer, llm_rewriter=rewriter),
    )
    assert result["retries"].get("script") == 1
    assert any("补充一个具体细节" in text for text in seen)
    state = await store.get_node("g1", "script")
    assert state is not None and state.status == "ok"


# ── API route ordering (no DB) ───────────────────────────────────────────────


class _MiniGraphRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        self.rows[str(data["id"])] = data
        return data

    async def get(self, graph_id: str) -> dict[str, Any] | None:
        return self.rows.get(str(graph_id))

    async def update(self, graph_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        row = self.rows.get(str(graph_id))
        if row is not None:
            row.update(updates)
        return row

    async def list_graphs(self, *, user_id: str | None = None, limit: int = 100):
        return list(self.rows.values())

    async def delete(self, graph_id: str) -> bool:
        return bool(self.rows.pop(str(graph_id), None))


@pytest.mark.asyncio
async def test_koubo_template_route_creates_parallel_nodes(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.canvas import get_current_user, get_graph_service

    store = InMemoryNodeStore()
    svc = GraphService(_MiniGraphRepo(), node_store=store)
    app.dependency_overrides[get_graph_service] = lambda: svc
    app.dependency_overrides[get_current_user] = lambda: {"id": "test-user"}
    try:
        resp = await client.post(
            "/api/canvas/templates/koubo",
            json={"topic": "测试口播", "script_text": "第一句。第二句。", "duration_s": 5},
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["graph_id"]
    keys = [n["node_id"] for n in body["nodes"]]
    assert keys[:2] == ["script", "sentences"]
    assert keys[-3:] == ["edit", "subtitle", "final"]
    assert "tts_1" in keys and "segment_2" in keys
    assert body["nodes"][0]["status"] == "pending"
    assert len(body["edges"]) > len(keys)
    assert len([e for e in body["edges"] if e["to_node_id"] == "edit"]) == 2
