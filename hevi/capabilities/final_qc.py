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

An optional defect scan (``defect_scan=True``) adds the
rendered-film defect checks of the video-director method, cleanly
rewritten here: single-frame flashes, pops, detected cuts compared
with planned cuts, frozen runs, flat runs and, for loops only, the
loop seam. It reuses ``probe_media`` and ``_extract_frame`` and
samples small greyscale frames at up to 8 fps (or fps/4, whichever
is lower). Flash and cut mismatches fail; frozen, flat and pop
findings are warnings recorded in the report and do not fail the
film on their own. When the scan cannot run (ffmpeg missing, too
few frames), its checks are skipped, never counted as passes.
Loudness is deliberately not re-checked here: ``mix_recipe``
remains the loudness authority.

Two further optional checks close the stale-timeline gap the
same way ``edit.subtitle_discipline`` does, and wire the
generation-consistency measurement in without ever calling a
service. ``edited=True`` (or a supplied ``transcript_source``)
requires a post-edit retranscription source, or the
``stale_timeline`` check fails; with neither supplied the check
is skipped, never passed. ``generation_artifacts`` (the offline
contract in ``qa.prompt_eval_harness``) is measured by that
harness; a partial or failed measurement fails the
``generation_consistency`` check, and with no artifacts it is
skipped. ``expected_vo_lines``/``asr_text``/``vo_word_timings``
feed the same harness's dialogue measurement alone, as the
``vo_asr`` check: the word timings are the
``audio.forced_align`` output shape, supplied by the caller
after a real alignment run -- this gate never calls Monid.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from statistics import median
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

# Defect-scan defaults: method defaults from the video-director
# rendered-film QA method (see VIDEO_DIRECTOR_ATTRIBUTION.md).
# All are overridable per call; none of them redefines loudness.
DEFAULT_DEFECT_MAX_SAMPLE_FPS = 8.0
DEFAULT_DEFECT_FLASH_FACTOR = 4.0
DEFAULT_DEFECT_FLASH_MIN = 2.0
DEFAULT_DEFECT_FLASH_SKIP_FACTOR = 0.35
DEFAULT_DEFECT_CUT_FACTOR = 3.5
DEFAULT_DEFECT_CUT_MIN = 6.0
DEFAULT_DEFECT_CUT_TOLERANCE_SEC = 0.5
DEFAULT_DEFECT_FREEZE_EPS = 0.25
DEFAULT_DEFECT_FREEZE_SEC = 1.0
DEFAULT_DEFECT_FLAT_STD = 6.0
DEFAULT_DEFECT_LOOP_SEAM_RATIO = 2.0
_DEFECT_SAMPLE_WIDTH = 192

# Transcript sources that count as a post-edit retranscription
# (same set as edit.subtitle_discipline; a re-edited film whose
# captions/transcript were not re-made from the edited audio is
# stale, however right the words look).
_FRESH_TRANSCRIPT_SOURCES = frozenset({
    "post_edit_retranscription", "post_edit_transcript", "fresh_transcription",
})

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
    # Seek a hair before the requested time, at microsecond
    # precision: formatting at_sec to milliseconds rounds
    # 2.9666...s up to 2.967s, past the last frame's start, and
    # ffmpeg then returns nothing for that frame. The 0.1ms
    # epsilon is far below one frame, so it cannot pull in the
    # previous frame.
    seek = max(0.0, at_sec - 0.0001)
    attempts = [
        # Fast input seek first.
        [ffmpeg, "-y", "-v", "error", "-ss", f"{seek:.6f}",
         "-i", str(media_path), "-frames:v", "1", str(out_path)],
        # Accurate output seek as a fallback: an input seek past the
        # last frame's start time can land beyond the stream and
        # produce nothing, while output seeking still returns the
        # frame covering that timestamp.
        [ffmpeg, "-y", "-v", "error",
         "-i", str(media_path), "-ss", f"{seek:.6f}",
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


def _small_grey(path: Path) -> Any:
    with Image.open(path) as img:
        grey = img.convert("L")
        width, height = grey.size
        new_height = max(1, round(_DEFECT_SAMPLE_WIDTH * height / width))
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)
        return grey.resize((_DEFECT_SAMPLE_WIDTH, new_height), resample)


def _grey_diff(a: Any, b: Any) -> float:
    diff = ImageChops.difference(a, b)
    return float(ImageStat.Stat(diff).mean[0])


def _grey_std(frame: Any) -> float:
    return float(ImageStat.Stat(frame).stddev[0])


def _skipped_defect_checks(reason: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    names = (
        "defect_flash", "defect_unplanned_cuts", "defect_frozen",
        "defect_flat", "defect_loop_seam",
    )
    checks = {
        name: {"pass": None, "detail": f"skipped: {reason}", "events": []}
        for name in names
    }
    summary: dict[str, Any] = {
        "enabled": True, "status": "skipped", "reason": reason,
        "flash": [], "pops": [], "cuts_detected": [], "missing_cuts": [],
        "unplanned_cuts": [], "frozen": [], "flat": [], "loop_seam": None,
        "warnings": [reason],
    }
    return checks, summary


def _run_defect_scan(
    media_path: Path,
    tmp: Path,
    probe: dict[str, Any],
    *,
    planned_cuts: list[float] | None,
    is_loop: bool,
    max_sample_fps: float,
    flash_factor: float,
    flash_min: float,
    flash_skip_factor: float,
    cut_factor: float,
    cut_min: float,
    cut_tolerance_sec: float,
    freeze_eps: float,
    freeze_sec: float,
    flat_std: float,
    loop_seam_ratio: float,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Sample small greyscale frames and scan for render defects.

    Returns (checks, summary). Anything that prevents a real scan
    yields skipped checks, never a fabricated pass.
    """
    duration = float(probe["duration_sec"])
    fps = float(probe["fps"])
    sample_fps = max_sample_fps
    if fps > 0:
        sample_fps = min(max_sample_fps, fps / 4.0)
    if sample_fps <= 0 or duration <= 0:
        return _skipped_defect_checks("unusable probe for defect sampling")
    interval = 1.0 / sample_fps
    times: list[float] = []
    t = 0.0
    while t < duration - 0.005:
        times.append(round(t, 4))
        t += interval
    if len(times) < 3:
        return _skipped_defect_checks(
            f"only {len(times)} defect samples for a {duration:.3f}s film"
        )
    frames: list[Any] = []
    kept_times: list[float] = []
    for i, stamp in enumerate(times):
        out = tmp / f"defect_{i}.png"
        try:
            _extract_frame(media_path, stamp, out)
        except CapabilityError:
            continue
        try:
            frames.append(_small_grey(out))
            kept_times.append(stamp)
        except Exception:
            continue
    if len(frames) < 3:
        return _skipped_defect_checks(
            f"only {len(frames)} defect frames could be extracted"
        )
    times = kept_times
    diffs = [_grey_diff(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]
    stds = [_grey_std(frame) for frame in frames]
    median_step = float(median(diffs)) if diffs else 0.0
    skip_diffs = [
        _grey_diff(frames[i - 1], frames[i + 1]) for i in range(1, len(frames) - 1)
    ]

    # Flash: one frame far from both neighbours while the neighbours
    # are close to each other.
    flash_events: list[dict[str, Any]] = []
    flash_frames: set[int] = set()
    flash_thresh = max(flash_min, flash_factor * median_step)
    for i in range(1, len(frames) - 1):
        d_prev, d_next, skip = diffs[i - 1], diffs[i], skip_diffs[i - 1]
        if d_prev >= flash_thresh and d_next >= flash_thresh \
                and skip < flash_skip_factor * min(d_prev, d_next):
            flash_events.append({
                "t_sec": times[i], "frame_index": i,
                "diff_prev": round(d_prev, 2), "diff_next": round(d_next, 2),
                "skip_diff": round(skip, 2),
            })
            flash_frames.add(i)

    # Cuts: a boundary diff far above its local median, excluding
    # boundaries that belong to a flash frame.
    cut_events: list[dict[str, Any]] = []
    for i, d in enumerate(diffs):
        if i in flash_frames or (i + 1) in flash_frames:
            continue
        window = diffs[max(0, i - 15):i] + diffs[i + 1:i + 16]
        local_med = float(median(window)) if window else median_step
        if d > max(cut_min, cut_factor * (local_med + 0.5)):
            cut_t = times[i + 1]
            if cut_events and cut_t - cut_events[-1]["t_sec"] < 0.25:
                if d > cut_events[-1]["diff"]:
                    cut_events[-1] = {"t_sec": cut_t, "diff": round(d, 2)}
                continue
            cut_events.append({"t_sec": cut_t, "diff": round(d, 2)})
    detected_cuts = [event["t_sec"] for event in cut_events]

    # Pops: small spikes that are neither cuts nor flashes (warnings).
    cut_times = set(detected_cuts)
    pop_events: list[dict[str, Any]] = []
    for i in range(1, len(diffs) - 1):
        d = diffs[i]
        if d > 2.0 and d > 3.0 * diffs[i - 1] and d > 3.0 * diffs[i + 1] \
                and times[i + 1] not in cut_times and i not in flash_frames \
                and (i + 1) not in flash_frames:
            pop_events.append({"t_sec": times[i + 1], "diff": round(d, 2)})

    # Frozen: near-zero change sustained for at least freeze_sec.
    frozen_events: list[dict[str, Any]] = []
    run_start: int | None = None
    for i, d in enumerate(diffs + [math.inf]):
        if d < freeze_eps:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None:
                run_end = i
                run_sec = times[run_end] - times[run_start]
                if run_sec >= freeze_sec:
                    frozen_events.append({
                        "start_sec": times[run_start],
                        "end_sec": times[run_end],
                        "duration_sec": round(run_sec, 3),
                        "final_hold": run_end == len(diffs),
                    })
                run_start = None

    # Flat: low-std frames in a run (first frame excluded).
    flat_events: list[dict[str, Any]] = []
    run_start = None
    for i in range(1, len(stds) + 1):
        flat = i < len(stds) and stds[i] < flat_std
        if flat and run_start is None:
            run_start = i
        if not flat and run_start is not None:
            if i - run_start >= 2:
                flat_events.append({
                    "start_sec": times[run_start],
                    "end_sec": times[i - 1],
                    "frame_count": i - run_start,
                })
            run_start = None

    warnings: list[str] = []
    for event in pop_events:
        warnings.append(f"pop at {event['t_sec']:.3f}s (diff {event['diff']})")
    for event in frozen_events:
        note = " (final hold)" if event["final_hold"] else ""
        warnings.append(
            f"frozen {event['duration_sec']:.2f}s from {event['start_sec']:.3f}s{note}"
        )
    for event in flat_events:
        warnings.append(
            f"flat {event['frame_count']} frames from {event['start_sec']:.3f}s"
        )

    checks: dict[str, dict[str, Any]] = {}
    if flash_events:
        checks["defect_flash"] = {
            "pass": False,
            "detail": f"{len(flash_events)} flash frame(s) at "
                      f"{[e['t_sec'] for e in flash_events]}",
            "events": flash_events,
        }
    else:
        checks["defect_flash"] = {
            "pass": True,
            "detail": f"no flash in {len(frames)} sampled frames "
                      f"(threshold {flash_thresh:.2f}, median step {median_step:.2f})",
            "events": [],
        }

    if planned_cuts is None or len(planned_cuts) == 0:
        checks["defect_unplanned_cuts"] = {
            "pass": None,
            "detail": "skipped: no planned_cuts supplied to compare against",
            "events": cut_events,
        }
        missing_cuts: list[float] = []
        unplanned_cuts: list[float] = []
    else:
        missing_cuts = [
            p for p in planned_cuts
            if not any(abs(p - d) <= cut_tolerance_sec for d in detected_cuts)
        ]
        unplanned_cuts = [
            d for d in detected_cuts
            if not any(abs(d - p) <= cut_tolerance_sec for p in planned_cuts)
        ]
        if missing_cuts or unplanned_cuts:
            checks["defect_unplanned_cuts"] = {
                "pass": False,
                "detail": f"missing planned cuts {missing_cuts}; "
                          f"unplanned cuts {unplanned_cuts}; "
                          f"detected {detected_cuts} (tolerance {cut_tolerance_sec}s)",
                "events": cut_events,
            }
        else:
            checks["defect_unplanned_cuts"] = {
                "pass": True,
                "detail": f"detected cuts {detected_cuts} match planned "
                          f"{list(planned_cuts)} within {cut_tolerance_sec}s",
                "events": cut_events,
            }

    checks["defect_frozen"] = {
        "pass": True,
        "detail": (
            f"warn: {len(frozen_events)} frozen run(s)" if frozen_events
            else f"no frozen run >= {freeze_sec}s"
        ),
        "events": frozen_events,
        "warnings": [w for w in warnings if w.startswith("frozen")],
    }
    checks["defect_flat"] = {
        "pass": True,
        "detail": (
            f"warn: {len(flat_events)} flat run(s)" if flat_events
            else f"no flat run (std < {flat_std}) beyond the first frame"
        ),
        "events": flat_events,
        "warnings": [w for w in warnings if w.startswith("flat")],
    }

    loop_seam: dict[str, Any] | None = None
    if not is_loop:
        checks["defect_loop_seam"] = {
            "pass": None,
            "detail": "skipped: not a loop film (is_loop is False)",
            "events": [],
        }
    else:
        seam_diff = _grey_diff(frames[0], frames[-1])
        speed_in = diffs[0] if diffs else 0.0
        speed_out = diffs[-1] if diffs else 0.0
        if speed_in > 0:
            speed_ratio = speed_out / speed_in
        else:
            speed_ratio = 1.0 if speed_out == 0 else math.inf
        seam_ok = (seam_diff <= loop_seam_ratio * median_step) or seam_diff < 0.5
        speed_ok = 0.5 <= speed_ratio <= 2.0
        loop_seam = {
            "seam_diff": round(seam_diff, 2),
            "median_step": round(median_step, 2),
            "seam_ratio": round(seam_diff / median_step, 2) if median_step > 0 else None,
            "speed_ratio": round(speed_ratio, 2) if math.isfinite(speed_ratio) else None,
        }
        checks["defect_loop_seam"] = {
            "pass": bool(seam_ok and speed_ok),
            "detail": f"seam diff {seam_diff:.2f} vs median step {median_step:.2f}; "
                      f"in/out speed ratio {speed_ratio if math.isfinite(speed_ratio) else 'inf'} "
                      f"(required 0.5-2.0)",
            "events": [loop_seam],
        }

    failed = any(c["pass"] is False for c in checks.values())
    status = "fail" if failed else ("warn" if warnings else "pass")
    summary = {
        "enabled": True,
        "status": status,
        "sample_fps": round(sample_fps, 3),
        "sample_count": len(frames),
        "median_step": round(median_step, 3),
        "flash": flash_events,
        "pops": pop_events,
        "cuts_detected": detected_cuts,
        "missing_cuts": missing_cuts if planned_cuts else [],
        "unplanned_cuts": unplanned_cuts if planned_cuts else [],
        "frozen": frozen_events,
        "flat": flat_events,
        "loop_seam": loop_seam,
        "warnings": warnings,
    }
    return checks, summary


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
    defect_scan: bool = False,
    planned_cuts: list[float] | None = None,
    is_loop: bool = False,
    defect_max_sample_fps: float = DEFAULT_DEFECT_MAX_SAMPLE_FPS,
    defect_flash_factor: float = DEFAULT_DEFECT_FLASH_FACTOR,
    defect_flash_min: float = DEFAULT_DEFECT_FLASH_MIN,
    defect_flash_skip_factor: float = DEFAULT_DEFECT_FLASH_SKIP_FACTOR,
    defect_cut_factor: float = DEFAULT_DEFECT_CUT_FACTOR,
    defect_cut_min: float = DEFAULT_DEFECT_CUT_MIN,
    defect_cut_tolerance_sec: float = DEFAULT_DEFECT_CUT_TOLERANCE_SEC,
    defect_freeze_eps: float = DEFAULT_DEFECT_FREEZE_EPS,
    defect_freeze_sec: float = DEFAULT_DEFECT_FREEZE_SEC,
    defect_flat_std: float = DEFAULT_DEFECT_FLAT_STD,
    defect_loop_seam_ratio: float = DEFAULT_DEFECT_LOOP_SEAM_RATIO,
    edited: bool = False,
    transcript_source: str | None = None,
    generation_artifacts: dict[str, Any] | None = None,
    expected_vo_lines: list[str] | None = None,
    asr_text: str | None = None,
    vo_word_timings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run every final check and return the full report.

    ``subtitle_bottom_fraction`` is the caption block's bottom edge
    as a fraction of frame height (0 = top, 1 = bottom). On a
    vertical frame it must stay at or above 0.80, i.e. clear of the
    bottom fifth where platform controls sit. When it is not
    supplied, the safe-zone check is skipped, not passed.

    ``defect_scan`` is off by default so existing callers keep
    exactly the old behaviour. When on, ``planned_cuts`` (seconds)
    is compared with detected cuts and ``is_loop`` enables the
    loop-seam check; the remaining ``defect_*`` arguments are the
    configurable scan thresholds.

    ``edited`` declares the film was re-cut after its transcript
    was made: then ``transcript_source`` must name a post-edit
    retranscription, or the ``stale_timeline`` check fails. A
    supplied non-fresh ``transcript_source`` fails the same check
    even without ``edited``. ``generation_artifacts`` and the
    VO arguments are offline evidence only (see the module
    docstring); neither check runs when its evidence is absent.
    """
    media_path = Path(media_path)
    if not media_path.is_file():
        raise CapabilityError(f"qa.final_qc_gate: media file not found: {media_path}")
    planned: list[float] | None = None
    if planned_cuts is not None:
        planned = []
        for cut in planned_cuts:
            if not isinstance(cut, (int, float)) or isinstance(cut, bool):
                raise CapabilityError(
                    f"qa.final_qc_gate: planned_cuts must be numbers, got {cut!r}"
                )
            planned.append(float(cut))
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
    defect_summary: dict[str, Any] | None = None
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
        if defect_scan:
            defect_checks, defect_summary = _run_defect_scan(
                media_path, tmp, probe,
                planned_cuts=planned, is_loop=is_loop,
                max_sample_fps=defect_max_sample_fps,
                flash_factor=defect_flash_factor,
                flash_min=defect_flash_min,
                flash_skip_factor=defect_flash_skip_factor,
                cut_factor=defect_cut_factor,
                cut_min=defect_cut_min,
                cut_tolerance_sec=defect_cut_tolerance_sec,
                freeze_eps=defect_freeze_eps,
                freeze_sec=defect_freeze_sec,
                flat_std=defect_flat_std,
                loop_seam_ratio=defect_loop_seam_ratio,
            )
            checks.update(defect_checks)
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

    # Stale timeline: a re-edited film needs a post-edit
    # retranscription. Missing provenance is skipped (the caller
    # never declared an edit), never counted as a pass.
    if edited or transcript_source is not None:
        fresh = transcript_source in _FRESH_TRANSCRIPT_SOURCES
        _set("stale_timeline", fresh,
             f"transcript_source {transcript_source!r} "
             f"{'is' if fresh else 'is not'} a post-edit retranscription"
             + ("; the film was re-edited, so a fresh transcript is required"
                if edited and not fresh else ""))
    else:
        _skip("stale_timeline", "no edit declared and no transcript_source supplied")

    # VO / ASR: dialogue measurement over supplied evidence only.
    consistency: dict[str, Any] | None = None
    vo_supplied = (
        expected_vo_lines is not None or asr_text is not None
        or vo_word_timings is not None)
    if vo_supplied:
        from hevi.capabilities.prompt_eval_harness import (
            measure_generation_consistency,
        )

        vo_result = measure_generation_consistency({
            "prompt": {"expected_lines": list(expected_vo_lines or [])},
            "asr_text": asr_text,
            "word_timings": vo_word_timings,
        })
        dialogue = next(
            m for m in vo_result["measurements"] if m["name"] == "dialogue_asr")
        if dialogue["status"] == "measured":
            _set("vo_asr", dialogue["verdict"] == "pass", dialogue["detail"])
        else:
            _set("vo_asr", False,
                 "VO evidence supplied but the dialogue measurement is "
                 f"unmeasured: {dialogue['detail']}")
    else:
        _skip("vo_asr", "no VO lines / ASR transcript / word timings supplied")

    # Generation consistency: the full offline-artifact contract,
    # measured by qa.prompt_eval_harness. Partial evidence fails:
    # a half-measured film is not a measured film.
    if generation_artifacts is not None:
        from hevi.capabilities.prompt_eval_harness import (
            measure_generation_consistency,
        )

        consistency = measure_generation_consistency(generation_artifacts)
        if consistency["verdict"] == "pass":
            _set("generation_consistency", True,
                 f"all {consistency['measured_count']} consistency measurements "
                 "pass on the supplied offline artifacts")
        elif consistency["verdict"] == "fail":
            failed_names = [m["name"] for m in consistency["measurements"]
                            if m["verdict"] == "fail"]
            _set("generation_consistency", False,
                 f"consistency verdict fail ({consistency['status']}); "
                 f"failed: {failed_names}")
        else:
            _set("generation_consistency", False,
                 f"consistency {consistency['status']}: only "
                 f"{consistency['measured_count']}/4 measurements have "
                 "evidence; the rest stay planned_not_measured")
    else:
        _skip("generation_consistency", "no generation artifacts supplied")

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
        "defect_scan": defect_summary,
        "generation_consistency": consistency,
        "edited": edited,
        "transcript_source": transcript_source,
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
        ("defect_max_sample_fps", float),
        ("defect_flash_factor", float),
        ("defect_cut_tolerance_sec", float),
        ("defect_freeze_sec", float),
        ("defect_flat_std", float),
    ):
        if params.get(key) is not None:
            kwargs[key] = conv(params[key])
    if params.get("defect_scan") is not None:
        kwargs["defect_scan"] = bool(params["defect_scan"])
    if params.get("is_loop") is not None:
        kwargs["is_loop"] = bool(params["is_loop"])
    if params.get("edited") is not None:
        kwargs["edited"] = bool(params["edited"])
    if params.get("transcript_source"):
        kwargs["transcript_source"] = str(params["transcript_source"])
    if params.get("generation_artifacts") is not None:
        kwargs["generation_artifacts"] = dict(params["generation_artifacts"])
    if params.get("expected_vo_lines") is not None:
        kwargs["expected_vo_lines"] = [str(line) for line in params["expected_vo_lines"]]
    if params.get("asr_text"):
        kwargs["asr_text"] = str(params["asr_text"])
    if params.get("vo_word_timings") is not None:
        kwargs["vo_word_timings"] = list(params["vo_word_timings"])
    if params.get("planned_cuts") is not None:
        kwargs["planned_cuts"] = [float(c) for c in params["planned_cuts"]]
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
            "defect_scan": report["defect_scan"],
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
                    "defect_scan": {"type": "boolean"},
                    "planned_cuts": {"type": "array", "items": {"type": "number"}},
                    "is_loop": {"type": "boolean"},
                    "defect_max_sample_fps": {"type": "number", "exclusiveMinimum": 0},
                    "defect_flash_factor": {"type": "number", "exclusiveMinimum": 0},
                    "defect_cut_tolerance_sec": {"type": "number", "minimum": 0},
                    "defect_freeze_sec": {"type": "number", "exclusiveMinimum": 0},
                    "defect_flat_std": {"type": "number", "minimum": 0},
                    "edited": {"type": "boolean"},
                    "transcript_source": {"type": "string"},
                    "generation_artifacts": {"type": "object"},
                    "expected_vo_lines": {"type": "array", "items": {"type": "string"}},
                    "asr_text": {"type": "string"},
                    "vo_word_timings": {"type": "array", "items": {"type": "object"}},
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
                "listed, skipped checks are never counted as passes. "
                "Optional defect_scan adds flash/pop, cut-vs-plan, "
                "frozen, flat and loop-seam checks on sampled frames. "
                "Optional edited/transcript_source adds the stale-"
                "timeline check, and offline generation artifacts / "
                "VO evidence add the generation-consistency and vo_asr "
                "checks (no service is ever called)."
            ),
            line="qa",
        )
    )
    return ["qa.final_qc_gate"]


register_final_qc_capabilities_once()
