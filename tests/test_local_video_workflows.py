"""Regression tests for the newly executable AI-Shorts/FireRed/Shotcraft paths."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from hevi.motion.recipe_card import build_shotcraft_library, card_index, validate_library
from hevi.studio.conversational_edit import execute_edit, parse_edit_command
from hevi.studio.timeline import reset_timelines, timeline_from_edit_plan


def setup_function() -> None:
    reset_timelines()


def test_shotcraft_runtime_catalog_is_complete() -> None:
    library = build_shotcraft_library()
    assert len(library) == 152
    assert validate_library(library) == []
    assert sum(len(items) for items in card_index(library).values()) == 152


def test_conversational_edit_preview_then_apply() -> None:
    timeline = timeline_from_edit_plan(
        {
            "cuts": [
                {"start_s": 0, "duration_s": 3, "text": "第一镜"},
                {"start_s": 3, "duration_s": 3, "text": "第二镜"},
            ]
        }
    )
    assert parse_edit_command("删除第2镜").operation == "drop"
    assert parse_edit_command("撤销删除第2镜").operation == "keep"
    preview = execute_edit(timeline.timeline_id, "删除第2镜", preview=True)
    assert preview["status"] == "preview"
    assert preview["timeline"]["tracks"]["video"][1]["action"] == "keep"
    applied = execute_edit(timeline.timeline_id, "把第1镜字幕改成‘新字幕’")
    assert applied["status"] == "applied"
    assert applied["timeline"]["tracks"]["captions"][0]["text"] == "新字幕"


def test_local_clip_adapter_emits_real_artifact_manifest(tmp_path: Path, monkeypatch) -> None:
    from hevi.openshorts import clip_engine

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    def fake_render(_source, _highlight, destination, *, width, height):
        assert width == 180 and height == 320
        destination.write_bytes(b"mp4")

    monkeypatch.setattr(clip_engine, "_render_one", fake_render)
    result = clip_engine.render_clip_batch(
        source,
        output_dir=tmp_path / "out",
        target_clips=1,
        config={
            "output_width": 180,
            "transcript_segments": [
                {"start": 0, "end": 30, "text": "其实这个方法就是三步，记住这个公式。"}
            ],
        },
    )
    assert result["status"] == "completed"
    assert Path(result["result_video_path"]).is_file()
    manifest = result["config_json"]["artifact_manifest"]
    assert {item["kind"] for item in manifest["artifacts"]} == {"video", "subtitle", "json"}


def test_mpt_adapter_translates_terminal_state(tmp_path: Path, monkeypatch) -> None:
    from hevi.services import mpt_adapter

    video = tmp_path / "mpt.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=16x16:r=2",
            "-t",
            "1",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
        capture_output=True,
    )

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def generate_video(self, _topic, **_kwargs):
            return {"task_id": "mpt-1"}

        async def check_task_status(self, _task_id):
            return {"state": 1, "videos": [str(video)]}

    monkeypatch.setattr(mpt_adapter, "MPTClient", FakeClient)
    result = asyncio.run(
        mpt_adapter.execute_mpt_task(
            {"id": str(uuid4()), "topic": "demo", "config_json": {"mpt_request": {}}},
            MagicMock(),
        )
    )
    assert result["status"] == "completed"
    # The provider is mocked, but the returned artifact is a real media file;
    # the PASS comes from measured ffprobe/quality evidence, not file presence.
    assert result["quality"]["verdict"] == "pass"
    assert result["quality"]["passed"] is True
    assert result["config_json"]["artifact_manifest"]["artifacts"][0]["primary"] is True
