"""Tests for kids_gate capability and checker with real ffmpeg synthetic bad/good samples."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import subprocess

from hevi.quality.kids_gate import kids_gate_workflow
from hevi.capabilities import get


def _make_test_clip(out_path: Path, *, duration: float = 4.0, fps: int = 25, color: str = "blue") -> Path:
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c={color}:s=320x568:rate={fps}:duration={duration}",
        "-f", "lavfi", "-i", f"sine=f=440:r=48000:d={duration}",
        "-af", "loudnorm=I=-16:TP=-1.5",
        "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
        "-shortest", str(out_path)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def test_kids_gate_good_sample(tmp_path: Path) -> None:
    video = tmp_path / "good.mp4"
    _make_test_clip(video, duration=4.0)
    srt = tmp_path / "good.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n小朋友你好\n", encoding="utf-8")
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"subtitle_font_px": 64}), encoding="utf-8")

    report = kids_gate_workflow(video, srt_path=srt, metadata_path=meta)
    assert report["passed"] is True
    assert report["verdict"] == "ok"


def test_kids_gate_bad_sample_fast_cuts(tmp_path: Path) -> None:
    # 1s fast cuts: concat tiny segments
    segs = []
    for i in range(10):
        seg = tmp_path / f"seg_{i}.mp4"
        col = "red" if i % 2 == 0 else "blue"
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={col}:s=320x568:rate=25:duration=0.1",
            "-f", "lavfi", "-i", "sine=f=440:r=48000:d=0.1",
            "-af", "loudnorm=I=-16:TP=-1.5",
            "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
            "-shortest", str(seg)
        ], check=True, capture_output=True)
        segs.append(seg)

    list_file = tmp_path / "list.txt"
    list_file.write_text("\n".join(f"file '{s}'" for s in segs), encoding="utf-8")
    video = tmp_path / "fast_cuts.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", str(video)
    ], check=True, capture_output=True)

    report = kids_gate_workflow(video)
    assert report["passed"] is False
    assert any("最短时长" in v for v in report["violations"])


def test_kids_gate_bad_sample_banned_words(tmp_path: Path) -> None:
    video = tmp_path / "bad_words.mp4"
    _make_test_clip(video, duration=3.0)
    srt = tmp_path / "bad.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n去死吧打架\n", encoding="utf-8")

    report = kids_gate_workflow(video, srt_path=srt)
    assert report["passed"] is False
    assert any("禁用词" in v for v in report["violations"])


def test_kids_gate_bad_sample_small_font(tmp_path: Path) -> None:
    video = tmp_path / "small_font.mp4"
    _make_test_clip(video, duration=3.0)
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"subtitle_font_px": 30}), encoding="utf-8")

    report = kids_gate_workflow(video, metadata_path=meta)
    assert report["passed"] is False
    assert any("字号" in v for v in report["violations"])


def test_capability_qa_kids_gate(tmp_path: Path) -> None:
    cap = get("qa.kids_gate")
    assert cap.name == "qa.kids_gate"
    video = tmp_path / "cap_test.mp4"
    _make_test_clip(video, duration=3.0)

    out = tmp_path / "render_out"
    res = cap.render({"video_path": str(video)}, out, duration=3.0, aspect="9:16", seed=1)
    assert res.qa["passed"] is True


def test_deletion_fails(tmp_path: Path) -> None:
    video = tmp_path / "del.mp4"
    _make_test_clip(video, duration=2.0)
    video.unlink()
    with pytest.raises(Exception):
        kids_gate_workflow(video)
