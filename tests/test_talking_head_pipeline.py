"""Unit tests for the talking-head pipeline skeleton (hevi.talking_head).

Scope: the pure / injectable parts only — preflight rules, the frontal
assessment, the script/transcript similarity, black-frame aggregation,
the earshot + whisper + visual gate verdicts with fake measurers /
transcribers / samplers, the ledger structure, the retry policy, and a
full pipeline run with fake TTS / lip-sync stages.  No real engine
(LuxTTS, Wav2Lip, MuseTalk, faster-whisper, earshot CLI) runs here;
engine selection is exercised by a separate line.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from hevi.talking_head.gates import (
    earshot_gate,
    is_black_luma,
    normalize_for_compare,
    summarize_frames,
    text_similarity,
    visual_gate,
    whisper_gate,
)
from hevi.talking_head.pipeline import read_script_input, run_talking_head
from hevi.talking_head.preflight import (
    assess_frontal,
    check_voice_sample_metadata,
    estimate_script_seconds,
    run_preflight,
    validate_portrait,
    validate_script,
    validate_voice_sample,
)
from hevi.talking_head.state import (
    Ledger,
    finalize_status,
    new_ledger,
    validate_ledger,
)

SCRIPT = "大家好，今天我们来聊聊怎么把照片变成会说话的视频。"

# ---------------------------------------------------------------------------
# helpers / fakes
# ---------------------------------------------------------------------------

def _portrait(tmp_path: Path, *, size: int = 512, name: str = "me.png") -> Path:
    path = tmp_path / name
    Image.new("RGB", (size, size), (180, 160, 140)).save(path)
    return path


def _frontal_detector(_path: Path) -> dict:
    # Centred 200x240 face at score 0.9 in a 512x512 image, level eyes,
    # nose on the eye midline -> frontal.
    return {
        "face": (156.0, 136.0, 356.0, 376.0, 0.9),
        "landmarks": [(206.0, 220.0), (306.0, 220.0), (256.0, 280.0),
                      (226.0, 330.0), (286.0, 330.0)],
        "error": None,
    }


def _no_face_detector(_path: Path) -> dict:
    return {"face": None, "landmarks": None, "error": None}


def _good_measurer(_path: Path) -> dict:
    return {"lufs": -14.5, "true_peak_dbtp": -2.0, "clipped_samples": 0,
            "peak_dbfs": -2.0, "duration": 5.0}


def _hot_measurer(_path: Path) -> dict:
    return {"lufs": -6.0, "true_peak_dbtp": 0.2, "clipped_samples": 120,
            "peak_dbfs": 0.0, "duration": 5.0}


def _good_sampler(_path: Path) -> dict:
    return {
        "lumas": [90.0] * 10,
        "face_flags": [True] * 10,
        "durations": {"video_duration_s": 5.0, "audio_duration_s": 5.1,
                      "has_audio": True},
    }


# ---------------------------------------------------------------------------
# script preflight
# ---------------------------------------------------------------------------

def test_validate_script_empty_fails() -> None:
    for bad in ("", "   ", "\n\t"):
        result = validate_script(bad)
        assert result["ok"] is False
        assert any(c["name"] == "non_empty" and not c["ok"] for c in result["checks"])


def test_validate_script_counts_and_estimate() -> None:
    result = validate_script(SCRIPT)
    assert result["ok"] is True
    assert result["units"]["cjk_chars"] > 10
    assert result["estimated_seconds"] == estimate_script_seconds(SCRIPT)
    assert 3.0 < result["estimated_seconds"] < 10.0


def test_estimate_script_seconds_mixed_and_empty() -> None:
    assert estimate_script_seconds("") == 0.0
    mixed = estimate_script_seconds("hello world 你好世界")
    pure = estimate_script_seconds("你好世界")
    assert mixed > pure > 0


# ---------------------------------------------------------------------------
# portrait preflight
# ---------------------------------------------------------------------------

def test_validate_portrait_missing_file(tmp_path: Path) -> None:
    result = validate_portrait(tmp_path / "nope.jpg", face_detector=_frontal_detector)
    assert result["ok"] is False
    assert any("not found" in e for e in result["errors"])


def test_validate_portrait_undecodable(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"this is not an image at all")
    result = validate_portrait(bad, face_detector=_frontal_detector)
    assert result["ok"] is False
    assert any("not decodable" in e for e in result["errors"])


def test_validate_portrait_too_small(tmp_path: Path) -> None:
    small = _portrait(tmp_path, size=64)
    result = validate_portrait(small, face_detector=_frontal_detector)
    assert result["ok"] is False
    assert any("too small" in e for e in result["errors"])


def test_validate_portrait_good_with_fake_detector(tmp_path: Path) -> None:
    good = _portrait(tmp_path)
    result = validate_portrait(good, face_detector=_frontal_detector)
    assert result["ok"] is True, result
    assert result["width"] == 512 and result["height"] == 512
    assert result["face"]["frontal"] is True


def test_validate_portrait_no_face_fails(tmp_path: Path) -> None:
    good = _portrait(tmp_path)
    result = validate_portrait(good, face_detector=_no_face_detector)
    assert result["ok"] is False
    assert any("no face detected" in e for e in result["errors"])


def test_assess_frontal_side_face_rejected() -> None:
    # Nose pushed far right of the eye midline -> profile, not frontal.
    face = (156.0, 136.0, 356.0, 376.0, 0.9)
    landmarks = [(206.0, 220.0), (306.0, 220.0), (340.0, 280.0),
                 (226.0, 330.0), (286.0, 330.0)]
    result = assess_frontal(face, landmarks, image_size=(512, 512))
    assert result["ok"] is False
    assert result["frontal"] is False
    assert result["metrics"]["nose_offset_share"] > 0.20


def test_assess_frontal_low_score_and_none() -> None:
    assert assess_frontal(None, None, image_size=(512, 512))["ok"] is False
    low = assess_frontal((100.0, 100.0, 300.0, 340.0, 0.3), None, image_size=(512, 512))
    assert low["ok"] is False
    assert low["landmarks_checked"] is False


# ---------------------------------------------------------------------------
# voice sample rules (Rachel: MP3/M4A/WAV, 10s-5min, <=20MB)
# ---------------------------------------------------------------------------

def test_voice_sample_metadata_rules() -> None:
    ok = check_voice_sample_metadata(suffix=".mp3", size_bytes=1_000_000, duration_s=60.0)
    assert ok["ok"] is True
    too_short = check_voice_sample_metadata(suffix=".wav", size_bytes=1000, duration_s=5.0)
    assert too_short["ok"] is False
    too_long = check_voice_sample_metadata(suffix=".m4a", size_bytes=1000, duration_s=400.0)
    assert too_long["ok"] is False
    too_big = check_voice_sample_metadata(
        suffix=".mp3", size_bytes=21 * 1024 * 1024, duration_s=60.0)
    assert too_big["ok"] is False
    bad_fmt = check_voice_sample_metadata(suffix=".ogg", size_bytes=1000, duration_s=60.0)
    assert bad_fmt["ok"] is False


def test_validate_voice_sample_short_with_fake_prober(tmp_path: Path) -> None:
    sample = tmp_path / "sample.mp3"
    sample.write_bytes(b"\x00" * 2048)
    short = validate_voice_sample(sample, duration_prober=lambda _p: 5.0)
    assert short["ok"] is False
    assert any(c["name"] == "duration" and not c["ok"] for c in short["checks"])
    good = validate_voice_sample(sample, duration_prober=lambda _p: 42.0)
    assert good["ok"] is True
    missing = validate_voice_sample(tmp_path / "gone.mp3", duration_prober=lambda _p: 42.0)
    assert missing["ok"] is False


def test_run_preflight_aggregates_failures(tmp_path: Path) -> None:
    result = run_preflight(
        script_text="", portrait_path=tmp_path / "nope.jpg")
    assert result["ok"] is False
    assert result["errors"]  # both the empty script and the bad portrait


# ---------------------------------------------------------------------------
# similarity (whisper gate core)
# ---------------------------------------------------------------------------

def test_text_similarity() -> None:
    assert text_similarity(SCRIPT, SCRIPT) == 1.0
    # Punctuation / whitespace / case do not count.
    assert text_similarity("你好，世界！", "你好 世界") == 1.0
    assert text_similarity("Hello World", "helloworld") == 1.0
    assert text_similarity(SCRIPT, "完全不相干的另一段话讲的是做菜") < 0.5
    assert text_similarity("", "") == 1.0
    assert text_similarity(SCRIPT, "") == 0.0
    assert normalize_for_compare("A b，C!") == "abc"


def test_whisper_gate_with_fake_transcriber(tmp_path: Path) -> None:
    media = tmp_path / "film.mp4"
    media.write_bytes(b"\x00" * 16)
    good = whisper_gate(media, SCRIPT, transcriber=lambda _p: SCRIPT)
    assert good["pass"] is True and good["score"] == 1.0
    bad = whisper_gate(media, SCRIPT, transcriber=lambda _p: "今天教大家做红烧肉")
    assert bad["pass"] is False and bad["score"] < 0.85
    assert bad["transcript"]  # transcript is recorded, not just a boolean

    def boom(_p: Path) -> str:
        raise RuntimeError("model missing")

    broken = whisper_gate(media, SCRIPT, transcriber=boom)
    assert broken["pass"] is False and "model missing" in broken["error"]


# ---------------------------------------------------------------------------
# earshot gate with fake measurer
# ---------------------------------------------------------------------------

def test_earshot_gate_pass_and_fail(tmp_path: Path) -> None:
    media = tmp_path / "film.mp4"
    media.write_bytes(b"\x00" * 16)
    good = earshot_gate(media, measurer=_good_measurer)
    assert good["pass"] is True
    assert good["failed_checks"] == []
    hot = earshot_gate(media, measurer=_hot_measurer)
    assert hot["pass"] is False
    assert "loudness" in hot["failed_checks"]

    def boom(_p: Path) -> dict:
        raise RuntimeError("earshot missing")

    broken = earshot_gate(media, measurer=boom)
    assert broken["pass"] is False and "earshot missing" in broken["error"]
    missing = earshot_gate(tmp_path / "gone.mp4", measurer=_good_measurer)
    assert missing["pass"] is False


# ---------------------------------------------------------------------------
# visual gate: black frames + face rate + AV diff
# ---------------------------------------------------------------------------

def test_black_frame_detection() -> None:
    assert is_black_luma(0.0) is True
    assert is_black_luma(12.0) is True
    assert is_black_luma(80.0) is False
    summary = summarize_frames([5.0, 90.0, 95.0, 100.0], [True, True, True, False])
    assert summary["black_frames"] == 1
    assert summary["black_share"] == 0.25
    assert summary["face_rate"] == 0.75
    assert summary["pass"] is False  # black share 0.25 > 0.1 and face rate < 0.8
    clean = summarize_frames([90.0] * 10, [True] * 10)
    assert clean["pass"] is True
    empty = summarize_frames([], [])
    assert empty["pass"] is False


def test_visual_gate_with_fake_sampler(tmp_path: Path) -> None:
    media = tmp_path / "film.mp4"
    media.write_bytes(b"\x00" * 16)
    good = visual_gate(media, frame_sampler=_good_sampler)
    assert good["pass"] is True
    assert good["face_rate"] == 1.0
    assert good["av_duration_diff_s"] == pytest.approx(0.1)

    def dark_sampler(_p: Path) -> dict:
        return {"lumas": [2.0] * 10, "face_flags": [False] * 10,
                "durations": {"video_duration_s": 5.0, "audio_duration_s": 9.0,
                              "has_audio": True}}

    dark = visual_gate(media, frame_sampler=dark_sampler)
    assert dark["pass"] is False
    assert dark["black_share"] == 1.0
    assert dark["av_duration_diff_s"] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# ledger structure
# ---------------------------------------------------------------------------

def test_ledger_structure_and_cost_invariant(tmp_path: Path) -> None:
    data = new_ledger(script_text=SCRIPT, portrait="me.jpg", engine="wav2lip", voice="soffy")
    assert validate_ledger(data) == []
    assert data["cost_usd"] == 0
    assert data["cost_basis"]["external_paid_calls"] == []
    for stage in data["stages"].values():
        assert stage["status"] == "pending"
        assert stage["retries"] == 0 and stage["attempts"] == 0
        assert stage["degraded"] is False

    ledger = Ledger(data, tmp_path / "job-state.json")
    ledger.start_stage("tts")
    ledger.record_retry("tts")
    ledger.finish_stage("tts")
    assert data["stages"]["tts"]["attempts"] == 1
    assert data["stages"]["tts"]["retries"] == 1
    assert data["stages"]["tts"]["elapsed_s"] is not None
    path = ledger.save()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert validate_ledger(loaded) == []


def test_finalize_status_derivation() -> None:
    data = new_ledger(script_text=SCRIPT, portrait="me.jpg", engine="wav2lip", voice="soffy")
    data["gates"] = {"whisper_verify": {"pass": True}}
    assert finalize_status(data) == "delivered"
    data["gates"] = {"whisper_verify": {"pass": False, "score": 0.4}}
    assert finalize_status(data) == "delivered_with_warnings"
    data["stages"]["tts"]["status"] = "failed"
    assert finalize_status(data) == "failed"
    assert data["failed_stage"] == "tts"


# ---------------------------------------------------------------------------
# pipeline orchestration with fake stages
# ---------------------------------------------------------------------------

def _fake_tts(_text: str, out_wav: Path, _voice: str) -> Path:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    out_wav.write_bytes(b"RIFF-fake")
    return out_wav


def _fake_lipsync(_portrait: Path, _wav: Path, _dur: float, work: Path, _engine: str) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    final = work.parent / "talking_head.mp4"
    final.write_bytes(b"mp4-fake")
    return final


def _passing_gates(_video: Path, _text: str, _adur: float) -> dict:
    return {"pass": True, "failed": [],
            "gates": {"whisper_verify": {"pass": True, "score": 1.0},
                      "earshot_audio": {"pass": True},
                      "visual": {"pass": True}}}


def _failing_gates(_video: Path, _text: str, _adur: float) -> dict:
    return {"pass": False, "failed": ["whisper_verify"],
            "gates": {"whisper_verify": {"pass": False, "score": 0.31},
                      "earshot_audio": {"pass": True},
                      "visual": {"pass": True}}}


def test_pipeline_delivered_with_fake_stages(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "hevi.talking_head.pipeline._media_duration", lambda _p: 5.0)
    out = tmp_path / "job"
    ledger = run_talking_head(
        script_text=SCRIPT, portrait_path=_portrait(tmp_path), out_dir=out,
        tts_fn=_fake_tts, lipsync_fn=_fake_lipsync, gate_runner=_passing_gates,
        face_detector=_frontal_detector,
    )
    assert ledger["status"] == "delivered"
    assert ledger["cost_usd"] == 0
    assert (out / "talking_head.mp4").is_file()
    saved = json.loads((out / "job-state.json").read_text(encoding="utf-8"))
    assert validate_ledger(saved) == []
    assert saved["status"] == "delivered"
    assert saved["gates"]["whisper_verify"]["score"] == 1.0


def test_pipeline_gate_failure_delivers_with_warnings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "hevi.talking_head.pipeline._media_duration", lambda _p: 5.0)
    ledger = run_talking_head(
        script_text=SCRIPT, portrait_path=_portrait(tmp_path), out_dir=tmp_path / "job",
        tts_fn=_fake_tts, lipsync_fn=_fake_lipsync, gate_runner=_failing_gates,
        face_detector=_frontal_detector,
    )
    assert ledger["status"] == "delivered_with_warnings"
    # The failing gate's measured score is in the ledger; nothing faked.
    assert ledger["gates"]["whisper_verify"]["pass"] is False
    assert ledger["gates"]["whisper_verify"]["score"] == 0.31
    assert ledger["stages"]["gates"]["degraded"] is True


def test_pipeline_preflight_failure_stops(tmp_path: Path) -> None:
    called: list[str] = []

    def tts_spy(text: str, out_wav: Path, voice: str) -> Path:
        called.append(text)
        return _fake_tts(text, out_wav, voice)

    ledger = run_talking_head(
        script_text="", portrait_path=tmp_path / "nope.jpg", out_dir=tmp_path / "job",
        tts_fn=tts_spy, lipsync_fn=_fake_lipsync, gate_runner=_passing_gates,
        face_detector=_frontal_detector,
    )
    assert ledger["status"] == "failed"
    assert ledger["failed_stage"] == "preflight"
    assert called == []  # TTS never ran


def test_pipeline_tts_retries_once_then_succeeds(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "hevi.talking_head.pipeline._media_duration", lambda _p: 5.0)
    attempts: list[int] = []

    def flaky_tts(text: str, out_wav: Path, voice: str) -> Path:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("lux service hiccup")
        return _fake_tts(text, out_wav, voice)

    ledger = run_talking_head(
        script_text=SCRIPT, portrait_path=_portrait(tmp_path), out_dir=tmp_path / "job",
        tts_fn=flaky_tts, lipsync_fn=_fake_lipsync, gate_runner=_passing_gates,
        face_detector=_frontal_detector,
    )
    assert ledger["status"] == "delivered"
    assert ledger["stages"]["tts"]["attempts"] == 2
    assert ledger["stages"]["tts"]["retries"] == 1


def test_pipeline_tts_fails_after_retry(tmp_path: Path) -> None:
    def dead_tts(_text: str, _out: Path, _voice: str) -> Path:
        raise RuntimeError("lux service down")

    ledger = run_talking_head(
        script_text=SCRIPT, portrait_path=_portrait(tmp_path), out_dir=tmp_path / "job",
        tts_fn=dead_tts, lipsync_fn=_fake_lipsync, gate_runner=_passing_gates,
        face_detector=_frontal_detector,
    )
    assert ledger["status"] == "failed"
    assert ledger["failed_stage"] == "tts"
    assert ledger["stages"]["tts"]["attempts"] == 2  # 1 try + 1 retry, no more
    assert ledger["stages"]["tts"]["retries"] == 1


# ---------------------------------------------------------------------------
# CLI input resolution
# ---------------------------------------------------------------------------

def test_read_script_input(tmp_path: Path) -> None:
    script_file = tmp_path / "script.txt"
    script_file.write_text(SCRIPT, encoding="utf-8")
    assert read_script_input(script_path=str(script_file), text=None) == SCRIPT
    assert read_script_input(script_path=None, text="你好") == "你好"
    with pytest.raises(ValueError):
        read_script_input(script_path=str(script_file), text="你好")
    with pytest.raises(ValueError):
        read_script_input(script_path=None, text=None)
