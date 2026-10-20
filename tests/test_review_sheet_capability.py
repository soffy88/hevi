"""Offline tests for the generic review-sheet capability (``qa.review_sheet``).

The sample media is synthesized locally with ffmpeg lavfi sources
(testsrc + sine), so no network and no paid calls.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import hevi.capabilities.review_sheet as review_sheet_cap
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import get, list_capabilities
from hevi.quality.review_sheet import (
    ReviewSheetError,
    fold_events,
    make_comment_id,
    normalize_comments,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)

review_sheet_cap.register_review_sheet_capabilities_once()

_COMMENT = {
    "film": "测试片",
    "shot": 2,
    "timestamp_s": 1.0,
    "scene": "夜市",
    "element": "招牌灯光",
    "comment": "招牌过曝，压一档曝光",
}


def _make_video(path: Path, *, seconds: int = 3) -> Path:
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=10:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(path),
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return path


def _render(params: dict, out_dir: Path):
    cap = get("qa.review_sheet")
    return cap.render(params, out_dir, duration=3.0, aspect="16:9", seed=42)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_registered_visible() -> None:
    names = [c.name for c in list_capabilities(kind="video")]
    assert "qa.review_sheet" in names
    cap = get("qa.review_sheet")
    assert cap.line == "qa"
    assert cap.kind == "video"


# ---------------------------------------------------------------------------
# Record normalisation / event folding (pure)
# ---------------------------------------------------------------------------


def test_comment_list_defaults_to_pending() -> None:
    (record,) = normalize_comments([dict(_COMMENT)])
    assert record["status"] == "pending"
    assert record["comment"] == _COMMENT["comment"]
    assert record["thread"] == []


def test_id_is_deterministic() -> None:
    first = normalize_comments([dict(_COMMENT)])[0]["id"]
    second = normalize_comments([dict(_COMMENT)])[0]["id"]
    assert first == second
    assert first == make_comment_id(
        _COMMENT["film"], _COMMENT["shot"],
        _COMMENT["timestamp_s"], _COMMENT["comment"],
    )
    assert len(first) == 12


def test_events_fold_to_done_with_agent_notes() -> None:
    cid = make_comment_id("片A", 1, 0.5, "开头黑场太长")
    events = [
        {"type": "comment", "film": "片A", "shot": 1, "timestamp_s": 0.5,
         "comment": "开头黑场太长"},
        {"type": "claim", "id": cid, "note": "agent 已认领"},
        {"type": "done", "id": cid, "note": "agent 已裁掉 0.4s"},
    ]
    (record,) = fold_events(events)
    assert record["id"] == cid
    assert record["status"] == "done"
    notes = [entry["note"] for entry in record["thread"]]
    assert "agent 已认领" in notes
    assert "agent 已裁掉 0.4s" in notes


def test_reopen_returns_to_pending() -> None:
    cid = make_comment_id("片A", 1, 0.5, "开头黑场太长")
    events = [
        {"type": "comment", "film": "片A", "shot": 1, "timestamp_s": 0.5,
         "comment": "开头黑场太长"},
        {"type": "claim", "id": cid, "note": "agent 已认领"},
        {"type": "done", "id": cid, "note": "agent 已处理"},
        {"type": "reopen", "id": cid, "note": "复审发现黑场仍偏长"},
    ]
    (record,) = fold_events(events)
    assert record["status"] == "pending"
    assert record["thread"][-1]["type"] == "reopen"


def test_invalid_records_raise_review_sheet_error() -> None:
    with pytest.raises(ReviewSheetError):
        normalize_comments([dict(_COMMENT, status="bogus")])
    with pytest.raises(ReviewSheetError):
        normalize_comments([dict(_COMMENT, comment="  ")])
    with pytest.raises(ReviewSheetError):
        normalize_comments([dict(_COMMENT, timestamp_s=-1.0)])


# ---------------------------------------------------------------------------
# Render: sheet assembly on a synthesized clip
# ---------------------------------------------------------------------------


def test_render_builds_sheet(tmp_path: Path) -> None:
    media = _make_video(tmp_path / "clip.mp4")
    out_dir = tmp_path / "sheet"
    result = _render({"media_path": str(media), "comments": [dict(_COMMENT)]}, out_dir)

    (record_id,) = [normalize_comments([dict(_COMMENT)])[0]["id"]]
    frame = out_dir / "frames" / f"review_{record_id}.png"
    assert frame.is_file() and frame.stat().st_size > 0

    sheet_json = out_dir / "review_sheet.json"
    sheet_md = out_dir / "review.md"
    assert sheet_json.is_file() and sheet_md.is_file()

    data = json.loads(sheet_json.read_text(encoding="utf-8"))
    assert data["probe"]["duration_s"] == pytest.approx(3.0, abs=0.3)
    assert data["probe"]["width"] == 320
    (saved,) = data["comments"]
    assert saved["comment"] == _COMMENT["comment"]
    assert saved["status"] == "pending"
    assert saved["frame"] == f"frames/review_{record_id}.png"

    md = sheet_md.read_text(encoding="utf-8")
    assert md.startswith("# 测试片")
    assert _COMMENT["comment"] in md
    assert f"frames/review_{record_id}.png" in md

    assert result.mp4 == str(media)
    assert result.qa["pass"] is True
    assert result.qa["comments"] == 1
    assert result.qa["by_status"] == {"pending": 1}
    assert result.qa["report"] == str(sheet_json)
    assert result.qa["sheet_md"] == str(sheet_md)


def test_render_from_events(tmp_path: Path) -> None:
    media = _make_video(tmp_path / "clip.mp4")
    cid = make_comment_id("片B", 3, 2.0, "转场太硬")
    events = [
        {"type": "comment", "film": "片B", "shot": 3, "timestamp_s": 2.0,
         "comment": "转场太硬"},
        {"type": "claim", "id": cid, "note": "agent 处理中"},
    ]
    result = _render({"media_path": str(media), "events": events}, tmp_path / "out")
    assert result.qa["by_status"] == {"working": 1}
    data = json.loads(Path(result.qa["report"]).read_text(encoding="utf-8"))
    assert data["comments"][0]["thread"][-1]["note"] == "agent 处理中"


def test_timestamp_beyond_duration_raises(tmp_path: Path) -> None:
    media = _make_video(tmp_path / "clip.mp4")
    bad = dict(_COMMENT, timestamp_s=10.0)
    with pytest.raises(CapabilityError) as excinfo:
        _render({"media_path": str(media), "comments": [bad]}, tmp_path / "out")
    # The rejection names the offending comment id.
    assert normalize_comments([bad])[0]["id"] in str(excinfo.value)


def test_empty_comments_raise(tmp_path: Path) -> None:
    media = _make_video(tmp_path / "clip.mp4")
    with pytest.raises(CapabilityError):
        _render({"media_path": str(media), "comments": []}, tmp_path / "out")


def test_missing_comments_and_events_raise(tmp_path: Path) -> None:
    media = _make_video(tmp_path / "clip.mp4")
    with pytest.raises(CapabilityError):
        _render({"media_path": str(media)}, tmp_path / "out")
