"""Contract tests for edit.video_use (offline, zero paid calls).

Fixtures are invented for these tests only: a fictional night-market
vendor and invented word timings. No upstream skill text, example plot
or person is reused. ffmpeg is only used to synthesize tiny test
videos (solid colour + sine tone) on the test machine; the capability
itself never executes a render. The transcription layer is mocked:
no whisper model is downloaded and no real inference runs.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from hevi.capabilities import registry
from hevi.capabilities.errors import CapabilityError
import hevi.capabilities.edit_video_use as vu_cap


def _words():
    # Invented vendor line: "灯亮了 夜市开了 茶香飘满街"
    # word boundaries: 0.50-0.80, 0.90-1.20, 1.40-1.70, 1.90-2.20,
    # 2.40-2.70, 2.90-3.20, 3.40-3.70, 3.90-4.20
    texts = ["灯", "亮", "了", "夜", "市", "开", "了", "茶"]
    starts = [0.50, 0.90, 1.40, 1.90, 2.40, 2.90, 3.40, 3.90]
    return [
        {"text": t, "start": s, "end": s + 0.30} for t, s in zip(texts, starts)
    ]


def _run(params, tmp_path):
    cap = registry.get("edit.video_use")
    result = cap.render_safe(params, tmp_path, duration=0.0, aspect="16:9", seed=42)
    report = json.loads(Path(result.qa["report_json"]).read_text(encoding="utf-8"))
    return result, report


def _valid_plan(**overrides):
    plan = {
        "method": "per_segment_extract_lossless_concat",
        "segments": [{"fade_in_ms": 30, "fade_out_ms": 30}],
        "overlays": [{"setpts_shift": True}],
        "subtitles_stage": "last",
        "subtitles_remapped": True,
        "outputs": ["/tmp/videos/edit/final.mp4"],
        "animations_sequential": False,
    }
    plan.update(overrides)
    return plan


def _rule_status(report, rule_id):
    for rule in report["hard_rules"]:
        if rule["id"] == rule_id:
            return rule["status"]
    raise AssertionError(f"rule {rule_id} missing")


def test_registry_and_transcript_first(tmp_path):
    result, report = _run(
        {
            "action": "transcript_first",
            "words": _words(),
            "selections": [
                {"start_word": 0, "end_word": 2, "beat": "HOOK"},
                {"start_word": 3, "end_word": 7, "beat": "SCENE"},
            ],
            "strategy_confirmed": True,
            "videos_dir": str(tmp_path),
        },
        tmp_path,
    )
    assert result.sha256
    assert report["transcript_provider"] == "provided"
    assert report["word_count"] == 8
    edl = report["edl"]
    # First segment: first word starts 0.50, pad 50ms -> in 0.45;
    # last word ends 1.70, pad 80ms -> out 1.78.
    assert edl["segments"][0]["in_sec"] == 0.45
    assert edl["segments"][0]["out_sec"] == 1.78
    assert edl["segments"][1]["output_start_sec"] == 1.33
    assert edl["total_duration_sec"] == pytest.approx(1.33 + (4.28 - 1.85))
    assert report["render_plan"]["method"] == "per_segment_extract_lossless_concat"
    assert report["render_plan"]["subtitles_stage"] == "last"
    assert report["render_plan"]["outputs"] == [str(tmp_path / "edit" / "final.mp4")]
    assert report["hard_rules_pass"] is True
    assert _rule_status(report, "R06") == "pass"
    assert _rule_status(report, "R07") == "pass"
    commands = report["render_plan"]["commands"]
    assert any("afade=t=in:st=0:d=0.03" in c for c in commands)
    assert any("-c copy" in c for c in commands)
    assert "subtitles" in commands[-1]


def test_strategy_unconfirmed_blocks(tmp_path):
    with pytest.raises(CapabilityError, match="strategy not confirmed"):
        _run(
            {
                "action": "transcript_first",
                "words": _words(),
                "selections": [{"start_word": 0, "end_word": 1}],
                "strategy_confirmed": False,
            },
            tmp_path,
        )


def test_pad_out_of_window_rejected(tmp_path):
    with pytest.raises(CapabilityError, match="30-200ms"):
        _run(
            {
                "action": "transcript_first",
                "words": _words(),
                "selections": [{"start_word": 0, "end_word": 1}],
                "strategy_confirmed": True,
                "pad_start_ms": 500,
            },
            tmp_path,
        )


def test_word_range_out_of_range_rejected(tmp_path):
    with pytest.raises(CapabilityError, match="out of range"):
        _run(
            {
                "action": "transcript_first",
                "words": _words(),
                "selections": [{"start_word": 0, "end_word": 99}],
                "strategy_confirmed": True,
            },
            tmp_path,
        )


def test_scribe_never_runs(tmp_path, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(CapabilityError, match="ELEVENLABS_API_KEY is not set"):
        _run(
            {
                "action": "transcript_first",
                "transcript_source": "scribe",
                "selections": [{"start_word": 0, "end_word": 1}],
                "strategy_confirmed": True,
            },
            tmp_path,
        )
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-key-for-test-only")
    with pytest.raises(CapabilityError, match="never made here"):
        _run(
            {
                "action": "transcript_first",
                "transcript_source": "scribe",
                "selections": [{"start_word": 0, "end_word": 1}],
                "strategy_confirmed": True,
            },
            tmp_path,
        )


def test_whisper_local_mocked(tmp_path, monkeypatch):
    import hevi.audio.whisper_alignment as wa

    async def fake_align(*, audio_path, text, model=None, language="zh"):
        assert language == "zh"
        words = [
            SimpleNamespace(text="灯", start_ms=500, end_ms=800),
            SimpleNamespace(text="亮", start_ms=900, end_ms=1200),
        ]
        return words, None

    monkeypatch.setattr(wa, "whisper_align_words", fake_align)
    audio = tmp_path / "line.wav"
    audio.write_bytes(b"RIFF-fake")
    _, report = _run(
        {
            "action": "transcript_first",
            "transcript_source": "whisper_local",
            "audio_path": str(audio),
            "text": "灯亮",
            "selections": [{"start_word": 0, "end_word": 1}],
            "strategy_confirmed": True,
            "videos_dir": str(tmp_path),
        },
        tmp_path,
    )
    assert report["transcript_provider"] == "whisper_local"
    assert report["word_count"] == 2
    assert report["edl"]["segments"][0]["in_sec"] == 0.45


@pytest.mark.parametrize(
    "mutate,rule_id",
    [
        (lambda p: p.update(subtitles_stage="other"), "R01"),
        (lambda p: p.update(method="single_pass_filtergraph"), "R02"),
        (lambda p: p.update(segments=[{"fade_in_ms": 0, "fade_out_ms": 30}]), "R03"),
        (lambda p: p.update(overlays=[{"setpts_shift": False}]), "R04"),
        (lambda p: p.update(subtitles_remapped=False), "R05"),
        (lambda p: p.update(animations_sequential=True), "R10"),
        (lambda p: p.update(outputs=["/tmp/videos/final.mp4"]), "R12"),
    ],
)
def test_rule_check_negative_plan_rules(tmp_path, mutate, rule_id):
    plan = _valid_plan()
    mutate(plan)
    _, report = _run(
        {
            "action": "rule_check",
            "render_plan": plan,
            "strategy_confirmed": True,
            "transcript": {"mode": "word", "verbatim": True},
        },
        tmp_path,
    )
    assert report["hard_rules_pass"] is False
    assert _rule_status(report, rule_id) == "fail"
    assert rule_id in report["failed_rules"]


def test_rule_check_word_boundary_and_padding(tmp_path):
    # Cut at 0.65 falls inside the word 0.50-0.80: R06/R07 fail.
    _, report = _run(
        {
            "action": "rule_check",
            "render_plan": _valid_plan(),
            "words": _words(),
            "cuts": [0.65],
            "strategy_confirmed": True,
        },
        tmp_path,
    )
    assert _rule_status(report, "R06") == "fail"
    assert _rule_status(report, "R07") == "fail"
    # Cut at 0.45 is 50ms before the 0.50 boundary: passes.
    _, report = _run(
        {
            "action": "rule_check",
            "render_plan": _valid_plan(),
            "words": _words(),
            "cuts": [0.45],
            "strategy_confirmed": True,
        },
        tmp_path,
    )
    assert _rule_status(report, "R06") == "pass"
    assert _rule_status(report, "R07") == "pass"


def test_rule_check_transcript_and_strategy_rules(tmp_path):
    _, report = _run(
        {
            "action": "rule_check",
            "render_plan": _valid_plan(),
            "strategy_confirmed": False,
            "transcript": {"mode": "phrase", "verbatim": False, "retranscribed": True, "source_changed": False},
        },
        tmp_path,
    )
    assert _rule_status(report, "R08") == "fail"
    assert _rule_status(report, "R09") == "fail"
    assert _rule_status(report, "R11") == "fail"
    _, report = _run(
        {
            "action": "rule_check",
            "render_plan": _valid_plan(),
            "strategy_confirmed": True,
            "transcript": {"mode": "word", "verbatim": True, "retranscribed": False, "source_changed": False},
        },
        tmp_path,
    )
    assert _rule_status(report, "R08") == "pass"
    assert _rule_status(report, "R09") == "pass"
    assert _rule_status(report, "R11") == "pass"


def test_full_loop_repairs_fixable_rules_within_cap(tmp_path):
    _, report = _run(
        {
            "action": "full",
            "words": _words(),
            "selections": [{"start_word": 0, "end_word": 2}],
            "strategy_confirmed": True,
            "videos_dir": str(tmp_path),
            "plan_overrides": {
                "subtitles_stage": "other",
                "segments": [{"fade_in_ms": 0, "fade_out_ms": 0}],
            },
            "max_rounds": 3,
        },
        tmp_path,
    )
    assert report["verify_rounds_used"] == 2
    assert set(report["verify_rounds_fixed"]) == {"R01", "R03"}
    assert report["hard_rules_pass"] is True
    assert report["render_plan"]["subtitles_stage"] == "last"


def test_full_loop_max_rounds_cap(tmp_path):
    with pytest.raises(CapabilityError, match="max_rounds"):
        _run(
            {
                "action": "full",
                "words": _words(),
                "selections": [{"start_word": 0, "end_word": 1}],
                "strategy_confirmed": True,
                "max_rounds": 4,
            },
            tmp_path,
        )


def _make_video(path, color, seconds, with_audio=True):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    inputs = ["-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=30:d={seconds}"]
    if with_audio:
        inputs += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
        maps = ["-map", "0:v", "-map", "1:a"]
    else:
        maps = ["-map", "0:v"]
    cmd = ["ffmpeg", "-y", "-v", "error"] + inputs + maps + [
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path),
    ]
    subprocess.run(cmd, check=True, timeout=120)


def test_cut_verify_single_colour_no_jump(tmp_path):
    clip = tmp_path / "single.mp4"
    _make_video(clip, "red", 4)
    _, report = _run(
        {"action": "cut_verify", "cut_file": str(clip), "cuts": [2.0]},
        tmp_path,
    )
    assert report["duration_sec"] == pytest.approx(4.0, abs=0.15)
    assert report["verdict"] == "pass"
    assert report["cuts"][0]["frame_jump"] is not None
    assert report["cuts"][0]["frame_jump"] < 40.0
    assert report["cuts"][0]["window_max_volume_db"] is not None
    assert report["samples"]["first"]["frame_ok"] is True
    assert report["samples"]["last"]["frame_ok"] is True
    assert report["samples"]["mid"]["frame_ok"] is True
    assert report["loudness"]["status"] in ("measured", "pending")


def test_cut_verify_two_colour_jump_and_occlusion(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    red = tmp_path / "red.mp4"
    blue = tmp_path / "blue.mp4"
    _make_video(red, "red", 2, with_audio=False)
    _make_video(blue, "blue", 2, with_audio=False)
    joined = tmp_path / "joined.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(red), "-i", str(blue),
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(joined)],
        check=True, timeout=120,
    )
    _, report = _run(
        {
            "action": "cut_verify",
            "cut_file": str(joined),
            "cuts": [2.0],
            "subtitle_rect": {"x": 0, "y": 160, "w": 320, "h": 20},
            "overlay_rects": [{"x": 0, "y": 150, "w": 320, "h": 30}],
        },
        tmp_path,
    )
    assert report["cuts"][0]["frame_jump"] is not None
    assert report["cuts"][0]["frame_jump"] > 40.0
    assert report["subtitle_occlusion"]["status"] == "blocked"
    assert report["verdict"] == "needs_rework"
    checks = {f["check"] for f in report["findings"]}
    assert "visual_jump" in checks
    assert "subtitle_occlusion" in checks


def test_cut_verify_missing_file_raises(tmp_path):
    with pytest.raises(CapabilityError, match="cut file not found"):
        _run(
            {"action": "cut_verify", "cut_file": str(tmp_path / "nope.mp4"), "cuts": [1.0]},
            tmp_path,
        )
