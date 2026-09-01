"""VideoAgent 能力内化的合同、证据和事务测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from hevi.montage.omodul.video_agent import (
    VideoEvidenceConfig,
    video_agent_transaction,
    video_evidence_index,
    video_evidence_search,
)
from hevi.montage.oprim.video_agent import validate_video_agent_plan
from hevi.montage.oskill.video_agent import build_video_agent_plan
from hevi.studio.tools import get_tool


def test_video_agent_plan_is_typed_and_reflectable(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"local media")
    plan = asyncio.run(
        build_video_agent_plan(
            "从本地视频找出产品展示片段，剪成 9:16 的 30 秒短片",
            source_path=str(source),
            input_data={
                "source_path": str(source),
                "script_lines": [{"text": "产品展示", "duration_s": 3}],
                "target_duration_s": 30,
                "aspect_ratio": "9:16",
            },
        )
    )
    assert plan.feasibility == "Feasible"
    assert validate_video_agent_plan(plan) == []
    assert {node.tool_id for node in plan.nodes} >= {
        "video.evidence.index",
        "video.evidence.search",
        "nle.edit_plan",
        "timeline.export",
    }
    assert any(edge.source_port == "evidence_refs" for edge in plan.edges)


def test_video_agent_missing_source_is_recoverable() -> None:
    plan = asyncio.run(build_video_agent_plan("回答视频里出现了什么"))
    assert plan.feasibility == "NeedsInput"
    assert "source_path 或 evidence_index_path" in plan.intent.missing_inputs


def test_video_evidence_index_and_search_return_traceable_refs(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"local media")
    output_dir = tmp_path / "evidence"
    segments = [
        {"segment_id": "s1", "start_s": 0, "end_s": 3, "transcript": "a dog runs", "caption": "dog"},
        {"segment_id": "s2", "start_s": 3, "end_s": 6, "transcript": "a cat sleeps", "caption": "cat"},
    ]
    indexed = asyncio.run(
        video_evidence_index(
            VideoEvidenceConfig(),
            {"source_path": str(source), "segments": segments},
            output_dir,
        )
    )
    assert indexed["status"] == "completed"
    assert Path(indexed["index_path"]).is_file()
    assert Path(indexed["manifest_path"]).is_file()

    searched = asyncio.run(
        video_evidence_search(
            None,
            {"index_path": indexed["index_path"], "query": "dog"},
            output_dir,
        )
    )
    assert searched["status"] == "completed"
    assert searched["evidence_refs"]
    ref = searched["evidence_refs"][0]
    assert ref["source_sha256"]
    assert ref["segment_id"] == "s1"
    assert ref["start_s"] == 0
    assert ref["end_s"] == 3


def test_semantic_search_blocks_without_transcript_or_caption(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"local media")
    output_dir = tmp_path / "evidence"
    indexed = asyncio.run(
        video_evidence_index(
            None,
            {
                "source_path": str(source),
                "segments": [{"segment_id": "s1", "start_s": 0, "end_s": 2}],
            },
            output_dir,
        )
    )
    assert indexed["status"] == "planned"
    searched = asyncio.run(
        video_evidence_search(None, {"index_path": indexed["index_path"], "query": "dog"}, output_dir)
    )
    assert searched["status"] == "blocked"
    assert searched["evidence_refs"] == []


def test_video_agent_transaction_planning_is_local_and_non_destructive(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"local media")
    result = asyncio.run(
        video_agent_transaction(
            {"execute": False},
            {
                "requirement": "把本地视频剪成短片",
                "source_path": str(source),
                "script_lines": [{"text": "开场", "duration_s": 2}],
            },
            tmp_path / "run",
        )
    )
    assert result["status"] == "planned"
    assert Path(result["plan_path"]).is_file()
    assert Path(result["report_path"]).is_file()
    assert get_tool("video.agent.plan") is not None
    assert get_tool("video.evidence.index") is not None


def test_video_agent_transaction_executes_through_injected_hevi_ports(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"local media")
    calls: list[tuple[str, dict]] = []

    async def executor(tool_id: str, arguments: dict) -> dict:
        calls.append((tool_id, arguments))
        if tool_id == "watch.video":
            return {"status": "ok", "watch": {}, "transcript": ""}
        if tool_id == "nle.edit_plan":
            assert arguments["materials"][0]["source_path"] == str(source)
            return {"status": "ok", "edit_plan": {"cuts": []}}
        if tool_id == "timeline.create":
            return {"status": "ok", "timeline": {"timeline_id": "test-timeline"}}
        if tool_id == "timeline.export":
            output = Path(arguments["output_path"])
            output.write_bytes(b"real local artifact")
            return {"status": "ok", "video_path": str(output)}
        raise AssertionError(f"unexpected tool: {tool_id}")

    result = asyncio.run(
        video_agent_transaction(
            {"execute": True},
            {
                "requirement": "把本地视频剪成短片",
                "source_path": str(source),
                "script_lines": [{"text": "开场", "duration_s": 2}],
                "segments": [
                    {"segment_id": "s1", "start_s": 0, "end_s": 2, "caption": "开场"},
                ],
                "executor": executor,
            },
            tmp_path / "run",
        )
    )
    assert result["status"] == "completed"
    assert Path(result["artifact_manifest"]["artifacts"][0]["path"]).is_file()
    assert [tool_id for tool_id, _ in calls] == [
        "watch.video",
        "nle.edit_plan",
        "timeline.create",
        "timeline.export",
    ]
