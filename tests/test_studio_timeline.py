"""ChatCut 时间线:从 edit_plan 生成、改动作、重导出。"""

from __future__ import annotations

from pathlib import Path

from hevi.studio.timeline import (
    export_timeline,
    patch_clip,
    reset_timelines,
    ripple,
    set_bgm,
    split_at,
    timeline_from_edit_plan,
)


def setup_function() -> None:
    reset_timelines()


def test_timeline_from_plan_and_patch(tmp_path: Path) -> None:
    tl = timeline_from_edit_plan(
        {
            "cuts": [
                {"start_s": 0, "duration_s": 3, "text": "钩子", "visual": str(tmp_path / "a.mp4")},
                {"start_s": 3, "duration_s": 4, "text": "展开"},
            ]
        },
        title="盐税",
    )
    assert tl.duration_s >= 7
    assert len(tl.tracks["video"]) == 2
    assert len(tl.tracks["captions"]) == 2
    patched = patch_clip(tl.timeline_id, "v1", action="drop")
    assert patched is not None
    assert next(c.action for c in patched.clips if c.clip_id == "v1") == "drop"
    assert set_bgm(tl.timeline_id, "warm") is not None
    (tmp_path / "a.mp4").write_bytes(b"x")
    out = export_timeline(tl.timeline_id, tmp_path / "out.mp4")
    assert out["status"] in {"ok", "failed"}


def test_split_and_ripple() -> None:
    tl = timeline_from_edit_plan(
        {
            "cuts": [
                {"start_s": 0, "duration_s": 6, "text": "钩子"},
                {"start_s": 6, "duration_s": 4, "text": "展开"},
            ]
        }
    )
    video_before = len(tl.tracks["video"])
    split = split_at(tl.timeline_id, 3.0)
    assert split is not None
    assert len(split.tracks["video"]) == video_before + 1
    patch_clip(tl.timeline_id, "v0", action="drop")
    packed = ripple(tl.timeline_id)
    assert packed is not None
    kept = sorted(
        (c for c in packed.tracks["video"] if c.action != "drop"),
        key=lambda c: c.start_s,
    )
    assert kept
    assert kept[0].start_s == 0.0
