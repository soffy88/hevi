"""Single-image sway engine (``video.single_image_sway``).

Clean-room rewrite of the single-image sway *idea* in
``hevi-vs-oyasumi-gamedev.md`` item 7 (from the oyasumi-gamedev.com
tool pages, restated in the report's own words): a still picture
plus colour zones plus per-zone motion parameters makes a light
pseudo-Live2D -- hair, flags, flames and the like sway without
any bone rigging. Only the idea is taken here. The source tool's
internal construction, its parameters, and its shape-generation
logic were never inspected and are not reproduced: every motion
number in this module is caller-given, and the sway vocabulary
itself is caller-supplied (a mapping from caller-named kinds to
one of three generic waveforms). No site number is a default.

How it works: the caller paints zones by colour (a colour plus a
tolerance) and gives each zone a sway kind, an amplitude in
pixels, a speed in hertz, an axis, and a phase. Each output
frame displaces that zone's pixels by a sinusoid (or triangle /
square wave) along the axis. Pixels outside every zone are
byte-identical in every frame, so zones never bleed into each
other; overlapping zones resolve in declaration order, later
zones winning. Rendering is pure NumPy with no randomness: two
runs of the same plan produce byte-identical frames.

This module renders locally with Pillow/NumPy/ffmpeg only. It
never calls a model, never touches a key or a budget, and never
reads the source tool.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

WAVEFORMS = ("sine", "triangle", "square")
AXES = ("horizontal", "vertical")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"video.single_image_sway: {detail}"}
    issue.update(extra)
    return issue


def _wave(waveform: str, phase_angle: float) -> float:
    if waveform == "sine":
        return math.sin(phase_angle)
    if waveform == "triangle":
        frac = phase_angle / (2.0 * math.pi) - math.floor(phase_angle / (2.0 * math.pi) + 0.5)
        return 2.0 * abs(2.0 * frac) - 1.0
    if waveform == "square":
        return 1.0 if math.sin(phase_angle) >= 0 else -1.0
    raise CapabilityError(f"video.single_image_sway: unknown waveform {waveform!r}")


def _resolve_zones(plan: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate the caller plan. Returns (zones, issues)."""
    issues: list[dict[str, Any]] = []
    zones: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return zones, [_issue("plan_not_object", "sway plan must be an object")]
    kinds = plan.get("sway_kinds")
    if not isinstance(kinds, dict) or not kinds:
        return zones, [
            _issue(
                "sway_kinds_missing",
                "plan must declare a caller sway vocabulary: sway_kinds "
                "mapping kind names to {waveform, axis}",
            )
        ]
    for kind_name, spec in kinds.items():
        if not isinstance(spec, dict) or spec.get("waveform") not in WAVEFORMS:
            issues.append(
                _issue(
                    "sway_kind_invalid",
                    f"sway kind {kind_name!r} must declare waveform "
                    f"sine/triangle/square, got {spec!r}",
                )
            )
        if isinstance(spec, dict) and spec.get("axis") not in AXES and spec.get("axis") is not None:
            issues.append(
                _issue(
                    "sway_kind_axis_invalid",
                    f"sway kind {kind_name!r} axis must be horizontal/vertical",
                )
            )
    raw_zones = plan.get("zones")
    if not isinstance(raw_zones, list) or not raw_zones:
        issues.append(_issue("zones_missing", "plan must list at least one colour zone"))
        return zones, issues
    for index, zone in enumerate(raw_zones):
        where = f"zone {index}"
        if not isinstance(zone, dict):
            issues.append(_issue("zone_not_object", f"{where} must be an object"))
            continue
        kind_name = zone.get("sway_kind")
        spec = kinds.get(kind_name) if isinstance(kind_name, str) else None
        if spec is None:
            issues.append(
                _issue(
                    "sway_kind_unknown",
                    f"{where} sway_kind {kind_name!r} is not in the "
                    "caller-declared sway_kinds vocabulary",
                )
            )
            continue
        color = zone.get("color")
        if (
            not isinstance(color, list)
            or len(color) != 3
            or any(not isinstance(c, int) or c < 0 or c > 255 for c in color)
        ):
            issues.append(
                _issue("zone_color_invalid", f"{where} color must be [R, G, B] 0-255")
            )
            continue
        amplitude = zone.get("amplitude_px", 0)
        speed = zone.get("speed_hz", 0)
        if not isinstance(amplitude, (int, float)) or isinstance(amplitude, bool) or amplitude < 0:
            issues.append(_issue("amplitude_invalid", f"{where} amplitude_px must be >= 0"))
            continue
        if not isinstance(speed, (int, float)) or isinstance(speed, bool) or speed < 0:
            issues.append(_issue("speed_invalid", f"{where} speed_hz must be >= 0"))
            continue
        axis = zone.get("axis", spec.get("axis", "horizontal"))
        if axis not in AXES:
            issues.append(_issue("zone_axis_invalid", f"{where} axis must be horizontal/vertical"))
            continue
        zones.append(
            {
                "name": zone.get("name", f"zone_{index}"),
                "color": tuple(color),
                "tolerance": zone.get("tolerance", 0),
                "waveform": spec["waveform"],
                "axis": axis,
                "amplitude_px": float(amplitude),
                "speed_hz": float(speed),
                "phase": float(zone.get("phase", 0.0)),
            }
        )
    return zones, issues


def _zone_mask(base: np.ndarray, color: tuple[int, int, int], tolerance: Any) -> np.ndarray:
    tol = tolerance if isinstance(tolerance, (int, float)) and tolerance >= 0 else 0
    diff = np.abs(base.astype(np.int16) - np.array(color, dtype=np.int16))
    return np.all(diff <= tol, axis=2)


def _shift_layer(layer: np.ndarray, mask: np.ndarray, offset: int, axis: str) -> tuple[np.ndarray, np.ndarray]:
    """Shift a masked layer by an integer offset, clipping wrap-around."""
    if offset == 0:
        return layer, mask
    if axis == "horizontal":
        shifted = np.roll(layer, offset, axis=1)
        shifted_mask = np.roll(mask, offset, axis=1)
        if offset > 0:
            shifted[:, :offset] = 0
            shifted_mask[:, :offset] = False
        else:
            shifted[:, offset:] = 0
            shifted_mask[:, offset:] = False
    else:
        shifted = np.roll(layer, offset, axis=0)
        shifted_mask = np.roll(mask, offset, axis=0)
        if offset > 0:
            shifted[:offset, :] = 0
            shifted_mask[:offset, :] = False
        else:
            shifted[offset:, :] = 0
            shifted_mask[offset:, :] = False
    return shifted, shifted_mask


def render_sway_frames(
    base: np.ndarray, zones: list[dict[str, Any]], frames: int, fps: float
) -> list[np.ndarray]:
    """Render ``frames`` swayed frames from a base RGB array."""
    masks = [_zone_mask(base, z["color"], z["tolerance"]) for z in zones]
    out_frames: list[np.ndarray] = []
    for frame_index in range(frames):
        t = frame_index / fps if fps else 0.0
        canvas = base.copy()
        for zone, mask in zip(zones, masks):
            offset = int(
                round(
                    zone["amplitude_px"]
                    * _wave(zone["waveform"], 2.0 * math.pi * zone["speed_hz"] * t + zone["phase"])
                )
            )
            layer = np.zeros_like(base)
            layer[mask] = base[mask]
            shifted, shifted_mask = _shift_layer(layer, mask, offset, zone["axis"])
            canvas[shifted_mask] = shifted[shifted_mask]
        out_frames.append(canvas)
    return out_frames


def make_synthetic_base(spec: Any) -> np.ndarray:
    """Build a small synthetic test picture from caller shapes.

    ``spec``: {width, height, background: [R,G,B], shapes: [{kind:
    rect/circle, color, box: [x0,y0,x1,y1] or center/radius}]}.
    Used for evidence only; never presented as a real picture.
    """
    if not isinstance(spec, dict):
        raise CapabilityError("video.single_image_sway: synthetic spec must be an object")
    width = spec.get("width", 160)
    height = spec.get("height", 120)
    background = spec.get("background", [255, 255, 255])
    image = Image.new("RGB", (width, height), tuple(background))
    draw = ImageDraw.Draw(image)
    for shape in spec.get("shapes", []):
        color = tuple(shape.get("color", [0, 0, 0]))
        if shape.get("kind") == "rect":
            draw.rectangle(shape["box"], fill=color)
        elif shape.get("kind") == "circle":
            cx, cy, radius = shape["center"][0], shape["center"][1], shape["radius"]
            draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color)
    return np.array(image)


def load_base(params: dict[str, Any]) -> np.ndarray:
    """Load the source picture: a file path, or a synthetic spec."""
    source = params.get("source_image")
    if source:
        path = Path(source)
        if not path.exists():
            raise CapabilityError(f"video.single_image_sway: source image not found: {path}")
        return np.array(Image.open(path).convert("RGB"))
    if params.get("synthetic") is not None:
        return make_synthetic_base(params["synthetic"])
    raise CapabilityError(
        "video.single_image_sway: params need source_image or synthetic"
    )


def render_single_image_sway(
    params: dict[str, Any], out_dir: Path
) -> dict[str, Any]:
    """Render a sway plan to frames + mp4 + report. Returns the report."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    zones, issues = _resolve_zones(params)
    frames = params.get("frames", 12)
    fps = params.get("fps", 6)
    if not isinstance(frames, int) or frames < 2:
        issues.append(_issue("frames_invalid", "frames must be an integer >= 2"))
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or fps <= 0:
        issues.append(_issue("fps_invalid", "fps must be a positive number"))
    if issues:
        return {"ok": False, "verdict": "fail", "issues": issues}
    base = load_base(params)
    rendered = render_sway_frames(base, zones, frames, float(fps))
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    frame_records: list[dict[str, Any]] = []
    for index, frame in enumerate(rendered):
        path = frames_dir / f"frame_{index:06d}.png"
        Image.fromarray(frame).save(path)
        frame_records.append(
            {"frame": index, "file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    video_path = out_dir / "sway.mp4"
    command = [
        "ffmpeg", "-y", "-v", "error",
        "-framerate", str(fps), "-i", str(frames_dir / "frame_%06d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode != 0 or not video_path.exists():
        raise CapabilityError(
            f"video.single_image_sway: ffmpeg assembly failed: {result.stderr.strip()}"
        )
    report = {
        "ok": True,
        "verdict": "pass",
        "issues": [],
        "frames": frames,
        "fps": fps,
        "size": [int(base.shape[1]), int(base.shape[0])],
        "zones": [
            {
                "name": z["name"],
                "color": list(z["color"]),
                "waveform": z["waveform"],
                "axis": z["axis"],
                "amplitude_px": z["amplitude_px"],
                "speed_hz": z["speed_hz"],
                "phase": z["phase"],
            }
            for z in zones
        ],
        "frame_records": frame_records,
        "video": video_path.name,
        "video_sha256": compute_sha256(video_path),
        "synthetic": params.get("synthetic") is not None,
    }
    (out_dir / "single_image_sway.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = render_single_image_sway(params, Path(out_dir))
    report_path = Path(out_dir) / "single_image_sway.json"
    return CapabilityResult(
        duration_s=float(params.get("frames", 12)) / float(params.get("fps", 6)),
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_single_image_sway_capabilities_once() -> list[str]:
    """Register ``video.single_image_sway`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.single_image_sway",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "source_image": {"type": "string"},
                    "synthetic": {"type": "object"},
                    "zones": {"type": "array"},
                    "sway_kinds": {"type": "object"},
                    "frames": {"type": "integer"},
                    "fps": {"type": "number"},
                },
                "additionalProperties": True,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=True,
            description=(
                "Single-image sway: colour zones of a still picture "
                "displaced per frame by caller-given amplitude/speed/"
                "axis/phase over a caller-declared sway vocabulary of "
                "generic waveforms. Zones never bleed; rendering is "
                "deterministic. Local Pillow/NumPy/ffmpeg only."
            ),
            line="video",
        )
    )
    return ["video.single_image_sway"]


register_single_image_sway_capabilities_once()
