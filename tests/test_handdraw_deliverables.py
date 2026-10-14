"""Acceptance checks on freshly rendered pixels, PCM audio and artifacts."""
from __future__ import annotations

import json
import re
import subprocess
import wave
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

from hevi.layer4_legacy.handdraw.layout import compute_canvas_layout


def _required_artifacts(root: Path) -> dict[str, Path]:
    return {
        "video": root / "work" / "review" / "preview.mp4",
        "cover": root / "outputs" / "cover.png",
        "captions": root / "outputs" / "editing" / "transcript.srt",
        "script": root / "outputs" / "script.txt",
        "master": root / "inputs" / "narration" / "master.wav",
        "alignment": root / "inputs" / "narration" / "alignment.json",
        "kids_safety": root / "kids-safety.json",
        "verification": root / "preview-verification.json",
        "review": root / "review.json",
        "drawing_plan": root / "drawing-plan.json",
        "drawing_plan_preflight": root / "drawing-plan.preflight.json",
        "drawing_review": root / "drawing-review.json",
        "art_direction": root / "art-direction.json",
        "timeline": root / "work" / "timeline.json",
        "assets": root / "work" / "assets",
    }


def _assert_all_artifacts(root: Path) -> dict[str, Path]:
    artifacts = _required_artifacts(root)
    for name, path in artifacts.items():
        assert path.exists(), f"Missing {name} artifact: {path}"
        if path.is_dir():
            content = [item for item in path.rglob("*") if item.is_file()]
            assert content, f"Empty {name} artifact directory: {path}"
        else:
            assert path.is_file(), f"{name} artifact is not a regular file: {path}"
            assert path.stat().st_size > 0, f"Empty {name} artifact: {path}"
    return artifacts


def _probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "/home/soffy/.local/bin/ffprobe",
            "-v", "error",
            "-show_streams",
            "-show_format",
            "-of", "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _measure_loudness(path: Path) -> dict[str, float]:
    result = subprocess.run(
        [
            "/home/soffy/.local/bin/ffmpeg",
            "-hide_banner", "-i", str(path),
            "-af", "loudnorm=I=-17:TP=-2:LRA=7:print_format=json",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    match = re.search(r'\{\s*"input_i".*?\}', result.stderr, re.S)
    assert match, f"ffmpeg loudness analysis returned no measurements: {result.stderr[-1200:]}"
    raw = json.loads(match.group())
    return {"integrated_lufs": float(raw["input_i"]), "true_peak_dbtp": float(raw["input_tp"])}


def test_deliverables_exist_and_are_real(handdraw_preview) -> None:
    root = handdraw_preview.root
    result = handdraw_preview.result
    artifacts = _assert_all_artifacts(root)
    assert result.mp4 == artifacts["video"]
    assert result.mp4 is not None and result.mp4.is_file()
    assert result.sha256
    report = json.loads(artifacts["verification"].read_text(encoding="utf-8"))
    assert report["status"] == "engineering_preview_verified"
    assert report["human_review"] == "pending"
    review = json.loads(artifacts["review"].read_text(encoding="utf-8"))
    assert review["review_type"] == "automated_engineering_only"
    assert review["human_review"] == "pending"
    for category in ("content", "visual", "motion", "audio", "privacy"):
        assert review[category]["status"] == "not_reviewed"
        assert "review remains pending" in review[category]["evidence"]


def test_ffprobe_duration_resolution_and_audio_stream(handdraw_preview) -> None:
    artifacts = _assert_all_artifacts(handdraw_preview.root)
    probe = _probe(artifacts["video"])
    video = next(stream for stream in probe["streams"] if stream.get("codec_type") == "video")
    audio = next(stream for stream in probe["streams"] if stream.get("codec_type") == "audio")
    duration = float(probe["format"]["duration"])
    assert abs(duration - 2.0) <= 0.1
    assert (int(video["width"]), int(video["height"])) == (1920, 1080)
    assert abs(float(audio["duration"]) - duration) <= 0.08
    assert not [stream for stream in probe["streams"] if stream.get("codec_type") == "subtitle"]


def test_preview_audio_is_non_silent_and_measured_mix_meets_loudness_policy(
    handdraw_preview,
) -> None:
    root = handdraw_preview.root
    wav_path = root / "work" / "mix.wav"
    assert wav_path.is_file() and wav_path.stat().st_size > 1000
    with wave.open(str(wav_path), "rb") as stream:
        frames = stream.getnframes()
        rate = stream.getframerate()
        samples = np.frombuffer(stream.readframes(frames), dtype="<i2")
    assert frames > rate
    assert float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) > 300
    measured = _measure_loudness(wav_path)
    assert -17.0 <= measured["integrated_lufs"] <= -15.0, measured
    assert measured["true_peak_dbtp"] <= -1.5, measured


def test_narration_ranges_cues_and_real_asr_timing_are_valid(handdraw_preview) -> None:
    from hevi.layer4_legacy.handdraw.asr import transcribe_words
    from hevi.layer4_legacy.handdraw.tts import build_caption_cues

    root = handdraw_preview.root
    artifacts = _assert_all_artifacts(root)
    alignment = json.loads(artifacts["alignment"].read_text(encoding="utf-8"))
    assert alignment["engine"] in {"piper", "cosyvoice"}
    assert len(alignment["engines_used"]) == 1
    assert alignment["caption_method"] in {"asr", "proportional"}
    assert set(alignment["caption_methods_used"]) <= {"asr", "proportional"}
    assert all(beat["engine"] == alignment["engine"] for beat in alignment["beats"])
    assert float(alignment["characters_per_second"]) <= 3.5

    previous = 0.0
    for beat in alignment["beats"]:
        start, end = float(beat["start"]), float(beat["end"])
        assert 0 <= previous <= start < end <= float(alignment["total_duration"]) + 1 / 48000
        previous = end
        cues = beat["caption_cues"]
        assert cues
        assert "".join(cue["text"] for cue in cues) == beat["text"]
        assert all(1 <= len(cue["text"]) <= 14 for cue in cues)
        assert all(cue["text"].strip("，。！？；：、,.!?;:…—· ") for cue in cues)
        assert not any(len(cue["text"]) == 1 and cue["text"] in "，。！？；：、,.!?;:" for cue in cues)

    # Re-run CPU ASR on the actual first beat WAV and compare its independently
    # measured word boundaries with the generated cue starts (not JSON claims).
    wav = root / "inputs" / "narration" / "_synth" / "0000.wav"
    assert wav.is_file()
    beat = alignment["beats"][0]
    words = transcribe_words(wav)
    assert words, "CPU ASR must yield word timestamps for the sample narration"
    with wave.open(str(wav), "rb") as stream:
        duration = stream.getnframes() / stream.getframerate()
    measured_cues, method = build_caption_cues(beat["text"], duration, words)
    assert method == "asr"
    stored = beat["caption_cues"]
    assert len(stored) == len(measured_cues)
    errors = [
        abs(float(actual["start"]) - float(expected["start"]))
        for actual, expected in zip(stored, measured_cues, strict=True)
    ]
    assert errors
    p95 = float(np.percentile(errors, 95))
    assert p95 <= 0.2, {"p95_seconds": p95, "errors": errors}

    # Independently inspect PCM energy onset for the real spoken waveform.
    samples = np.frombuffer(wav.read_bytes()[44:], dtype="<i2")
    window = max(1, int(stream.getframerate() * 0.01))
    rms = [
        float(np.sqrt(np.mean(samples[i:i + window].astype(np.float64) ** 2)))
        for i in range(0, len(samples) - window + 1, window)
    ]
    peak = max(rms, default=0.0)
    onset = next((i * window / 48000 for i, value in enumerate(rms) if value > max(30, peak * 0.02)), 0.0)
    first_cue_start = float(stored[0]["start"])
    assert abs(first_cue_start - onset) <= 0.2, {
        "cue_start": first_cue_start, "pcm_energy_onset": onset
    }


def test_visual_ink_coverage_is_measured_from_video_frames(handdraw_preview) -> None:
    path = handdraw_preview.result.mp4
    assert path and path.is_file()
    decoded = subprocess.run(
        [
            "/home/soffy/.local/bin/ffmpeg",
            "-v", "error", "-i", str(path),
            "-vf", "fps=8,scale=320:180",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    frame_size = 320 * 180 * 3
    assert len(decoded) >= frame_size * 8, "Must decode multiple actual frames from the MP4"
    frames = np.frombuffer(decoded, dtype=np.uint8).reshape(-1, 180, 320, 3)
    paper = np.asarray((250, 243, 221), dtype=np.int16)
    cumulative = np.zeros((144, 320), dtype=bool)
    cumulative_counts = []
    frame_counts = []
    for frame in frames:
        # Measure decoded pixels in the top 80% so changing subtitle glyphs cannot
        # masquerade as ink progression. The cumulative map is built from observed
        # RGB frames (never renderer NPZ/reveal data), so its area cannot decrease.
        image = frame[:144].astype(np.int16)
        difference = np.abs(image - paper).max(axis=2)
        ink = (difference > 26) & (
            (image.max(axis=2) < 165)
            | ((image.max(axis=2) - image.min(axis=2)) > 32)
        )
        frame_counts.append(int(ink.sum()))
        cumulative |= ink
        cumulative_counts.append(int(cumulative.sum()))

    # The direct frame measurements include the moving drawing hand/nib, so a
    # small local drop is expected as it crosses the illustration. The overall
    # decoded frame coverage must still rise, with no frame losing more than 5%
    # of the measured ink area. These counts come from decoded MP4 RGB pixels,
    # not reveal maps, timeline JSON or NPZ metadata.
    assert frame_counts[-1] > frame_counts[0] + 100, frame_counts
    allowed_drop = max(50, int(max(frame_counts) * 0.05))
    drops = [
        left - right for left, right in pairwise(frame_counts) if left > right
    ]
    assert not drops or max(drops) <= allowed_drop, {
        "frame_counts": frame_counts,
        "largest_drop": max(drops, default=0),
        "allowed_drop": allowed_drop,
    }
    assert sum(
        right > left for left, right in pairwise(frame_counts)
    ) >= 3, frame_counts
    assert cumulative_counts[-1] > cumulative_counts[0] + 100, {
        "frame_counts": frame_counts, "cumulative_counts": cumulative_counts
    }
    assert all(
        left <= right for left, right in pairwise(cumulative_counts)
    ), cumulative_counts


@pytest.mark.parametrize(
    "artifact_name",
    [
        "video",
        "cover",
        "master",
        "review",
        "drawing_plan",
        "timeline",
        "assets",
    ],
)
def test_removing_any_critical_artifact_is_a_hard_failure(
    handdraw_preview, artifact_name: str
) -> None:
    root = handdraw_preview.root
    artifacts = _assert_all_artifacts(root)
    artifact = artifacts[artifact_name]
    parked = artifact.with_name(artifact.name + ".held-for-negative-test")
    assert not parked.exists()
    artifact.rename(parked)
    try:
        with pytest.raises(AssertionError, match=f"Missing {artifact_name} artifact"):
            _assert_all_artifacts(root)
    finally:
        parked.rename(artifact)


def test_layout_fonts_meet_kids_caption_contract() -> None:
    landscape = compute_canvas_layout(1920, 1080)
    portrait = compute_canvas_layout(1080, 1920)
    assert landscape.caption_font_size >= 48
    assert portrait.caption_font_size >= 56
    assert landscape.caption_font_size >= 56
