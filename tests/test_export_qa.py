"""Offline tests for the unified export QA gate (``qa.export_gate``).

All samples are synthesized locally — video from ffmpeg lavfi sources,
audio from stdlib ``wave`` sine tones (same approach as
tests/test_earshot_gate.py) — so no network and no paid calls.  Loudness
is measured through the real local earshot CLI (model-free ``measure``).
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.quality.export_qa import run_export_qa

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)

W, H = 180, 320  # 9:16 vertical sample size


def _ffmpeg(args: list[str]) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *args],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


def _tone_wav(path: Path, *, seconds: float, fade_out: bool = True) -> Path:
    """Mono 48 kHz sine at amp 0.2 (~-15 LUFS once muxed, inside -14±2)."""
    sr = 48000
    n = int(sr * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        for i in range(n):
            t = i / sr
            gain = 1.0
            if fade_out and t > seconds - 0.5:
                gain = max(0.0, (seconds - t) / 0.5)
            v = 0.2 * gain * math.sin(2.0 * math.pi * 440.0 * t)
            w.writeframes(int(v * 32767).to_bytes(2, "little", signed=True))
    return path


def _mux(path: Path, video_src: str, tone: Path, *, shortest: bool = True) -> Path:
    args = [
        "-f", "lavfi", "-i", video_src,
        "-i", str(tone),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
    ]
    if shortest:
        args.append("-shortest")
    args.append(str(path))
    _ffmpeg(args)
    return path


def _good_video(path: Path, *, fade_out: bool = True) -> Path:
    tone = _tone_wav(path.with_suffix(".tone.wav"), seconds=3.0, fade_out=fade_out)
    return _mux(
        path, f"testsrc2=size={W}x{H}:rate=30:duration=3", tone
    )


def _black_video(path: Path) -> Path:
    tone = _tone_wav(path.with_suffix(".tone.wav"), seconds=2.0)
    return _mux(
        path, f"color=c=black:size={W}x{H}:rate=30:duration=2", tone
    )


def _desync_video(path: Path) -> Path:
    """3 s video with only 1 s of audio (A/V diff 2 s)."""
    tone = _tone_wav(path.with_suffix(".tone.wav"), seconds=1.0, fade_out=False)
    return _mux(
        path,
        f"testsrc2=size={W}x{H}:rate=30:duration=3",
        tone,
        shortest=False,
    )


def _by_name(report: dict) -> dict[str, dict]:
    return {c["name"]: c for c in report["checks"]}


# ---------------------------------------------------------------------------
# Pure-function gate behaviour
# ---------------------------------------------------------------------------


def test_good_video_passes(tmp_path: Path) -> None:
    media = _good_video(tmp_path / "good.mp4")
    report = run_export_qa(media, expect={"aspect": "9:16", "fps": 30})
    checks = _by_name(report)
    assert checks["container_codec"]["status"] == "pass"
    assert checks["resolution_aspect"]["status"] == "pass"
    assert checks["fps"]["status"] == "pass"
    assert checks["black_frames"]["status"] == "pass"
    assert checks["loudness"]["status"] == "pass", checks["loudness"]
    assert checks["av_sync"]["status"] == "pass"
    assert checks["ending_audio"]["status"] == "pass"
    assert checks["last_frame_black"]["status"] == "pass"
    assert checks["subtitles"]["status"] == "skip"
    assert report["verdict"] == "pass"
    assert report["pass"] is True
    assert report["failed_checks"] == []
    json.dumps(report)  # report must stay JSON-serialisable


def test_black_video_fails_black_frames(tmp_path: Path) -> None:
    media = _black_video(tmp_path / "black.mp4")
    report = run_export_qa(media, expect={"aspect": "9:16"})
    checks = _by_name(report)
    assert checks["black_frames"]["status"] == "fail"
    assert checks["black_frames"]["value"] > 0.1
    assert checks["last_frame_black"]["status"] == "warn"
    assert report["verdict"] == "fail"
    assert report["pass"] is False
    assert "black_frames" in report["failed_checks"]


def test_abrupt_ending_warns_not_fails(tmp_path: Path) -> None:
    media = _good_video(tmp_path / "abrupt.mp4", fade_out=False)
    report = run_export_qa(media, expect={"aspect": "9:16", "fps": 30})
    checks = _by_name(report)
    assert checks["ending_audio"]["status"] == "warn", checks["ending_audio"]
    assert checks["loudness"]["status"] == "pass"
    assert report["verdict"] == "warn"
    assert report["pass"] is True  # warnings never block delivery
    assert "ending_audio" in report["warned_checks"]


def test_wrong_aspect_fails(tmp_path: Path) -> None:
    media = _good_video(tmp_path / "good.mp4")
    report = run_export_qa(media, expect={"aspect": "16:9"})
    checks = _by_name(report)
    assert checks["resolution_aspect"]["status"] == "fail"
    assert report["verdict"] == "fail"


def test_wrong_fps_fails(tmp_path: Path) -> None:
    media = _good_video(tmp_path / "good.mp4")
    report = run_export_qa(media, expect={"fps": 60})
    assert _by_name(report)["fps"]["status"] == "fail"


def test_av_desync_fails(tmp_path: Path) -> None:
    media = _desync_video(tmp_path / "desync.mp4")
    report = run_export_qa(media)
    checks = _by_name(report)
    assert checks["av_sync"]["status"] == "fail"
    assert checks["av_sync"]["value"] > 0.5


def test_subtitles_required_then_sidecar(tmp_path: Path) -> None:
    media = _good_video(tmp_path / "subs.mp4")
    report = run_export_qa(media, expect={"subtitles": True})
    assert _by_name(report)["subtitles"]["status"] == "fail"

    (tmp_path / "subs.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8"
    )
    report2 = run_export_qa(media, expect={"subtitles": True})
    assert _by_name(report2)["subtitles"]["status"] == "pass"


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run_export_qa(tmp_path / "nope.mp4")


def test_no_expect_skips_optional_checks(tmp_path: Path) -> None:
    media = _good_video(tmp_path / "good.mp4")
    report = run_export_qa(media)
    checks = _by_name(report)
    assert checks["fps"]["status"] == "skip"
    assert checks["subtitles"]["status"] == "skip"
    assert checks["resolution_aspect"]["status"] == "pass"


# ---------------------------------------------------------------------------
# Capability registration contract
# ---------------------------------------------------------------------------


def test_export_gate_registered_and_listable() -> None:
    names = caps.names()
    assert "qa.export_gate" in names
    listed = [c.name for c in caps.list(kind="video")]
    assert "qa.export_gate" in listed


def test_export_gate_describe_has_schema() -> None:
    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    assert "qa.export_gate" in by_name
    assert by_name["qa.export_gate"].get("description")
    assert by_name["qa.export_gate"].get("params_schema")


def test_export_gate_rejects_invalid_params(tmp_path: Path) -> None:
    cap = caps.get("qa.export_gate")
    with pytest.raises(CapabilityError):
        cap.render_safe({}, tmp_path / "out", duration=1.0, aspect="9:16", seed=1)
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"media_path": "/tmp/x.mp4", "bogus": 1},
            tmp_path / "out",
            duration=1.0,
            aspect="9:16",
            seed=1,
        )
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"media_path": "/tmp/x.mp4", "max_black_ratio": 2.0},
            tmp_path / "out",
            duration=1.0,
            aspect="9:16",
            seed=1,
        )


def test_export_gate_missing_file_raises(tmp_path: Path) -> None:
    cap = caps.get("qa.export_gate")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"media_path": str(tmp_path / "nope.mp4")},
            tmp_path / "out",
            duration=1.0,
            aspect="9:16",
            seed=1,
        )


def test_export_gate_render_writes_report(tmp_path: Path) -> None:
    media = _good_video(tmp_path / "good.mp4")
    cap = caps.get("qa.export_gate")
    result = cap.render_safe(
        {"media_path": str(media), "expect_fps": 30},
        tmp_path / "out",
        duration=3.0,
        aspect="9:16",
        seed=7,
    )
    assert result.qa["verdict"] == "pass"
    assert result.qa["pass"] is True
    assert result.qa["failed_checks"] == []
    assert result.mp4 == str(media)
    assert result.sha256

    report_path = Path(result.qa["report"])
    assert report_path.name == "export_qa_report.json"
    assert report_path.is_file()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["verdict"] == "pass"
    assert payload["tool"].startswith("export_qa")

    report_path.unlink()
    assert not report_path.exists(), "contract: deleting the artifact must break verification"


def test_export_gate_render_reports_fail_verdict(tmp_path: Path) -> None:
    media = _black_video(tmp_path / "black.mp4")
    cap = caps.get("qa.export_gate")
    result = cap.render_safe(
        {"media_path": str(media)},
        tmp_path / "out",
        duration=2.0,
        aspect="9:16",
        seed=7,
    )
    assert result.qa["verdict"] == "fail"
    assert result.qa["pass"] is False
    assert "black_frames" in result.qa["failed_checks"]
