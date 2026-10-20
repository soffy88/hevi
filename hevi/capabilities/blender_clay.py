"""Blender clay-style 3D render capability (headless bpy, Cycles CPU).

Registers ``video.blender_clay_render`` so every product line can call
Blender by name (CAPABILITY_CONTRACT.md).  The engine layer (binary
discovery, pure keyframe/resolution maths, deterministic bpy-script
generation) lives in ``hevi/video/blender_clay.py``; this module only
orchestrates: validate -> generate script -> ``blender --background
--python`` -> frame sequence -> ffmpeg -> mp4 + timing sidecar.

Missing Blender, a non-zero Blender exit, a missing/truncated frame
sequence, or a missing ffmpeg all raise ``CapabilityError`` - never a fake
success.  Zero paid calls: everything is local.

Measured cost on ubuntu26 (2026-10-20, 20 CPU cores, no GPU), Blender
4.2.17 LTS, Cycles CPU, 32 samples + OpenImageDenoise, 480p in 9:16
(480x854), ball_character/bounce: 188.4s wall for 60 frames = 3.14s/frame
wall, i.e. ~75s wall per 1 second of 24fps video; the 2.5s sample clip
took ~3.1 minutes end to end for the Blender step.  Keep shots short.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)
from hevi.video import blender_clay as clay

_Registered = False

_DESCRIPTION = (
    "Blender clay-style 3D render (headless bpy script, Cycles CPU, no GPU): "
    "matte clay scene (Principled BSDF roughness 0.9, metallic 0, soft pastel "
    "palette, large area light) - a rounded ball character or stacked clay "
    "blocks, animated with first/last-frame keyframes (bounce or slide+turn). "
    "CPU SLOW - measured on ubuntu26 (20 cores, Blender 4.2.17, 32 samples + "
    "OIDN denoise, 480p 9:16 = 480x854): 188s wall for 60 frames = 3.1s/frame, "
    "~75s wall per 1s of 24fps video, so a 2-3s shot takes ~3 minutes. "
    "Recommended: 480p (540p max), duration <=3s per shot, hard limit 6s, "
    "samples 32 (64 max in schema is ~2x slower). No GPU is used or required. "
    "Needs a local Blender binary ($HEVI_BLENDER_BIN / $BLENDER_BIN / PATH / "
    "~/.local/blender/blender / ~/opt/blender/blender); missing binary raises "
    "CapabilityError. Local and free: no paid calls."
)

# Wall-clock seconds per second of output video at the measured settings
# (480p, 32 samples, 24fps): 188.4s / 2.5s = 75.4.
_CPU_COST_HINT = 75.0


def _blender_version(blender: str) -> str:
    try:
        proc = subprocess.run(
            [blender, "--version"], capture_output=True, text=True, timeout=30
        )
        first = (proc.stdout or "").strip().splitlines()
        return first[0].strip() if first else "unknown"
    except Exception:
        return "unknown"


def _render_blender_clay(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if aspect not in ("16:9", "9:16", "1:1"):
        raise CapabilityError(
            f"video.blender_clay_render: unsupported aspect {aspect!r} "
            "(supported: 16:9, 9:16, 1:1)"
        )
    if not (1.0 <= float(duration) <= 6.0):
        raise CapabilityError(
            "video.blender_clay_render: duration must be 1..6s (CPU render is "
            f"~75s wall per output second at 480p; keep shots <=3s), got {duration}"
        )

    blender = clay.find_blender()
    if blender is None:
        raise CapabilityError(
            "video.blender_clay_render: blender binary not found (checked "
            "$HEVI_BLENDER_BIN, $BLENDER_BIN, PATH, ~/.local/blender/blender, "
            "~/opt/blender/blender, /usr/bin/blender); install Blender or set "
            "HEVI_BLENDER_BIN to its path"
        )
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise CapabilityError(
            "video.blender_clay_render: ffmpeg not found on PATH (needed to "
            "assemble the rendered PNG frame sequence into mp4)"
        )

    fps = int(params.get("fps", 24))
    samples = int(params.get("samples", 32))
    effective_seed = int(params.get("seed", seed))
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    try:
        config = clay.build_config(
            preset=str(params.get("preset", "ball_character")),
            motion=str(params.get("motion", "bounce")),
            palette=str(params.get("palette", "warm")),
            resolution=str(params.get("resolution", "480p")),
            aspect=aspect,
            fps=fps,
            samples=samples,
            duration=float(duration),
            seed=effective_seed,
            frames_dir=str(frames_dir),
        )
    except CapabilityError:
        raise
    except Exception as exc:
        raise CapabilityError(f"video.blender_clay_render: bad config: {exc}") from exc

    script_path = out_dir / "blender_clay_scene.py"
    script_path.write_text(clay.build_bpy_script(config), encoding="utf-8")
    config_path = out_dir / "blender_clay_config.json"
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    version = _blender_version(blender)
    log_path = out_dir / "blender.log"
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [blender, "--background", "--python", str(script_path)],
            capture_output=True,
            text=True,
            timeout=3600,
        )
    except subprocess.TimeoutExpired as exc:
        raise CapabilityError(
            "video.blender_clay_render: blender timed out after 3600s"
        ) from exc
    wall_s = time.monotonic() - started
    log_path.write_text(
        (proc.stdout or "") + "\n--- STDERR ---\n" + (proc.stderr or ""),
        encoding="utf-8",
    )
    if proc.returncode != 0:
        tail = "\n".join(((proc.stdout or "") + (proc.stderr or "")).splitlines()[-20:])
        raise CapabilityError(
            f"video.blender_clay_render: blender exited {proc.returncode}; "
            f"see {log_path}; tail: {tail}"
        )

    total = int(config["total_frames"])
    frames = sorted(frames_dir.glob("frame_*.png"))
    if len(frames) != total:
        raise CapabilityError(
            f"video.blender_clay_render: expected {total} frames in {frames_dir}, "
            f"found {len(frames)} (see {log_path})"
        )
    if any(f.stat().st_size == 0 for f in frames):
        raise CapabilityError("video.blender_clay_render: empty frame file rendered")

    clip_path = out_dir / "clay.mp4"
    encode = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "frame_%04d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(clip_path),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if encode.returncode != 0 or not clip_path.is_file() or clip_path.stat().st_size == 0:
        raise CapabilityError(
            f"video.blender_clay_render: ffmpeg failed ({encode.returncode}): "
            f"{(encode.stderr or '')[-500:]}"
        )

    per_frame = wall_s / total if total else 0.0
    per_second = wall_s / float(duration) if duration else 0.0
    sidecar = {
        "blender": blender,
        "blender_version": version,
        "render_engine": "CYCLES",
        "device": "CPU",
        "params": dict(params),
        "duration_s": float(duration),
        "aspect": aspect,
        "seed": effective_seed,
        "width": config["width"],
        "height": config["height"],
        "fps": fps,
        "samples": samples,
        "total_frames": total,
        "blender_wall_s": round(wall_s, 3),
        "seconds_per_frame": round(per_frame, 3),
        "wall_seconds_per_output_second": round(per_second, 3),
        "script": str(script_path),
        "config": str(config_path),
        "log": str(log_path),
        "frames_dir": str(frames_dir),
        "cost_note": (
            "Local CPU render, $0. Measured baseline 2026-10-20 on ubuntu26: "
            "188.4s wall / 60 frames at 480p 9:16, 32 samples (~75s wall per "
            "1s of 24fps video)."
        ),
    }
    sidecar_path = out_dir / "blender_clay_sidecar.json"
    sidecar_path.write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    return CapabilityResult(
        mp4=str(clip_path),
        duration_s=float(duration),
        sha256=compute_sha256(clip_path),
        qa={
            "blender_version": version,
            "render_engine": "CYCLES/CPU",
            "total_frames": total,
            "width": config["width"],
            "height": config["height"],
            "fps": fps,
            "samples": samples,
            "blender_wall_s": round(wall_s, 3),
            "seconds_per_frame": round(per_frame, 3),
            "wall_seconds_per_output_second": round(per_second, 3),
            "sidecar_json": str(sidecar_path),
            "frames_dir": str(frames_dir),
            "note": sidecar["cost_note"],
        },
    )


def register_blender_clay_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True

    register(
        Capability(
            name="video.blender_clay_render",
            kind="shot",
            aspects=["9:16", "16:9", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "preset": {
                        "type": "string",
                        "enum": ["ball_character", "clay_blocks"],
                        "default": "ball_character",
                        "description": "Clay scene preset (hero subject)",
                    },
                    "motion": {
                        "type": "string",
                        "enum": ["bounce", "slide_turn"],
                        "default": "bounce",
                        "description": "Hero animation: bouncing hop, or glide across + turn",
                    },
                    "palette": {
                        "type": "string",
                        "enum": ["warm", "mint", "sky"],
                        "default": "warm",
                        "description": "Soft clay colour palette",
                    },
                    "resolution": {
                        "type": "string",
                        "enum": ["480p", "540p"],
                        "default": "480p",
                        "description": "480p recommended on CPU; 540p costs ~27% more per frame",
                    },
                    "fps": {
                        "type": "integer",
                        "minimum": 12,
                        "maximum": 30,
                        "default": 24,
                    },
                    "samples": {
                        "type": "integer",
                        "minimum": 16,
                        "maximum": 64,
                        "default": 32,
                        "description": "Cycles samples; 32 + OIDN denoise is the measured baseline",
                    },
                    "seed": {"type": "integer", "description": "Cycles seed (defaults to the render seed)"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=_CPU_COST_HINT,
            render=_render_blender_clay,
            description=_DESCRIPTION,
            line="blender_clay",
        )
    )
    return ["video.blender_clay_render"]
