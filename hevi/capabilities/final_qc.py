"""Final-film quality gate (``qa.final_qc_gate``).

This is the last gate before a finished film is handed over. It is
deliberately separate from ``qa.export_gate``: export_qa checks the
container and loudness of an export, while this gate checks the film
as a viewer would meet it -- its probed shape, its first, middle and
last frames, whether the picture actually changes instead of sitting
still, whether forbidden pictographs slipped into the captions, and
whether the head and tail frames are clean.

The verdict is all-or-nothing: one failed check fails the whole
film, and the report lists every failed check by name. A check that
could not be run (no caption file supplied, no subtitle position
supplied) is reported as skipped with a reason, never silently
counted as a pass. Extracted keyframes are kept beside the report
so a human can still look at the exact frames the gate judged.

Two honest limits are recorded in the report, not hidden. First,
"no half-cut caption on the head/tail frames" is checked here as
"head and tail frames are present, correctly sized and not black";
detecting a caption sliced by the frame edge needs OCR or a human
look at the extracted frames, so the gate keeps those frames for
review and says so. Second, the picture-change rate is a signal,
not a verdict on quality: a film can move and still be bad, and a
quiet talking-head passage moves little; the floor below is a
tripwire for still-card films, not a taste score.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_BLACK_LUMA = 12.0
# Mean absolute per-pixel change (0-255 scale) between two small
# greyscale frames that counts as "the picture moved".
_CHANGE_DELTA = 2.0
# Default floor for the share of sampled intervals that must move.
# A still-card film scores near 0; a film with real motion scores
# well above this. The stricter per-beat 0.80 rule lives in
# video.motion_beat_chart, not here.
DEFAULT_MIN_CHANGE_RATE = 0.30

_EMOJI_RE = re.compile(
    "["
    "\U0001f000-\U0001faff"
    "\U00002600-\U000027bf"
    "\U0001f1e6-\U0001f1ff"
    "\uFE0F"
    "]"
)


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise CapabilityError(f"qa.final_qc_gate: required tool missing from PATH: {name}")
    return path


def probe_media(media_path: Path) -> dict[str, Any]:
    ffprobe = _require_tool("ffprobe")
    proc = subprocess.run(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,codec_name,r_frame_rate",
            "-show_entries", "format=duration",
            "-of", "json", str(media_path),
        ],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise CapabilityError(f"qa.final_qc_gate: ffprobe failed: {proc.stderr.strip()}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CapabilityError("qa.final_qc_gate: ffprobe output was not JSON") from exc
    streams = data.get("streams") or []
    if not streams:
        raise CapabilityError(f"qa.final_qc_gate: no video stream in {media_path}")
    stream = streams[0]
    fps_raw = str(stream.get("r_frame_rate", "0/1"))
    try:
        num, den = fps_raw.split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    duration = 0.0
    fmt = data.get("format") or {}
    if fmt.get("duration") is not None:
        try:
            duration = float(fmt["duration"])
        except (TypeError, ValueError):
            duration = 0.0
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "codec_name": str(stream.get("codec_name") or ""),
        "fps": fps,
        "duration_sec": duration,
    }


def _extract_frame(media_path: Path, at_sec: float, out_path: Path) -> None:
    ffmpeg = _require_tool("ffmpeg")
    attempts = [
        # Fast input seek first.
        [ffmpeg, "-y", "-v", "error", "-ss", f"{at_sec:.3f}",
         "-i", str(media_path), "-frames:v", "1", str(out_path)],
        # Accurate output seek as a fallback: an input seek past the
        # last frame's start time can land beyond the stream and
        # produce nothing, while output seeking still returns the
        # frame covering that timestamp.
        [ffmpeg, "-y", "-v", "error",
         "-i", str(media_path), "-ss", f"{at_sec:.3f}",
         "-frames:v", "1", str(out_path)],
    ]
    last_err = ""
    for cmd in attempts:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0 and out_path.is_file():
            return
        last_err = proc.stderr.strip()
    raise CapabilityError(
        f"qa.final_qc_gate: frame extraction at {at_sec:.3f}s failed: {last_err}"
    )


def _mean_luma(path: Path) -> float:
    with Image.open(path) as img:
        grey = img.convert("L")
        return float(ImageStat.Stat(grey).mean[0])


def _frame_change(a: Path, b: Path) -> float:
    with Image.open(a) as ia, Image.open(b) as ib:
        small_a = ia.convert("L").resize((64, 36))
        small_b = ib.convert("L").resize((64, 36))
        diff = ImageChops.difference(small_a, small_b)
        return float(ImageStat.Stat(diff).mean[0])


def _find_emoji(text: str) -> list[str]:
    return sorted(set(_EMOJI_RE.findall(text)))


def run_final_qc(
    media_path: Path,
    *,
    expected_duration_sec: float | None = None,
    duration_tolerance_sec: float = 0.5,
    expected_width: int | None = None,
    expected_height: int | None = None,
    expected_codec: str | None = None,
    subtitle_text: str | None = None,
    subtitle_path: Path | None = None,
    subtitle_bottom_fraction: float | None = None,
    min_change_rate: float = DEFAULT_MIN_CHANGE_RATE,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """Run every final check and return the full report.

    ``subtitle_bottom_fraction`` is the caption block's bottom edge
    as a fraction of frame height (0 = top, 1 = bottom). On a
    vertical frame it must stay at or above 0.80, i.e. clear of the
    bottom fifth where platform controls sit. When it is not
    supplied, the safe-zone check is skipped, not passed.
    """
    media_path = Path(media_path)
    if not media_path.is_file():
        raise CapabilityError(f"qa.final_qc_gate: media file not found: {media_path}")
    probe = probe_media(media_path)
    duration = probe["duration_sec"]
    width, height = probe["width"], probe["height"]
    if duration <= 0 or width <= 0 or height <= 0:
        raise CapabilityError(
            f"qa.final_qc_gate: unprobeable media (duration={duration}, "
            f"size={width}x{height}): {media_path}"
        )
    checks: dict[str, dict[str, Any]] = {}

    def _set(name: str, ok: bool, detail: str) -> None:
        checks[name] = {"pass": bool(ok), "detail": detail}

    def _skip(name: str, reason: str) -> None:
        checks[name] = {"pass": None, "detail": f"skipped: {reason}"}

    if expected_duration_sec is not None:
        gap = abs(duration - float(expected_duration_sec))
        _set("duration", gap <= duration_tolerance_sec,
             f"probed {duration:.3f}s vs expected {float(expected_duration_sec):.3f}s "
             f"(gap {gap:.3f}s, tolerance {duration_tolerance_sec}s)")
    else:
        _skip("duration", "no expected duration supplied")
    if expected_width is not None or expected_height is not None:
        ok = True
        bits = []
        if expected_width is not None:
            ok = ok and width == int(expected_width)
            bits.append(f"width {width} vs {int(expected_width)}")
        if expected_height is not None:
            ok = ok and height == int(expected_height)
            bits.append(f"height {height} vs {int(expected_height)}")
        _set("resolution", ok, "; ".join(bits))
    else:
        _skip("resolution", "no expected size supplied")
    if expected_codec is not None:
        _set("video_codec", probe["codec_name"] == expected_codec,
             f"probed {probe['codec_name']!r} vs expected {expected_codec!r}")
    else:
        _skip("video_codec", "no expected codec supplied")

    own_tmp = work_dir is None
    tmp = Path(tempfile.mkdtemp(prefix="final_qc_")) if own_tmp else Path(work_dir)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        # Keyframes: first, middle, last -- at least three, always.
        # The last stamp is the start of the final frame, not the
        # stream end: seeking to the end itself can miss the last
        # frame entirely.
        fps = probe["fps"]
        frame_span = (1.0 / fps) if fps and fps > 0 else 0.1
        last_stamp = max(0.0, duration - frame_span)
        stamps = sorted({0.0, duration / 2.0, last_stamp})
        frames: list[dict[str, Any]] = []
        for i, stamp in enumerate(stamps):
            out = tmp / f"keyframe_{i}.png"
            _extract_frame(media_path, stamp, out)
            luma = _mean_luma(out)
            frames.append({
                "at_sec": round(stamp, 3),
                "path": str(out),
                "mean_luma": round(luma, 2),
                "black": luma < _BLACK_LUMA,
            })
        head, tail = frames[0], frames[-1]
        _set("head_tail_clean",
             not head["black"] and not tail["black"],
             f"head luma {head['mean_luma']}, tail luma {tail['mean_luma']} "
             "(black below 12; caption edge-truncation still needs a look "
             "at the extracted frames, see visual_review_frames)")
        # Picture-change rate over the whole film, sampled each second.
        sample_times = [t for t in _sample_times(duration, last_stamp)]
        sample_paths: list[Path] = []
        for i, stamp in enumerate(sample_times):
            out = tmp / f"sample_{i}.png"
            _extract_frame(media_path, stamp, out)
            sample_paths.append(out)
        deltas = [
            _frame_change(sample_paths[i], sample_paths[i + 1])
            for i in range(len(sample_paths) - 1)
        ]
        moved = sum(1 for d in deltas if d >= _CHANGE_DELTA)
        rate = (moved / len(deltas)) if deltas else 0.0
        _set("picture_change_rate", rate >= min_change_rate,
             f"{moved}/{len(deltas)} sampled intervals moved "
             f"(rate {rate:.2f}, floor {min_change_rate:.2f}, "
             f"mean delta {sum(deltas) / len(deltas) if deltas else 0.0:.2f})")
    finally:
        if own_tmp:
            # Keyframes are part of the evidence: keep them only when
            # the caller gave us a work dir; otherwise clean up.
            import shutil as _shutil
            _shutil.rmtree(tmp, ignore_errors=True)
            frames = []  # type: ignore[assignment]

    caption = subtitle_text
    if caption is None and subtitle_path is not None:
        sp = Path(subtitle_path)
        if not sp.is_file():
            raise CapabilityError(f"qa.final_qc_gate: subtitle file not found: {sp}")
        caption = sp.read_text(encoding="utf-8", errors="replace")
    if caption is not None:
        found = _find_emoji(caption)
        _set("caption_no_emoji", not found,
             "no pictographs found" if not found else f"pictographs found: {found}")
    else:
        _skip("caption_no_emoji", "no caption text or file supplied")

    vertical = height > width
    if vertical:
        if subtitle_bottom_fraction is not None:
            bottom = float(subtitle_bottom_fraction)
            _set("vertical_caption_safe_zone", bottom <= 0.80,
                 f"caption bottom at {bottom:.2f} of frame height; "
                 "vertical films require at most 0.80 (clear of bottom fifth)")
        else:
            _skip("vertical_caption_safe_zone",
                  "no subtitle_bottom_fraction supplied")
    else:
        _skip("vertical_caption_safe_zone", "not a vertical frame")

    failed = [n for n, c in checks.items() if c["pass"] is False]
    verdict = "fail" if failed else "pass"
    return {
        "capability": "qa.final_qc_gate",
        "media_path": str(media_path),
        "probe": probe,
        "orientation": "vertical" if vertical else "horizontal",
        "checks": checks,
        "failed_checks": failed,
        "skipped_checks": [n for n, c in checks.items() if c["pass"] is None],
        "visual_review_frames": [f["path"] for f in frames],
        "verdict": verdict,
        "verdict_note": (
            "Fail: at least one check failed, listed in failed_checks. "
            "A pass still leaves caption edge-truncation to the human "
            "look at visual_review_frames."
            if verdict == "fail" else
            "Pass: every runnable check passed; skipped checks are listed "
            "separately and were not counted as passes."
        ),
    }


def _sample_times(duration: float, last_stamp: float | None = None) -> list[float]:
    times = [0.0]
    t = 1.0
    while t < duration - 0.05:
        times.append(t)
        t += 1.0
    if duration > 0.1:
        times.append(max(0.0, duration - 0.05 if last_stamp is None else last_stamp))
    # De-duplicate while keeping order.
    seen: list[float] = []
    for t in times:
        if all(abs(t - s) > 0.01 for s in seen):
            seen.append(t)
    return seen


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {}
    for key, conv in (
        ("expected_duration_sec", float),
        ("duration_tolerance_sec", float),
        ("expected_width", int),
        ("expected_height", int),
        ("min_change_rate", float),
        ("subtitle_bottom_fraction", float),
    ):
        if params.get(key) is not None:
            kwargs[key] = conv(params[key])
    if params.get("expected_codec"):
        kwargs["expected_codec"] = str(params["expected_codec"])
    if params.get("subtitle_text"):
        kwargs["subtitle_text"] = str(params["subtitle_text"])
    if params.get("subtitle_path"):
        kwargs["subtitle_path"] = Path(params["subtitle_path"])
    report = run_final_qc(Path(params["media_path"]), work_dir=out_dir, **kwargs)
    report_path = out_dir / "final_qc_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        mp4=str(params["media_path"]),
        duration_s=float(report["probe"]["duration_sec"]),
        sha256=compute_sha256(Path(params["media_path"])),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "pass": report["verdict"] == "pass",
            "failed_checks": report["failed_checks"],
            "skipped_checks": report["skipped_checks"],
        },
    )


def register_final_qc_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.final_qc_gate",
            kind="video",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "media_path": {"type": "string"},
                    "expected_duration_sec": {"type": "number", "exclusiveMinimum": 0},
                    "duration_tolerance_sec": {"type": "number", "minimum": 0},
                    "expected_width": {"type": "integer", "exclusiveMinimum": 0},
                    "expected_height": {"type": "integer", "exclusiveMinimum": 0},
                    "expected_codec": {"type": "string"},
                    "subtitle_text": {"type": "string"},
                    "subtitle_path": {"type": "string"},
                    "subtitle_bottom_fraction": {"type": "number", "minimum": 0, "maximum": 1},
                    "min_change_rate": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["media_path"],
                "additionalProperties": False,
            },
            cpu_cost_hint=1.0,
            render=_render,
            description=(
                "Final-film QC gate: ffprobe duration/resolution/codec, "
                "first/middle/last keyframes, head/tail black check, "
                "whole-film picture-change rate, caption pictograph "
                "ban, and vertical caption safe zone (bottom fifth). "
                "Any failed check fails the whole film; failures are "
                "listed, skipped checks are never counted as passes."
            ),
            line="qa",
        )
    )
    return ["qa.final_qc_gate"]


register_final_qc_capabilities_once()
