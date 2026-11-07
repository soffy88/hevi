"""Tests for video.step_segmentation (clean-room, placeholder data only).

Pure logic is tested without ffmpeg. The ffmpeg tests build their own
synthetic video with the system ffmpeg and are skipped honestly when
ffmpeg or ffprobe is unavailable. No downloaded video, no third-party
material, and no real titles are used anywhere here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.capabilities import names as capability_names
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.video_step_segmentation import (
    CAPABILITY_NAME,
    build_step_segmentation,
    build_title,
    enforce_durations,
    group_segments,
    require_rights,
    select_visual_checks,
    step_confidence,
    validate_segments,
)

RIGHTS = {"source": "placeholder local file", "basis": "own_recording", "publish": False}

MODULE_PATH = Path(__file__).resolve().parents[1] / "hevi" / "capabilities" / "video_step_segmentation.py"


def _seg(start: float, end: float, text: str = "placeholder words", conf=None) -> dict:
    seg = {"start": start, "end": end, "text": text}
    if conf is not None:
        seg["confidence"] = conf
    return seg


def test_capability_is_registered_on_package_import() -> None:
    assert CAPABILITY_NAME in capability_names()


def test_module_has_no_network_or_upstream_imports() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    for banned in (
        "urllib",
        "requests",
        "socket",
        "yt_dlp",
        "yt-dlp",
        "volcengine",
        "doubao",
        "whisper",
        "weasyprint",
    ):
        assert banned not in source, f"banned token present: {banned}"


def test_rights_refused_when_missing_or_empty() -> None:
    with pytest.raises(CapabilityError):
        require_rights(None)
    with pytest.raises(CapabilityError):
        require_rights({"source": "", "basis": "own_recording"})
    with pytest.raises(CapabilityError):
        require_rights({"source": "somewhere", "basis": "  "})
    assert require_rights(RIGHTS)["publish"] is False


def test_grouping_splits_on_gap_threshold() -> None:
    segments = [
        _seg(0.0, 1.0),
        _seg(1.5, 2.5),
        _seg(5.0, 6.0),
        _seg(6.2, 7.0),
    ]
    groups = group_segments(segments, gap_threshold=2.0)
    assert len(groups) == 2
    assert len(groups[0]) == 2
    assert len(groups[1]) == 2
    groups = group_segments(segments, gap_threshold=3.0)
    assert len(groups) == 1


def test_grouping_gap_exactly_at_threshold_splits() -> None:
    segments = [_seg(0.0, 1.0), _seg(3.0, 4.0)]
    assert len(group_segments(segments, gap_threshold=2.0)) == 2


def test_enforce_durations_splits_long_step_at_boundaries() -> None:
    segments = [_seg(0.0, 4.0), _seg(4.0, 8.0), _seg(8.0, 12.0)]
    groups, flags = enforce_durations(
        [segments], min_step_duration=3.0, max_step_duration=10.0
    )
    assert len(groups) == 2
    assert flags[0] == ["split_for_max_duration"]
    assert groups[0][0]["start"] == 0.0 and groups[1][0]["start"] == 8.0


def test_enforce_durations_keeps_single_overlong_segment_whole() -> None:
    segments = [_seg(0.0, 30.0)]
    groups, flags = enforce_durations(
        [segments], min_step_duration=3.0, max_step_duration=10.0
    )
    assert len(groups) == 1
    assert "exceeds_max_duration" in flags[0]


def test_enforce_durations_merges_short_step_forward() -> None:
    groups, flags = enforce_durations(
        [[_seg(0.0, 1.0)], [_seg(5.0, 9.0)]],
        min_step_duration=3.0,
        max_step_duration=60.0,
    )
    assert len(groups) == 1
    assert "merged_for_min_duration" in flags[0]


def test_step_confidence_mean_and_estimated_flag() -> None:
    members = [_seg(0.0, 1.0, conf=0.9), _seg(1.0, 2.0, conf=0.5)]
    mean, estimated = step_confidence(members)
    assert mean == pytest.approx(0.7)
    assert estimated is False
    mean, estimated = step_confidence([_seg(0.0, 1.0, conf=0.9), _seg(1.0, 2.0)])
    assert mean == pytest.approx(0.7)
    assert estimated is True


def test_build_title_is_plain_prefix() -> None:
    members = [_seg(0.0, 1.0, text="alpha beta"), _seg(1.0, 2.0, text="gamma delta")]
    assert build_title(members, max_chars=40) == "alpha beta gamma delta"
    assert build_title(members, max_chars=5) == "alpha"


def test_select_visual_checks_lowest_first_tie_earliest() -> None:
    steps = [
        {"confidence": 0.5, "start": 10.0, "needs_visual_check": True},
        {"confidence": 0.5, "start": 2.0, "needs_visual_check": True},
        {"confidence": 0.9, "start": 0.0, "needs_visual_check": False},
        {"confidence": 0.2, "start": 20.0, "needs_visual_check": True},
    ]
    assert select_visual_checks(steps, confidence_threshold=0.7, budget=2) == [4, 2]
    assert select_visual_checks(steps, confidence_threshold=0.7, budget=0) == []
    with pytest.raises(CapabilityError):
        select_visual_checks(steps, confidence_threshold=0.7, budget=9)


def test_validate_segments_refusals() -> None:
    with pytest.raises(CapabilityError):
        validate_segments([], 60.0)
    with pytest.raises(CapabilityError):
        validate_segments([_seg(5.0, 4.0)], 60.0)
    with pytest.raises(CapabilityError):
        validate_segments([_seg(0.0, 2.0), _seg(1.0, 3.0)], 60.0)
    with pytest.raises(CapabilityError):
        validate_segments([_seg(0.0, 61.0)], 60.0)
    with pytest.raises(CapabilityError):
        validate_segments([_seg(0.0, 1.0, conf=1.5)], 60.0)
    with pytest.raises(CapabilityError):
        validate_segments([_seg(-1.0, 1.0)], 60.0)
    ok = validate_segments([_seg(0.0, 1.0), _seg(1.0, 2.0)], 60.0)
    assert len(ok) == 2


def _make_synthetic_video(path: Path, duration: float = 6.0) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=duration={duration}:size=320x240:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        capture_output=True,
        check=True,
        timeout=120,
    )


@pytest.fixture()
def synthetic_video(tmp_path: Path) -> Path:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not available")
    video = tmp_path / "synthetic.mp4"
    _make_synthetic_video(video)
    return video


def test_build_end_to_end_unreviewed_flags_and_frames(
    synthetic_video: Path, tmp_path: Path
) -> None:
    segments = [
        _seg(0.0, 1.0, "first placeholder line", conf=0.9),
        _seg(1.2, 2.0, "second placeholder line", conf=0.9),
        _seg(4.5, 5.5, "third placeholder line", conf=0.2),
    ]
    result = build_step_segmentation(
        str(synthetic_video),
        segments,
        RIGHTS,
        tmp_path / "out",
        min_step_duration=0.5,
    )
    steps = result["steps"]
    assert len(steps) == 2
    assert all(step["transcript_unverified"] is True for step in steps)
    assert steps[0]["needs_visual_check"] is False
    assert steps[1]["needs_visual_check"] is True
    assert steps[1]["visual_check"] is not None
    assert steps[1]["visual_check"]["status"] == "awaiting_human_check"
    frame = Path(steps[1]["visual_check"]["frame"])
    assert frame.is_file() and frame.stat().st_size > 0
    assert steps[0]["visual_check"] is None
    steps_path = result["steps_path"]
    assert steps_path.is_file()
    payload = json.loads(steps_path.read_text(encoding="utf-8"))
    assert payload["transcript_reviewed"] is False
    manifest = result["manifest"]
    assert manifest["rights"] == RIGHTS
    assert manifest["tool_versions"]["ffmpeg"]
    assert manifest["step_count"] == 2


def test_build_reviewed_transcript_clears_unverified_flag(
    synthetic_video: Path, tmp_path: Path
) -> None:
    segments = [_seg(0.0, 1.0, "only placeholder line", conf=0.9)]
    result = build_step_segmentation(
        str(synthetic_video),
        segments,
        RIGHTS,
        tmp_path / "out",
        transcript_reviewed=True,
        visual_check_budget=0,
    )
    assert result["steps"][0]["transcript_unverified"] is False
    assert result["steps"][0]["visual_check"] is None


def test_build_language_tag_passes_through(
    synthetic_video: Path, tmp_path: Path
) -> None:
    segments = [_seg(0.0, 1.0, "placeholder line", conf=0.9)]
    result = build_step_segmentation(
        str(synthetic_video),
        segments,
        RIGHTS,
        tmp_path / "out",
        language="placeholder-lang",
        visual_check_budget=0,
    )
    assert result["manifest"]["language"] == "placeholder-lang"


def test_build_refuses_without_rights(
    synthetic_video: Path, tmp_path: Path
) -> None:
    segments = [_seg(0.0, 1.0, "placeholder line", conf=0.9)]
    with pytest.raises(CapabilityError):
        build_step_segmentation(
            str(synthetic_video), segments, None, tmp_path / "out"
        )


def test_build_refuses_overwrite_without_flag(
    synthetic_video: Path, tmp_path: Path
) -> None:
    segments = [_seg(0.0, 1.0, "placeholder line", conf=0.9)]
    out = tmp_path / "out"
    build_step_segmentation(
        str(synthetic_video), segments, RIGHTS, out, visual_check_budget=0
    )
    with pytest.raises(CapabilityError):
        build_step_segmentation(
            str(synthetic_video), segments, RIGHTS, out, visual_check_budget=0
        )
    build_step_segmentation(
        str(synthetic_video),
        segments,
        RIGHTS,
        out,
        visual_check_budget=0,
        overwrite=True,
    )


def test_build_rejects_inconsistent_duration_limits(
    synthetic_video: Path, tmp_path: Path
) -> None:
    segments = [_seg(0.0, 1.0, "placeholder line", conf=0.9)]
    with pytest.raises(CapabilityError):
        build_step_segmentation(
            str(synthetic_video),
            segments,
            RIGHTS,
            tmp_path / "out",
            min_step_duration=30.0,
            max_step_duration=10.0,
        )


def test_render_entry_point_returns_report(
    synthetic_video: Path, tmp_path: Path
) -> None:
    from hevi.capabilities.registry import get as get_capability

    capability = get_capability(CAPABILITY_NAME)
    result = capability.render_safe(
        {
            "video_path": str(synthetic_video),
            "segments": [_seg(0.0, 1.0, "placeholder line", conf=0.9)],
            "rights": RIGHTS,
            "visual_check_budget": 0,
        },
        tmp_path / "render-out",
        duration=6.0,
        aspect="16:9",
        seed=1,
    )
    assert result.sha256
    assert Path(result.qa["report_json"]).is_file()
    assert result.qa["step_count"] == 1
