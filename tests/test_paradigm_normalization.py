"""Paradigm-normalization tests (stage 3): the 34-item audit list, by item.

Covers the behaviour changes that are cheap to pin down without any
paid API, Blender session, or database: new-capability reports,
schema locks, bundle passed, chain errors, gates ffmpeg-pending,
novel write-root rules, registry overwrite guard, preview semantics,
and the /canvas workflow routes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from hevi.capabilities import get as cap_get
from hevi.capabilities import registry
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    overwrite_history,
    register,
)

# ---------------------------------------------------------------------------
# New capabilities (M-01..M-05): report + sha + delete-breaks
# ---------------------------------------------------------------------------

NEW_CAP_CASES: list[tuple[str, dict[str, Any]]] = [
    (
        "story.shot_chain",
        {"shots": [{"shot_id": "S1"}, {"shot_id": "S2"}]},
    ),
    (
        "story.reference_bundle",
        {
            "shot": {"shot_id": "S1", "character_ids": ["C1"]},
            "asset_registry": {"C1": {"kind": "character", "block": "C1 block"}},
        },
    ),
    (
        "story.canvas_workflow",
        {
            "nodes": [
                {"node_id": "s1", "type": "script"},
                {"node_id": "v1", "type": "video", "inputs": ["s1"]},
            ],
            "selected_ids": ["v1"],
        },
    ),
    (
        "story.novel_import",
        {
            "chapters": [
                {
                    "chapter_no": 1,
                    "title": "第一章",
                    "text": "第一段。\n\n第二段。\n\n第三段。\n\n第四段。",
                }
            ],
            "episodes_per_chapter": 2,
        },
    ),
    (
        "story.narration_srt",
        {
            "shots": [
                {"shot_id": "S1", "duration": 2.0, "dialogue": "你好", "narration": "旁白"},
            ]
        },
    ),
]


@pytest.mark.parametrize("name,params", NEW_CAP_CASES)
def test_new_capability_report_and_sha(tmp_path: Path, name: str, params: dict) -> None:
    cap = cap_get(name)
    assert cap.has_media_output is False
    result = cap.render_safe(params, tmp_path, duration=0.0, aspect="16:9", seed=42)
    report_path = Path(result.qa["report_json"])
    assert report_path.is_file()
    assert result.sha256 == registry.compute_sha256(report_path)
    # Contract "delete the product, verification must fail" (report form).
    report_path.unlink()
    with pytest.raises(CapabilityError):
        registry.compute_sha256(report_path)


@pytest.mark.parametrize("name,params", NEW_CAP_CASES)
def test_new_capability_rejects_bogus_param(name: str, params: dict) -> None:
    cap = cap_get(name)
    bad = dict(params)
    bad["bogus_param_xyz"] = 1
    with pytest.raises(CapabilityError):
        cap.validate_params(bad)


def test_canvas_workflow_render_includes_rerun_plan(tmp_path: Path) -> None:
    cap = cap_get("story.canvas_workflow")
    result = cap.render_safe(
        {
            "nodes": [
                {"node_id": "s1", "type": "script"},
                {"node_id": "v1", "type": "video", "inputs": ["s1"]},
            ],
            "selected_ids": ["v1"],
        },
        tmp_path,
        duration=0.0,
        aspect="16:9",
        seed=42,
    )
    assert result.qa["rerun_order"] == ["s1", "v1"]
    assert result.qa["node_count"] == 2


def test_novel_import_division_of_labour(tmp_path: Path) -> None:
    # story.novel_import maps a finished book; it never invents a synopsis.
    cap = cap_get("story.novel_import")
    result = cap.render_safe(
        {
            "chapters": [
                {"chapter_no": 1, "title": "楔子", "text": "首段梗概。\n\n次段。\n\n三段。\n\n四段。"}
            ]
        },
        tmp_path,
        duration=0.0,
        aspect="16:9",
        seed=42,
    )
    episodes = result.qa["episodes"]
    assert len(episodes) == 2
    assert episodes[0]["synopsis"] == "首段梗概。"


# ---------------------------------------------------------------------------
# C-01: schema locks on the six previously open capabilities
# ---------------------------------------------------------------------------

LOCKED_CAPS: list[tuple[str, dict[str, Any]]] = [
    ("story.episode_prompts", {"bible": {}, "episode": {}}),
    ("story.drama_gates", {"prompt_package": {}}),
    ("story.reference_decompose", {"transcript": "x"}),
    ("story.edit_assemble", {"clips": []}),
    ("story.model_test", {"test_set": {}}),
    ("video.blender_mcp", {"code": "import bpy"}),
]


@pytest.mark.parametrize("name,params", LOCKED_CAPS)
def test_locked_schema_rejects_typo_param(name: str, params: dict) -> None:
    cap = cap_get(name)
    assert cap.params_schema.get("additionalProperties") is False
    bad = dict(params)
    bad["budge"] = 1  # the audit's typo example: must not silently pass
    with pytest.raises(CapabilityError):
        cap.validate_params(bad)


def test_reference_decompose_accepts_string_shot_list() -> None:
    cap = cap_get("story.reference_decompose")
    cap.validate_params({"shot_list": "镜1\n镜2", "mode": "deterministic"})


# ---------------------------------------------------------------------------
# C-06: bundle passed is False on any [缺失], True when clean
# ---------------------------------------------------------------------------

_CLEAN_REGISTRY = {"C1": {"kind": "character", "block": "C1 block"}}


def test_bundle_passed_false_on_missing_block(tmp_path: Path) -> None:
    cap = cap_get("story.reference_bundle")
    result = cap.render_safe(
        {
            "shot": {"shot_id": "S1", "character_ids": ["C1"], "prop_ids": ["P9"]},
            "asset_registry": _CLEAN_REGISTRY,
        },
        tmp_path,
        duration=0.0,
        aspect="16:9",
        seed=42,
    )
    assert result.qa["passed"] is False
    assert any(ref["block"] == "[缺失]" for ref in result.qa["references"])


def test_bundle_passed_true_when_clean(tmp_path: Path) -> None:
    cap = cap_get("story.reference_bundle")
    result = cap.render_safe(
        {
            "shot": {"shot_id": "S1", "character_ids": ["C1"]},
            "asset_registry": _CLEAN_REGISTRY,
        },
        tmp_path,
        duration=0.0,
        aspect="16:9",
        seed=42,
    )
    assert result.qa["passed"] is True


# ---------------------------------------------------------------------------
# C-07: non-dict chain links are errors, not skips
# ---------------------------------------------------------------------------

def test_validate_chain_non_dict_link_is_error() -> None:
    from hevi.capabilities.shot_chain import validate_chain

    issues = validate_chain([{"shot_id": "S1"}, "not-a-dict"])
    assert any(
        i["severity"] == "error" and i["code"] == "non_dict_link" for i in issues
    )


# ---------------------------------------------------------------------------
# C-08: gates treat ffmpeg pending as pending (not passed, not blocker)
# ---------------------------------------------------------------------------

def test_gates_ffmpeg_pending_is_pending_not_passed(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "tdg", str(Path(__file__).resolve().parents[1] / "tests" / "test_drama_gates.py")
    )
    tdg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tdg)
    pkg = tdg._clean_package()
    params = tdg._gates_params(
        pkg,
        edit_report={
            "edit_ready": True,
            "findings": [],
            "ffmpeg": {"status": "pending", "reason": "no subtitle_file"},
        },
    )
    _, report = tdg._run(params, tmp_path)
    assert report["checks"]["edit_ready"] == {"passed": None, "status": "pending"}
    assert report["counts"]["pending"] >= 1
    assert "edit_ready" not in report["failed_checks"]


# ---------------------------------------------------------------------------
# C-05: novel write-root rules (unit level; end-to-end covered by
# test_novelpipeline.py's absolute-path cases, which must keep passing)
# ---------------------------------------------------------------------------

def test_novel_relative_book_dir_resolves_under_out_dir(tmp_path: Path) -> None:
    from hevi.capabilities.novelpipeline import _resolve_book_dir

    out_dir = tmp_path / "job"
    out_dir.mkdir()
    resolved = _resolve_book_dir({"book_dir": "mybook"}, out_dir, name="novel.create")
    assert resolved == (out_dir / "mybook").resolve()


def test_novel_absolute_root_and_home_rejected(tmp_path: Path) -> None:
    from hevi.capabilities.novelpipeline import _resolve_book_dir

    with pytest.raises(CapabilityError):
        _resolve_book_dir({"book_dir": "/"}, tmp_path, name="novel.create")
    with pytest.raises(CapabilityError):
        _resolve_book_dir({"book_dir": str(Path.home())}, tmp_path, name="novel.create")
    existing_file = tmp_path / "afile.txt"
    existing_file.write_text("x", encoding="utf-8")
    with pytest.raises(CapabilityError):
        _resolve_book_dir({"book_dir": str(existing_file)}, tmp_path, name="novel.create")


def test_novel_write_chapter_without_book_json_is_capability_error(tmp_path: Path) -> None:
    import hevi.capabilities.novelpipeline as novel_caps

    novel_caps.set_llm_fn(lambda prompt, kind: "x")
    try:
        cap = cap_get("novel.write_chapter")
        with pytest.raises(CapabilityError, match="book.json"):
            cap.render_safe(
                {"book_dir": str(tmp_path / "nobook")},
                tmp_path / "job",
                duration=0.0,
                aspect="16:9",
                seed=42,
            )
    finally:
        novel_caps.set_llm_fn(None)


# ---------------------------------------------------------------------------
# S-09: registry default refuses overwrite; explicit overwrite is audited
# ---------------------------------------------------------------------------

def test_register_default_refuses_duplicate_and_audit_trail() -> None:
    dummy_name = "test.paradigm_dummy"

    def _render(params, out_dir, *, duration, aspect, seed):
        return CapabilityResult(duration_s=0.0, qa={})

    first = Capability(
        name=dummy_name, kind="line", aspects=["16:9"],
        params_schema={"type": "object"}, cpu_cost_hint=0.0, render=_render,
    )
    # The dummy may already exist if this test ran before in-process;
    # clear it via explicit overwrite so the sequence below is exact.
    register(first, overwrite=True)
    with pytest.raises(CapabilityError, match="already registered"):
        register(first)
    register(first, overwrite=True)
    assert any(entry["name"] == dummy_name for entry in overwrite_history())


# ---------------------------------------------------------------------------
# M-15 / M-17 / S-03: preview semantics
# ---------------------------------------------------------------------------

def test_preview_report_capability_returns_json_not_mp4(tmp_path: Path) -> None:
    from hevi.api.routers.capabilities import preview_capability_endpoint

    resp = preview_capability_endpoint(
        "story.season_bible",
        params={
            "title": "T", "premise": "P", "worldview": "W",
            "characters": [], "scenes": [], "props": [],
            "visual_locks": {}, "tone_style": {},
        },
        aspect="16:9",
        seed=42,
    )
    assert resp.status_code == 200
    body = json.loads(resp.body.decode("utf-8"))
    assert body["kind"] == "report"
    assert body["qa"]["title"] == "T"
    assert body["sha256"]


def test_preview_report_capability_exempt_from_aspect_check() -> None:
    from hevi.api.routers.capabilities import preview_capability_endpoint

    # 4:3 is not in the declared aspects, but report renders ignore
    # aspect, so preview must not 422 (S-03).
    resp = preview_capability_endpoint(
        "story.season_bible",
        params={
            "title": "T", "premise": "P", "worldview": "W",
            "characters": [], "scenes": [], "props": [],
            "visual_locks": {}, "tone_style": {},
        },
        aspect="4:3",
        seed=42,
    )
    assert resp.status_code == 200


def test_preview_blender_mcp_always_restricted() -> None:
    from hevi.api.routers.capabilities import preview_capability_endpoint

    cap = cap_get("video.blender_mcp")
    assert cap.preview_restricted is True
    with pytest.raises(HTTPException) as excinfo:
        preview_capability_endpoint(
            "video.blender_mcp", params={"code": "import bpy"}, aspect="16:9", seed=42
        )
    assert excinfo.value.status_code == 422
    assert "restricted" in excinfo.value.detail


def test_preview_unknown_capability_404() -> None:
    from hevi.api.routers.capabilities import preview_capability_endpoint

    with pytest.raises(HTTPException) as excinfo:
        preview_capability_endpoint("no.such_cap", params={}, aspect="16:9", seed=42)
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# M-14: /canvas workflow routes (auth + services faked, no DB)
# ---------------------------------------------------------------------------

_WORKFLOW = {
    "nodes": [
        {"node_id": "s1", "type": "script"},
        {"node_id": "v1", "type": "video", "inputs": ["s1"]},
    ]
}


def _client_with_overrides(overrides: dict):
    from hevi.api.main import app

    for key, value in overrides.items():
        app.dependency_overrides[key] = value
    client = TestClient(app)
    return app, client


def test_canvas_workflow_to_graph_and_planned_graph_routes() -> None:
    from hevi.api.routers.canvas import get_graph_service
    from hevi.auth.dependencies import get_current_user

    app, client = _client_with_overrides(
        {get_current_user: lambda: {"id": "u1", "is_active": True}}
    )
    try:
        resp = client.post("/api/canvas/workflow-to-graph", json={"workflow": _WORKFLOW})
        assert resp.status_code == 200, resp.text
        graph = resp.json()["graph"]
        assert {n["node_id"] for n in graph["nodes"]} == {"s1", "v1"}
        assert resp.json()["edge_warnings"] == []
        resp = client.post(
            "/api/canvas/planned-graph",
            json={"source": _WORKFLOW, "selected_ids": ["v1"]},
        )
        assert resp.status_code == 200, resp.text
        plan = resp.json()["plan"]
        assert [p["node_id"] for p in plan] == ["s1", "v1"]
        resp = client.post("/api/canvas/workflow-preflight", json={"workflow": _WORKFLOW})
        assert resp.status_code == 200, resp.text
        assert resp.json()["passed"] is True
        resp = client.post(
            "/api/canvas/workflow-to-graph", json={"workflow": {"nodes": []}}
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_canvas_workflow_execute_delegates_to_executor_service() -> None:
    from hevi.api.routers.canvas import get_executor_service, get_graph_service
    from hevi.auth.dependencies import get_current_user

    svc = AsyncMock()
    svc.save_graph.return_value = {"graph_id": "g1"}
    svc.load_graph.return_value = {"user_id": "u1", "nodes_json": [], "edges_json": []}
    exe = AsyncMock()
    exe.execute_graph.return_value = {"graph_id": "g1", "status": "completed"}
    app, client = _client_with_overrides(
        {
            get_current_user: lambda: {"id": "u1", "is_active": True},
            get_graph_service: lambda: svc,
            get_executor_service: lambda: exe,
        }
    )
    try:
        resp = client.post(
            "/api/canvas/workflow-execute",
            json={"workflow": _WORKFLOW, "name": "W"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "completed"
        svc.save_graph.assert_awaited_once()
        saved_kwargs = svc.save_graph.await_args.kwargs
        assert saved_kwargs["user_id"] == "u1"
        assert {n["node_id"] for n in saved_kwargs["nodes"]} == {"s1", "v1"}
        exe.execute_graph.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()
