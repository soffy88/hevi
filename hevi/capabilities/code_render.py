"""Deterministic code-render pipeline (``video.code_render``).

This is the missing execution half of ``story.canvas_workflow``:
that capability only registers a DAG model and never executes
anything. This module does the part a code-rendered video actually
needs, in the pdoom-video sense (every frame is a deterministic
function of time, so a re-render of the same inputs is identical):

* Resolution / frame-rate tiers, with 4K60 as the declared target
  tier and cheaper tiers for drafts. A tier is a contract, not a
  wish: width/height/fps are validated before any frame is drawn.
* Deterministic frame capture: ``render_frames`` calls a pure
  ``frame_fn(t_seconds, frame_index, width, height) -> PIL.Image``
  once per frame index. Same inputs must yield identical frame
  SHA-256s; the manifest records one hash per frame so a later run
  can prove it.
* Failed-frame re-render: a frame that raises is retried up to
  ``max_retries`` times; a frame that still fails aborts the whole
  render with the failing indices listed -- it is never replaced by
  a blank or a copy of a neighbour, which would silently break the
  time function.
* ffmpeg assembly: frames + optional audio -> mp4 (libx264,
  yuv420p), verified afterwards with ffprobe (duration within
  0.25s of the frame span, non-empty file). Missing ffmpeg or a
  failed encode raises.

What this module does NOT do: it does not drive a browser. The
headless-Chromium capture path already exists in hevi's
creator-style-kit styled render; this module is the deterministic
PIL/direct path (karaoke typography, HUDs, plates), which needs no
browser and no GPU. A browser scene spec is out of scope here and
is listed as a residual, not faked by relabelling PIL frames.

Failure contract: unknown tier, non-positive fps/duration, a frame
function returning the wrong size or mode, a persistently failing
frame, a missing ffmpeg/ffprobe, or an encode whose ffprobe duration
disagrees with the frame span all raise CapabilityError.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

TIERS: dict[str, dict[str, Any]] = {
    "draft_720p30": {"width": 1280, "height": 720, "fps": 30, "note": "draft only"},
    "hd_1080p30": {"width": 1920, "height": 1080, "fps": 30, "note": "default"},
    "hd_1080p60": {"width": 1920, "height": 1080, "fps": 60, "note": "pdoom default"},
    "uhd_2160p30": {"width": 3840, "height": 2160, "fps": 30, "note": "4K draft tier"},
    "uhd_2160p60": {"width": 3840, "height": 2160, "fps": 60, "note": "target tier: true 4K, not an upscale"},
}


def get_tier(name: str) -> dict[str, Any]:
    if name not in TIERS:
        raise CapabilityError(
            f"video.code_render: unknown tier {name!r}; known: {sorted(TIERS)}"
        )
    return dict(TIERS[name])


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise CapabilityError(f"video.code_render: required tool missing from PATH: {name}")
    return path


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_frames(
    frame_fn: Callable[[float, int, int, int], Any],
    tier: str,
    duration_sec: float,
    out_dir: Path,
    max_retries: int = 3,
) -> dict[str, Any]:
    if not callable(frame_fn):
        raise CapabilityError("video.code_render: frame_fn must be callable")
    spec = get_tier(tier)
    if not isinstance(duration_sec, (int, float)) or duration_sec <= 0:
        raise CapabilityError("video.code_render: duration_sec must be > 0")
    if not isinstance(max_retries, int) or max_retries < 0:
        raise CapabilityError("video.code_render: max_retries must be a non-negative integer")
    width, height, fps = spec["width"], spec["height"], spec["fps"]
    count = max(1, round(duration_sec * fps))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    retried: list[int] = []
    for i in range(count):
        t = i / fps
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                img = frame_fn(t, i, width, height)
                break
            except Exception as exc:  # noqa: BLE001 - retried, then reported
                last_exc = exc
                if attempt == max_retries:
                    raise CapabilityError(
                        f"video.code_render: frame {i} (t={t:.3f}s) failed after "
                        f"{max_retries} retries: {exc}"
                    ) from exc
                retried.append(i)
        else:  # pragma: no cover - loop always breaks or raises
            raise CapabilityError("video.code_render: unreachable frame loop state")
        if img.size != (width, height):
            raise CapabilityError(
                f"video.code_render: frame {i} size {img.size} != tier size {(width, height)}"
            )
        if img.mode != "RGB":
            img = img.convert("RGB")
        path = out_dir / f"frame_{i:06d}.png"
        img.save(path)
        frames.append({"index": i, "t_sec": round(t, 4), "file": path.name, "sha256": _sha256_file(path)})
    manifest = {
        "capability": "video.code_render", "tier": tier, "width": width,
        "height": height, "fps": fps, "duration_sec": duration_sec,
        "frame_count": count, "retried_frames": sorted(set(retried)),
        "frames": frames,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def assemble_mp4(
    frames_dir: Path,
    fps: int,
    out_path: Path,
    audio_path: Path | None = None,
) -> dict[str, Any]:
    ffmpeg = _require_tool("ffmpeg")
    ffprobe = _require_tool("ffprobe")
    frames_dir = Path(frames_dir)
    pattern = frames_dir / "frame_%06d.png"
    if not list(frames_dir.glob("frame_*.png")):
        raise CapabilityError(f"video.code_render: no frames in {frames_dir}")
    if not isinstance(fps, int) or fps <= 0:
        raise CapabilityError("video.code_render: fps must be a positive integer")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-framerate", str(fps), "-i", str(pattern)]
    if audio_path is not None:
        if not Path(audio_path).exists():
            raise CapabilityError(f"video.code_render: audio file missing: {audio_path}")
        cmd += ["-i", str(audio_path), "-map", "0:v", "-map", "1:a",
                "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        raise CapabilityError(
            f"video.code_render: ffmpeg failed: {(proc.stderr or '')[-500:]}"
        )
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(out_path)],
        capture_output=True, text=True)
    try:
        actual = float((probe.stdout or "").strip())
    except ValueError as exc:
        raise CapabilityError("video.code_render: ffprobe could not read output mp4") from exc
    frame_count = len(list(frames_dir.glob("frame_*.png")))
    expected = frame_count / fps
    if abs(actual - expected) > 0.25:
        raise CapabilityError(
            f"video.code_render: ffprobe duration {actual}s != frame span {expected}s"
        )
    return {"mp4": str(out_path), "duration_sec": actual,
            "bytes": out_path.stat().st_size, "frame_count": frame_count, "fps": fps}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    # Report-only entry point: validates a tier and, when a frames dir
    # is supplied, assembles + verifies it. Frame generation itself is
    # done by direct callers (e.g. edit.karaoke_render) through
    # render_frames, because a JSON capability cannot carry a frame
    # function -- pretending otherwise would be a fake render.
    tier = params.get("tier", "hd_1080p30")
    spec = get_tier(tier)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"capability": "video.code_render", "tier": tier, **spec}
    frames_dir = params.get("frames_dir")
    if frames_dir is not None:
        result["assembly"] = assemble_mp4(
            Path(frames_dir), spec["fps"], out_dir / "code_render.mp4",
            Path(params["audio_path"]) if params.get("audio_path") else None)
        result["mp4"] = result["assembly"]["mp4"]
    report = out_dir / "code_render.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "tier": tier},
    )


def register_code_render_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="video.code_render",
        kind="video",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {
                "tier": {"type": "string"},
                "frames_dir": {"type": "string"},
                "audio_path": {"type": "string"},
            },
            "additionalProperties": False,
        },
        cpu_cost_hint=1.0,
        render=_render,
        description=(
            "Deterministic code-render pipeline: resolution/fps tiers "
            "(draft 720p30 up to target 4K60), pure frame(t) capture with "
            "per-frame SHA-256 manifest and failed-frame re-render, and "
            "ffmpeg assembly verified by ffprobe. Frame generation is via "
            "direct render_frames calls (e.g. edit.karaoke_render); the "
            "JSON entry point assembles a supplied frames dir."
        ),
        line="video",
    ))
    return ["video.code_render"]


register_code_render_capabilities_once()
