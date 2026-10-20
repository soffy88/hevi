"""Unified export QA gate — the pre-delivery checklist as one check.

``run_export_qa`` inspects a finished media file (normally the final mp4)
and returns a JSON-serialisable report.  It deliberately *reuses* the
measurements the repo already trusts instead of re-inventing them:

* container / streams — ``ffprobe`` (same JSON probe style as
  ``hevi.layer4_legacy.scene3d.renderer.ffprobe``);
* black frames — frame luma statistics from
  ``hevi.layer4_legacy.zerolines.oskill_impl.qa.frame_stats``: a sampled
  frame whose mean luma is < 12 counts as black, and the black-frame
  ratio must stay at or below ``max_black_ratio`` (default 0.1, the
  ``max_black_ratio`` used by zerolines ``judge()``);
* loudness / true peak / clipping — earshot ``measure`` via
  ``hevi.audio.earshot_client.measure``, the exact path (and the exact
  thresholds) of the ``audio.earshot_gate`` capability: true peak
  <= -1.0 dBTP, integrated loudness -14 ± 2 LUFS, zero clipped samples.

Check list (each ``{name, status, detail, value, threshold}`` with
``status`` in ``pass | warn | fail | skip``):

===================  =====================================================
container_codec      format is mov/mp4, video h264, audio aac
                     (no audio track at all -> warn, it is annotated)
resolution_aspect    width/height + orientation vs ``expect.aspect``
fps                  frame rate vs ``expect.fps`` (optional)
black_frames         black-frame ratio <= 0.1 (zerolines口径, see above)
loudness             earshot: LUFS / true peak / clipping (one check)
av_sync              |video - audio| stream duration <= 0.5 s
ending_audio         last 0.3 s must not be a high-energy hard cut:
                     measurable via tail/overall RMS ratio + fade probe;
                     a suspected abrupt ending is *warn*, never fail —
                     a loud ending can be an artistic choice, a truncated
                     file cannot (that is what av_sync / black checks
                     are for)
last_frame_black     final frame black -> warn (credits/fade-outs are
                     legitimate, so this never fails the export)
subtitles            only when ``expect.subtitles`` is true: embedded
                     subtitle stream or same-stem ``.srt`` sidecar
===================  =====================================================

Overall verdict: ``fail`` if any check fails, else ``warn`` if any check
warns, else ``pass``.  ``report["pass"]`` is ``verdict != "fail"``
(warnings do not block delivery, they demand a human look — the same
role yellow lights play in film_gate).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

# --- thresholds (single source of truth; expect may override per call) ---
MAX_BLACK_RATIO = 0.1  # zerolines qa.judge(max_black_ratio=...)
BLACK_LUMA = 12.0  # zerolines frame_stats: frame mean luma < 12 == black
LUFS_TARGET = -14.0  # earshot_gate defaults
LUFS_TOLERANCE = 2.0
TRUE_PEAK_CEILING_DBTP = -1.0
AV_SYNC_TOLERANCE_S = 0.5
FPS_TOLERANCE = 0.6  # absolute fps slack when comparing to expect.fps
# Ending probe: the last 0.3 s still carrying most of the programme's
# energy *and* the final 50 ms not decaying at all == cut mid-sound.
TAIL_WINDOW_S = 0.3
TAIL_END_S = 0.05
TAIL_RATIO_WARN = 0.8  # tail RMS / overall RMS above this = still loud
TAIL_FADE_RATIO = 0.6  # end RMS / tail RMS above this = no fade-out
_SAMPLE_FPS = 4.0  # frame sampling rate for the black-frame ratio
_SAMPLE_WIDTH = 160  # frame_stats only needs per-frame mean luma

_STATUSES = ("pass", "warn", "fail", "skip")


def _check(
    name: str,
    status: str,
    detail: str,
    *,
    value: Any = None,
    threshold: str | None = None,
) -> dict[str, Any]:
    assert status in _STATUSES, status
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "value": value,
        "threshold": threshold,
    }


def _overall(checks: list[dict[str, Any]]) -> str:
    statuses = {c["status"] for c in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def _expect_get(expect: Any, key: str, default: Any = None) -> Any:
    if expect is None:
        return default
    if isinstance(expect, dict):
        return expect.get(key, default)
    return getattr(expect, key, default)


# ---------------------------------------------------------------------------
# ffprobe
# ---------------------------------------------------------------------------


def _ffprobe_bin() -> str:
    return shutil.which("ffprobe") or "ffprobe"


def _ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _probe(media_path: Path) -> dict[str, Any] | None:
    """ffprobe JSON; ``None`` when the file cannot be probed at all."""
    try:
        proc = subprocess.run(
            [
                _ffprobe_bin(),
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(media_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _stream_fps(stream: dict[str, Any]) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        raw = str(stream.get(key) or "")
        if "/" in raw:
            num, _, den = raw.partition("/")
            try:
                n, d = float(num), float(den)
            except ValueError:
                continue
            if d:
                return n / d
        elif raw:
            try:
                return float(raw)
            except ValueError:
                continue
    return 0.0


def _stream_duration(stream: dict[str, Any], fallback: float) -> float:
    try:
        return float(stream.get("duration") or fallback)
    except (TypeError, ValueError):
        return fallback


def _aspect_matches(width: int, height: int, expect_aspect: str) -> bool:
    try:
        ew, _, eh = str(expect_aspect).partition(":")
        ew_f, eh_f = float(ew), float(eh)
    except ValueError:
        return False
    if ew_f <= 0 or eh_f <= 0 or height <= 0:
        return False
    # Cross-multiplied comparison with 2% slack for odd pixel counts
    # (e.g. 720x1280 vs 9:16 is exact; 1079x1919 should still pass).
    return abs(width * eh_f - height * ew_f) <= 0.02 * height * ew_f


def _orientation(width: int, height: int) -> str:
    if height > width:
        return "vertical"
    if width > height:
        return "horizontal"
    return "square"


# ---------------------------------------------------------------------------
# Frame sampling (black frames) — zerolines frame_stats口径
# ---------------------------------------------------------------------------


def _sample_frame_lumas(media_path: Path, width: int, height: int) -> Any:
    """Decode sampled grayscale frames; returns an (N, h, w) array or None.

    Uses the zerolines definition (mean luma per frame) via ffmpeg rawvideo
    so no OpenCV dependency is introduced.  ``None`` means "could not
    measure" — callers must surface that, never treat it as zero black.
    """
    try:
        import numpy as np
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    scaled_h = max(2, round(height * _SAMPLE_WIDTH / width) // 2 * 2)
    vf = f"fps={_SAMPLE_FPS},scale={_SAMPLE_WIDTH}:{scaled_h},format=gray"
    try:
        proc = subprocess.run(
            [
                _ffmpeg_bin(),
                "-v",
                "error",
                "-i",
                str(media_path),
                "-vf",
                vf,
                "-f",
                "rawvideo",
                "-",
            ],
            capture_output=True,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    frame_bytes = _SAMPLE_WIDTH * scaled_h
    n = len(proc.stdout) // frame_bytes
    if n == 0:
        return None
    return np.frombuffer(proc.stdout[: n * frame_bytes], dtype=np.uint8).reshape(
        n, scaled_h, _SAMPLE_WIDTH
    )


def _last_frame_luma(media_path: Path) -> float | None:
    """Mean luma of the final frame (from the last 0.5 s), or None."""
    try:
        import numpy as np
    except Exception:
        return None
    try:
        proc = subprocess.run(
            [
                _ffmpeg_bin(),
                "-v",
                "error",
                "-sseof",
                "-0.5",
                "-i",
                str(media_path),
                "-frames:v",
                "1",
                "-vf",
                "scale=160:-2,format=gray",
                "-f",
                "rawvideo",
                "-",
            ],
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return float(np.frombuffer(proc.stdout, dtype=np.uint8).astype(np.float32).mean())


# ---------------------------------------------------------------------------
# Ending audio probe (RMS of tail vs programme)
# ---------------------------------------------------------------------------


def _audio_rms_profile(media_path: Path) -> dict[str, float] | None:
    """Decode audio to 8 kHz mono float and measure RMS levels.

    Returns overall / tail (last 0.3 s) / end (last 50 ms) RMS plus the
    tail ratio, or ``None`` when there is no decodable audio.
    """
    try:
        import numpy as np
    except Exception:
        return None
    sr = 8000
    try:
        proc = subprocess.run(
            [
                _ffmpeg_bin(),
                "-v",
                "error",
                "-i",
                str(media_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(sr),
                "-f",
                "f32le",
                "-",
            ],
            capture_output=True,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or len(proc.stdout) < 4:
        return None
    samples = np.frombuffer(proc.stdout, dtype=np.float32)
    if samples.size < sr // 10:
        return None
    overall = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    tail_n = min(samples.size, int(TAIL_WINDOW_S * sr))
    end_n = min(tail_n, int(TAIL_END_S * sr))
    tail = samples[-tail_n:]
    end = samples[-end_n:]
    tail_rms = float(np.sqrt(np.mean(tail.astype(np.float64) ** 2)))
    end_rms = float(np.sqrt(np.mean(end.astype(np.float64) ** 2)))
    return {
        "overall_rms": overall,
        "tail_rms": tail_rms,
        "end_rms": end_rms,
        "tail_ratio": (tail_rms / overall) if overall > 0 else 0.0,
        "fade_ratio": (end_rms / tail_rms) if tail_rms > 0 else 0.0,
        "audio_seconds": float(samples.size / sr),
    }


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def run_export_qa(media_path: str | Path, *, expect: Any = None) -> dict[str, Any]:
    """Run the unified export QA gate on ``media_path``.

    ``expect`` (dict or object, all keys optional):

    * ``aspect`` — e.g. ``"9:16"`` / ``"16:9"``;
    * ``fps`` — expected frame rate (compared within tolerance);
    * ``subtitles`` — True requires an embedded subtitle stream or a
      same-stem ``.srt`` sidecar;
    * ``max_black_ratio`` / ``lufs_target`` / ``lufs_tolerance`` /
      ``true_peak_ceiling`` / ``av_sync_tolerance_s`` — threshold
      overrides (defaults are the earshot_gate / zerolines ones).

    Raises ``FileNotFoundError`` for a missing file.  An un-probeable
    file yields a ``fail`` report instead of an exception so batch
    pipelines can record the verdict.
    """
    media = Path(media_path)
    if not media.is_file():
        raise FileNotFoundError(f"export_qa: media file not found: {media}")

    expect_aspect = _expect_get(expect, "aspect")
    expect_fps = _expect_get(expect, "fps")
    expect_subtitles = bool(_expect_get(expect, "subtitles", False))
    max_black_ratio = float(_expect_get(expect, "max_black_ratio", MAX_BLACK_RATIO))
    lufs_target = float(_expect_get(expect, "lufs_target", LUFS_TARGET))
    lufs_tolerance = float(_expect_get(expect, "lufs_tolerance", LUFS_TOLERANCE))
    peak_ceiling = float(_expect_get(expect, "true_peak_ceiling", TRUE_PEAK_CEILING_DBTP))
    av_tol = float(_expect_get(expect, "av_sync_tolerance_s", AV_SYNC_TOLERANCE_S))

    checks: list[dict[str, Any]] = []
    measurements: dict[str, Any] = {}

    probe = _probe(media)
    if probe is None:
        checks.append(
            _check(
                "container_codec",
                "fail",
                "ffprobe could not parse the file (not a readable media file)",
            )
        )
        for name in (
            "resolution_aspect",
            "fps",
            "black_frames",
            "loudness",
            "av_sync",
            "ending_audio",
            "last_frame_black",
            "subtitles",
        ):
            status = "fail" if name == "subtitles" and expect_subtitles else "skip"
            checks.append(_check(name, status, "skipped: media unprobeable"))
        return _report(media, expect, None, measurements, checks)

    streams = probe.get("streams") or []
    fmt = probe.get("format") or {}
    format_name = str(fmt.get("format_name") or "")
    try:
        format_duration = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        format_duration = 0.0
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    has_subtitle_stream = any(s.get("codec_type") == "subtitle" for s in streams)

    probe_summary = {
        "format_name": format_name,
        "duration_s": format_duration,
        "video": None
        if video is None
        else {
            "codec": video.get("codec_name"),
            "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0),
            "fps": _stream_fps(video),
            "duration_s": _stream_duration(video, format_duration),
        },
        "audio": None
        if audio is None
        else {
            "codec": audio.get("codec_name"),
            "duration_s": _stream_duration(audio, format_duration),
        },
        "has_subtitle_stream": has_subtitle_stream,
    }

    # --- a. container / codecs -------------------------------------------
    if video is None:
        checks.append(
            _check("container_codec", "fail", "no video stream in container")
        )
    else:
        format_tokens = {t.strip() for t in format_name.split(",") if t.strip()}
        problems: list[str] = []
        if not ({"mp4", "mov"} & format_tokens):
            problems.append(f"format_name {format_name!r} is not mov/mp4")
        if video.get("codec_name") != "h264":
            problems.append(f"video codec {video.get('codec_name')!r} != h264")
        if audio is not None and audio.get("codec_name") != "aac":
            problems.append(f"audio codec {audio.get('codec_name')!r} != aac")
        if problems:
            checks.append(
                _check(
                    "container_codec",
                    "fail",
                    "; ".join(problems),
                    value={
                        "format_name": format_name,
                        "video_codec": video.get("codec_name"),
                        "audio_codec": None if audio is None else audio.get("codec_name"),
                    },
                    threshold="format mov/mp4, video h264, audio aac",
                )
            )
        elif audio is None:
            checks.append(
                _check(
                    "container_codec",
                    "warn",
                    "container/codecs OK but there is NO audio track "
                    "(annotated per spec; silent exports must be intentional)",
                    value={"format_name": format_name, "video_codec": "h264"},
                    threshold="format mov/mp4, video h264, audio aac",
                )
            )
        else:
            checks.append(
                _check(
                    "container_codec",
                    "pass",
                    f"format {format_name}, video h264, audio aac",
                    value={
                        "format_name": format_name,
                        "video_codec": "h264",
                        "audio_codec": "aac",
                    },
                    threshold="format mov/mp4, video h264, audio aac",
                )
            )

    # --- b. resolution / aspect ------------------------------------------
    width = int(video.get("width") or 0) if video else 0
    height = int(video.get("height") or 0) if video else 0
    if video is None or width <= 0 or height <= 0:
        checks.append(
            _check("resolution_aspect", "fail", "no usable video dimensions")
        )
    elif expect_aspect:
        if _aspect_matches(width, height, str(expect_aspect)):
            checks.append(
                _check(
                    "resolution_aspect",
                    "pass",
                    f"{width}x{height} ({_orientation(width, height)}) "
                    f"matches expect {expect_aspect}",
                    value={"width": width, "height": height},
                    threshold=f"aspect {expect_aspect}",
                )
            )
        else:
            checks.append(
                _check(
                    "resolution_aspect",
                    "fail",
                    f"{width}x{height} ({_orientation(width, height)}) "
                    f"does not match expect {expect_aspect}",
                    value={"width": width, "height": height},
                    threshold=f"aspect {expect_aspect}",
                )
            )
    else:
        checks.append(
            _check(
                "resolution_aspect",
                "pass",
                f"{width}x{height} ({_orientation(width, height)}); "
                "no expected aspect given",
                value={"width": width, "height": height},
            )
        )

    # --- c. fps ------------------------------------------------------------
    fps = _stream_fps(video) if video else 0.0
    measurements["fps"] = fps
    if expect_fps is None:
        checks.append(_check("fps", "skip", "no expected fps given", value=fps))
    elif fps <= 0:
        checks.append(
            _check("fps", "fail", "could not determine frame rate", value=fps,
                   threshold=f"{expect_fps} fps")
        )
    elif abs(fps - float(expect_fps)) <= max(FPS_TOLERANCE, 0.02 * float(expect_fps)):
        checks.append(
            _check("fps", "pass", f"{fps:.3f} fps within tolerance of {expect_fps}",
                   value=fps, threshold=f"{expect_fps} fps ± tol")
        )
    else:
        checks.append(
            _check("fps", "fail", f"{fps:.3f} fps != expected {expect_fps}",
                   value=fps, threshold=f"{expect_fps} fps ± tol")
        )

    # --- d. black frames (zerolines frame_stats口径) ------------------------
    if video is None:
        checks.append(_check("black_frames", "skip", "no video stream"))
    else:
        frames = _sample_frame_lumas(media, width, height)
        if frames is None:
            checks.append(
                _check(
                    "black_frames",
                    "warn",
                    "could not decode sampled frames to measure black ratio "
                    "(not treated as pass)",
                    threshold=f"black_ratio <= {max_black_ratio}",
                )
            )
        else:
            from hevi.layer4_legacy.zerolines.oskill_impl.qa import frame_stats

            stats = frame_stats(frames)
            black_ratio = float(stats["black_ratio"])
            measurements["black_ratio"] = black_ratio
            measurements["frames_sampled"] = int(stats["frames_sampled"])
            status = "pass" if black_ratio <= max_black_ratio else "fail"
            checks.append(
                _check(
                    "black_frames",
                    status,
                    f"black-frame ratio {black_ratio:.3f} "
                    f"(frame mean luma < {BLACK_LUMA:g}, zerolines frame_stats; "
                    f"{int(stats['frames_sampled'])} frames sampled)",
                    value=black_ratio,
                    threshold=f"<= {max_black_ratio}",
                )
            )

    # --- e. loudness / peak / clipping (earshot measure, earshot_gate阈值) --
    if audio is None:
        checks.append(
            _check("loudness", "skip", "no audio track to measure")
        )
    else:
        try:
            from hevi.audio import earshot_client

            m = earshot_client.measure(media)
            measurements["earshot"] = m
            lufs = m.get("lufs")
            true_peak = m.get("true_peak_dbtp")
            clipped = m.get("clipped_samples")
            peak_dbfs = m.get("peak_dbfs")
            problems = []
            if true_peak is None or true_peak > peak_ceiling:
                problems.append(f"true peak {true_peak} > {peak_ceiling} dBTP")
            if lufs is None:
                problems.append("no integrated loudness measured (silence/too short)")
            elif abs(lufs - lufs_target) > lufs_tolerance:
                problems.append(
                    f"LUFS {lufs} outside {lufs_target} ± {lufs_tolerance}"
                )
            if clipped is not None:
                if clipped != 0:
                    problems.append(f"{clipped} clipped samples")
            elif peak_dbfs is None or peak_dbfs > -0.3:
                problems.append(f"sample peak {peak_dbfs} dBFS risks clipping")
            if problems:
                checks.append(
                    _check(
                        "loudness",
                        "fail",
                        "; ".join(problems),
                        value={
                            "lufs": lufs,
                            "true_peak_dbtp": true_peak,
                            "clipped_samples": clipped,
                            "peak_dbfs": peak_dbfs,
                        },
                        threshold=(
                            f"peak <= {peak_ceiling} dBTP, LUFS "
                            f"{lufs_target} ± {lufs_tolerance}, clipped == 0 "
                            "(earshot_gate thresholds)"
                        ),
                    )
                )
            else:
                checks.append(
                    _check(
                        "loudness",
                        "pass",
                        f"LUFS {lufs}, true peak {true_peak} dBTP, "
                        f"clipped {clipped} (earshot measure)",
                        value={
                            "lufs": lufs,
                            "true_peak_dbtp": true_peak,
                            "clipped_samples": clipped,
                            "peak_dbfs": peak_dbfs,
                        },
                        threshold=(
                            f"peak <= {peak_ceiling} dBTP, LUFS "
                            f"{lufs_target} ± {lufs_tolerance}, clipped == 0"
                        ),
                    )
                )
        except Exception as exc:  # earshot missing/failed: never silent-pass
            checks.append(
                _check(
                    "loudness",
                    "fail",
                    f"earshot measure unavailable/failed: "
                    f"{type(exc).__name__}: {exc}",
                    threshold=(
                        f"peak <= {peak_ceiling} dBTP, LUFS "
                        f"{lufs_target} ± {lufs_tolerance}, clipped == 0"
                    ),
                )
            )

    # --- f1. A/V duration sync ---------------------------------------------
    if video is None or audio is None:
        checks.append(
            _check("av_sync", "skip", "needs both audio and video streams")
        )
    else:
        v_dur = _stream_duration(video, format_duration)
        a_dur = _stream_duration(audio, format_duration)
        diff = abs(v_dur - a_dur)
        measurements["av_duration_diff_s"] = diff
        checks.append(
            _check(
                "av_sync",
                "pass" if diff <= av_tol else "fail",
                f"video {v_dur:.3f}s vs audio {a_dur:.3f}s, diff {diff:.3f}s",
                value=diff,
                threshold=f"<= {av_tol} s",
            )
        )

    # --- f2. ending audio (abrupt cut = warn only) ---------------------------
    if audio is None:
        checks.append(_check("ending_audio", "skip", "no audio track"))
    else:
        profile = _audio_rms_profile(media)
        if profile is None:
            checks.append(
                _check(
                    "ending_audio",
                    "warn",
                    "could not decode audio to verify the ending "
                    "(not treated as pass)",
                )
            )
        else:
            measurements["ending"] = profile
            if profile["overall_rms"] <= 1e-5:
                checks.append(
                    _check(
                        "ending_audio",
                        "pass",
                        "programme audio is (near-)silent; no abrupt ending",
                        value=profile,
                    )
                )
            elif (
                profile["tail_ratio"] > TAIL_RATIO_WARN
                and profile["fade_ratio"] > TAIL_FADE_RATIO
            ):
                checks.append(
                    _check(
                        "ending_audio",
                        "warn",
                        f"possible abrupt ending: last {TAIL_WINDOW_S}s RMS "
                        f"is {profile['tail_ratio']:.2f}x the programme RMS "
                        f"and the final {TAIL_END_S}s shows no fade "
                        f"(fade ratio {profile['fade_ratio']:.2f}); "
                        "listen to the ending — warn only, by design",
                        value=profile,
                        threshold=(
                            f"tail_ratio <= {TAIL_RATIO_WARN} or "
                            f"fade_ratio <= {TAIL_FADE_RATIO}"
                        ),
                    )
                )
            else:
                checks.append(
                    _check(
                        "ending_audio",
                        "pass",
                        f"ending decays or is quiet (tail ratio "
                        f"{profile['tail_ratio']:.2f}, fade ratio "
                        f"{profile['fade_ratio']:.2f})",
                        value=profile,
                        threshold=(
                            f"tail_ratio <= {TAIL_RATIO_WARN} or "
                            f"fade_ratio <= {TAIL_FADE_RATIO}"
                        ),
                    )
                )

    # --- f3. last frame black (warn only) ------------------------------------
    if video is None:
        checks.append(_check("last_frame_black", "skip", "no video stream"))
    else:
        luma = _last_frame_luma(media)
        if luma is None:
            checks.append(
                _check(
                    "last_frame_black",
                    "warn",
                    "could not extract the final frame (not treated as pass)",
                )
            )
        elif luma < BLACK_LUMA:
            checks.append(
                _check(
                    "last_frame_black",
                    "warn",
                    f"final frame is black (mean luma {luma:.1f} < "
                    f"{BLACK_LUMA:g}); fine for fade-out/credits, "
                    "suspicious otherwise — warn only",
                    value=luma,
                    threshold=f"luma >= {BLACK_LUMA:g}",
                )
            )
        else:
            checks.append(
                _check(
                    "last_frame_black",
                    "pass",
                    f"final frame mean luma {luma:.1f}",
                    value=luma,
                    threshold=f"luma >= {BLACK_LUMA:g}",
                )
            )

    # --- g. subtitles (optional) ---------------------------------------------
    if not expect_subtitles:
        checks.append(
            _check("subtitles", "skip", "subtitles not required by expect")
        )
    else:
        sidecar = media.with_suffix(".srt")
        sidecar_ok = sidecar.is_file() and sidecar.stat().st_size > 0
        # Also accept a sidecar that keeps the full stem (movie.mp4 -> movie.srt
        # is with_suffix; double extensions collapse the same way).
        if has_subtitle_stream or sidecar_ok:
            where = "embedded stream" if has_subtitle_stream else str(sidecar)
            checks.append(
                _check("subtitles", "pass", f"subtitles found: {where}")
            )
        else:
            checks.append(
                _check(
                    "subtitles",
                    "fail",
                    f"subtitles required but no embedded stream and no "
                    f"sidecar at {sidecar}",
                )
            )

    return _report(media, expect, probe_summary, measurements, checks)


def _report(
    media: Path,
    expect: Any,
    probe_summary: dict[str, Any] | None,
    measurements: dict[str, Any],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    verdict = _overall(checks)
    expect_dict: dict[str, Any] = {}
    if isinstance(expect, dict):
        expect_dict = dict(expect)
    elif expect is not None:
        expect_dict = {
            k: _expect_get(expect, k)
            for k in ("aspect", "fps", "subtitles")
            if _expect_get(expect, k) is not None
        }
    return {
        "media_path": str(media),
        "tool": (
            "export_qa (ffprobe + zerolines frame_stats black frames + "
            "earshot measure loudness)"
        ),
        "expect": expect_dict,
        "probe": probe_summary,
        "measurements": measurements,
        "checks": checks,
        "verdict": verdict,
        "pass": verdict != "fail",
        "failed_checks": [c["name"] for c in checks if c["status"] == "fail"],
        "warned_checks": [c["name"] for c in checks if c["status"] == "warn"],
    }


__all__ = [
    "AV_SYNC_TOLERANCE_S",
    "BLACK_LUMA",
    "LUFS_TARGET",
    "LUFS_TOLERANCE",
    "MAX_BLACK_RATIO",
    "TRUE_PEAK_CEILING_DBTP",
    "run_export_qa",
]
