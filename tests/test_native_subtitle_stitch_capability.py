"""Tests for image.native_subtitle_stitch (clean-room, placeholder data only).

Pure logic is tested without ffmpeg. The one ffmpeg test builds its
own synthetic video with the system ffmpeg and is skipped honestly
when ffmpeg is unavailable. No downloaded video, no third-party
material, no real titles or speakers are used anywhere here.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from hevi.capabilities import names as capability_names
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.native_subtitle_stitch import (
    CAPABILITY_NAME,
    build_stitched_image,
    check_speakers,
    find_cjk_font,
    frames_are_duplicates,
    native_layout,
    require_rights,
    script_layout,
    validate_lines,
    validate_timestamps,
)

RIGHTS = {"source": "placeholder local file", "basis": "own_recording", "publish": False}


def _frame(colour: tuple[int, int, int], size: tuple[int, int] = (640, 360)) -> Image.Image:
    image = Image.new("RGB", size, colour)
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 60, 60), fill=(255, 255, 255))
    return image


def _striped_frame(seed: int) -> Image.Image:
    image = Image.new("RGB", (640, 360), (20 + seed * 30, 40, 60))
    draw = ImageDraw.Draw(image)
    for x in range(0, 640, 32):
        draw.rectangle((x, 100 + seed * 10, x + 16, 260), fill=(200, 180, 40))
    return image


def test_capability_is_registered_on_package_import() -> None:
    assert CAPABILITY_NAME in capability_names()


def test_rights_refused_when_missing_or_empty() -> None:
    with pytest.raises(CapabilityError):
        require_rights(None)
    with pytest.raises(CapabilityError):
        require_rights({"source": "", "basis": "own_recording"})
    with pytest.raises(CapabilityError):
        require_rights({"source": "placeholder", "basis": "  "})
    assert require_rights(RIGHTS)["basis"] == "own_recording"


def test_timestamps_must_be_increasing_inside_duration_and_capped() -> None:
    assert validate_timestamps([0.5, 1.5, 2.5], 10.0) == [0.5, 1.5, 2.5]
    with pytest.raises(CapabilityError):
        validate_timestamps([1.5, 0.5], 10.0)
    with pytest.raises(CapabilityError):
        validate_timestamps([0.5, 10.0], 10.0)
    with pytest.raises(CapabilityError):
        validate_timestamps([0.5], 10.0)
    with pytest.raises(CapabilityError):
        validate_timestamps([float(i) for i in range(8)], 100.0)
    with pytest.raises(CapabilityError):
        validate_timestamps(["soon"], 10.0)


def test_mode_routing_never_switches_silently() -> None:
    times = [0.5, 1.5]
    lines = [
        {"t": 0.5, "text": "placeholder line one", "speaker": "Speaker A"},
        {"t": 1.5, "text": "placeholder line two", "speaker": "Speaker A"},
    ]
    with pytest.raises(CapabilityError):
        validate_lines(lines, times, "native", "single_speaker")
    with pytest.raises(CapabilityError):
        validate_lines(None, times, "script", "single_speaker")
    with pytest.raises(CapabilityError):
        validate_lines(lines, times, "other", "single_speaker")
    checked = validate_lines(lines, times, "script", "single_speaker")
    assert [line["text"] for line in checked] == ["placeholder line one", "placeholder line two"]


def test_mixed_speakers_refused_except_declared_question_answer() -> None:
    lines = [
        {"t": 0.5, "text": "placeholder question", "speaker": "Speaker A"},
        {"t": 1.5, "text": "placeholder answer", "speaker": "Speaker B"},
    ]
    with pytest.raises(CapabilityError):
        check_speakers(lines, "single_speaker")
    assert check_speakers(lines, "question_answer") == ["Speaker A", "Speaker B"]
    with pytest.raises(CapabilityError):
        check_speakers(lines + [{"t": 2.5, "text": "extra", "speaker": "Speaker A"}],
                       "question_answer")


def test_script_layout_sums_to_canvas_and_clamps() -> None:
    layout = script_layout(4)
    assert layout["hero_fraction"] == pytest.approx(0.70)
    assert layout["hero_height"] + sum(layout["strip_heights"]) == 1920
    clamped = script_layout(1, hero_fraction=0.95)
    assert clamped["hero_fraction"] == pytest.approx(0.82)
    assert clamped["hero_fraction_clamped"] is True
    low = script_layout(6, hero_fraction=0.10)
    assert low["hero_fraction"] == pytest.approx(0.48)


def test_native_layout_uses_one_uniform_scale() -> None:
    geometry = native_layout(640, 360, 4, 0.78, 0.96, 1440)
    assert geometry["scale"] == pytest.approx(2.25)
    assert geometry["total_height"] == geometry["hero_height"] + 4 * geometry["strip_height"]
    assert geometry["hero_height"] > geometry["strip_height"]


def test_duplicate_detection_on_synthetic_frames() -> None:
    same_a = _frame((10, 20, 30))
    same_b = _frame((10, 20, 30))
    different = _frame((200, 90, 40))
    assert frames_are_duplicates(same_a, same_b) is True
    assert frames_are_duplicates(same_a, different) is False


def test_native_build_keeps_uniform_scale_and_size() -> None:
    frames = [_striped_frame(i) for i in range(5)]
    image = build_stitched_image("native", frames)
    assert image.width == 1440
    geometry = native_layout(640, 360, 4, 0.78, 0.96, 1440)
    assert image.height == geometry["total_height"]


def test_script_build_produces_3x4_canvas() -> None:
    font = find_cjk_font()
    if font is None:
        pytest.skip("no CJK font on this system; script rendering refused honestly")
    frames = [_striped_frame(i) for i in range(5)]
    lines = [
        {"t": float(i), "text": f"placeholder reviewed line {i + 1}", "speaker": "Speaker A"}
        for i in range(5)
    ]
    image = build_stitched_image("script", frames, lines, font_path=font)
    assert image.size == (1440, 1920)


def test_script_build_refuses_without_font() -> None:
    frames = [_striped_frame(i) for i in range(2)]
    lines = [
        {"t": 0.0, "text": "placeholder line one", "speaker": "Speaker A"},
        {"t": 1.0, "text": "placeholder line two", "speaker": "Speaker A"},
    ]
    with pytest.raises(CapabilityError):
        build_stitched_image("script", frames, lines, font_path=None)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_extract_frame_from_synthetic_video(tmp_path: Path) -> None:
    from hevi.capabilities.native_subtitle_stitch import extract_frame, probe_video

    video = tmp_path / "synthetic.mp4"
    made = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=duration=3:size=1280x720:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        capture_output=True, text=True, timeout=120,
    )
    assert made.returncode == 0, made.stderr[-500:]
    probe = probe_video(video)
    assert probe["width"] == 1280 and probe["height"] == 720
    assert probe["duration_sec"] == pytest.approx(3.0, abs=0.2)
    out = tmp_path / "frame.png"
    extract_frame(video, 1.0, out)
    with Image.open(out) as frame:
        assert frame.size == (1280, 720)
