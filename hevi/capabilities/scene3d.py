"""SCENE3D capability adapter: exposes the ``hevi/layer4_legacy/scene3d`` line
through the unified Hevi capability registry (``hevi.capabilities``).

Three named, product-line-agnostic capabilities are registered so any product
(zero, talkcraft, short-drama, artmotion, explainer, ShotSpec workbench) can
call them by name: ``scene3d.planet_orbit``, ``scene3d.fox_wheat``,
``scene3d.star_sea``.

Each capability renders a CPU-only, deterministic 3D "Little-Prince-style" shot
via Three.js + Playwright/SwiftShader and returns a :class:`CapabilityResult`.
A failed render raises :class:`CapabilityError` — never a fake success.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from hevi.capabilities import Capability, CapabilityError, CapabilityResult, contains, get, register
from hevi.layer4_legacy.scene3d.renderer import ffprobe, ffprobe_frames, sha256
from hevi.layer4_legacy.scene3d.schema import parse_scene, scene_to_dict

# Base scene presets (name -> example json file).  Every capability is a thin
# variation on one of these presets; ``params`` only overrides safe knobs.
# This file lives at hevi/capabilities/scene3d.py; the presets live under
# hevi/layer4_legacy/scene3d/examples.
_EXAMPLES_DIR = (
    Path(__file__).resolve().parents[1]
    / "layer4_legacy"
    / "scene3d"
    / "examples"
)

# Base scene presets (name -> example json file).  Every capability is a thin
# variation on one of these presets; ``params`` only overrides safe knobs.
_PRESETS: dict[str, str] = {
    "scene3d.planet_orbit": "little_planet_orbit.json",
    "scene3d.fox_wheat": "fox_in_wheat.json",
    "scene3d.star_sea": "through_star_sea.json",
}

_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "seed": {"type": "integer"},
        "resolution": {"type": "integer", "minimum": 64, "maximum": 4320},
        "fps": {"type": "integer", "minimum": 1, "maximum": 120},
        "wind_strength": {"type": "number", "minimum": 0.0, "maximum": 4.0},
        "wind_speed": {"type": "number", "minimum": 0.0, "maximum": 4.0},
        "bloom_strength": {"type": "number", "minimum": 0.0, "maximum": 2.0},
        "star_count": {"type": "integer", "minimum": 0, "maximum": 8000},
        "star_radius": {"type": "number", "minimum": 5.0, "maximum": 2000.0},
        "star_size": {"type": "number", "minimum": 0.2, "maximum": 6.0},
        "camera_path": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "t": {"type": "number"},
                    "pos": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "look": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                },
                "required": ["t", "pos", "look"],
            },
        },
    },
}

# Per-capability metadata (aspects supported, rough CPU budget per output second).
_META: dict[str, dict[str, Any]] = {
    "scene3d.planet_orbit": {
        "kind": "shot",
        "aspects": ["16:9", "9:16"],
        "cpu_cost_hint": 1.6,
        "description": "漂浮 toon 小星球环绕镜头（小王子风格，CPU/SwiftShader 出片）。",
    },
    "scene3d.fox_wheat": {
        "kind": "shot",
        "aspects": ["9:16", "16:9"],
        "cpu_cost_hint": 0.8,
        "description": "麦田里的小狐狸竖屏镜头，风吹草动 + 暖色 bloom。",
    },
    "scene3d.star_sea": {
        "kind": "shot",
        "aspects": ["9:16", "16:9"],
        "cpu_cost_hint": 1.2,
        "description": "穿过星海推进镜头，星空粒子 + 大气雾 + bloom。",
    },
}


def _aspect_to_camera(aspect: str) -> dict[str, Any]:
    return {"aspect": aspect}


def _build_spec(name: str, params: dict[str, Any], duration: float, aspect: str, seed: int) -> Any:
    """Merge a preset example + safe overrides into a validated SceneSpec.

    Seed precedence: an explicit ``params["seed"]`` wins over the ``seed=``
    keyword argument (which is the caller/registry-level default).  Callers that
    pass both must expect ``params["seed"]`` to be authoritative; this is
    asserted by ``test_params_seed_overrides_seed_argument``.
    """
    preset_path = _EXAMPLES_DIR / _PRESETS[name]
    if not preset_path.is_file():
        raise CapabilityError(f"scene3d preset missing: {preset_path}")
    data = json.loads(preset_path.read_text(encoding="utf-8"))
    # Safe overrides only (the schema enforces this at registration time too).
    if "resolution" in params:
        data["resolution"] = int(params["resolution"])
    if "fps" in params:
        data["fps"] = int(params["fps"])
    if "seed" in params:
        data["seed"] = int(params["seed"])
    else:
        data["seed"] = seed
    data["duration_s"] = float(duration)
    data["camera"] = dict(data.get("camera", {}))
    data["camera"]["aspect"] = aspect
    # Per-aspect camera path override: a capability preset can ship a separate
    # portrait flight so a 9:16 render reframes instead of cropping the subject.
    aspect_paths = data["camera"].get("paths", {}) or {}
    if aspect in aspect_paths and aspect_paths[aspect]:
        data["camera"]["path"] = aspect_paths[aspect]
    if params.get("camera_path"):
        data["camera"]["path"] = params["camera_path"]
    wea = dict(data.get("weather", {}))
    for k in ("wind_strength", "wind_speed", "bloom_strength", "star_count", "star_radius", "star_size"):
        if k in params:
            wea[k] = params[k]
    data["weather"] = wea
    return parse_scene(data)


def _verify_video(video: Path, *, duration: float, fps: int, name: str) -> dict[str, Any]:
    """Integrity gate for a produced capability video.

    Checks, in order: the file exists and is non-empty (a missing mp4 must be a
    ``CapabilityError``, not a ``CalledProcessError`` from ffprobe), its
    duration is within tolerance, and its *decoded* frame count equals
    ``ceil(duration*fps)``.  A dropped/truncated frame fails here even when the
    container duration still looks plausible.

    Returns the counted probe dict.  Raises :class:`CapabilityError` on any
    failure.
    """
    import math

    # 1) existence first — never probe a missing file.
    if not video.exists() or video.stat().st_size == 0:
        raise CapabilityError(f"scene3d produced no video for {name}")
    # 2) probe (both a metadata probe and a decoded frame count).
    try:
        probe = ffprobe(video)
        counted = ffprobe_frames(video)
    except Exception as exc:
        raise CapabilityError(f"scene3d probe failed for {name}: {exc}") from exc
    if abs(probe.get("duration", 0.0) - float(duration)) > 0.5:
        raise CapabilityError(
            f"scene3d duration mismatch: wanted {duration}s got {probe.get('duration')}s"
        )
    # 3) exact decoded frame count.
    expected = max(1, math.ceil(float(duration) * int(fps)))
    if counted["nb_read_frames"] != expected:
        raise CapabilityError(
            f"scene3d frame count mismatch for {name}: expected {expected} "
            f"frames ({duration}s @ {fps}fps) got {counted['nb_read_frames']}"
        )
    return {"probe": probe, "counted": counted, "expected_frames": expected}


def _render_capability(
    name: str,
    params: dict[str, Any],
    out_dir: str | Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    """Core render callable shared by all scene3d capabilities.

    Every failure mode (bad params, unsupported aspect, missing preset, render
    crash, missing/truncated video) surfaces as :class:`CapabilityError` — never
    as a fake success.
    """
    from hevi.layer4_legacy.scene3d.renderer import SceneRenderer

    # Validate against the capability's own params schema first.
    cap = get(name)
    cap.validate_params(params)
    # A capability that declares only 16:9/9:16 must refuse 1:1 etc. up front
    # instead of silently rendering an unsupported frame.
    if not cap.supports_aspect(aspect):
        raise CapabilityError(
            f"capability {name} does not support aspect {aspect!r} "
            f"(supported: {cap.aspects})"
        )
    if duration <= 0:
        raise CapabilityError(f"capability {name}: duration must be positive, got {duration}")
    # These are finished preschool animation shots, not arbitrary micro-clips.
    # The minimum makes the visual beat readable and keeps API and ShotSpec
    # capability entry points aligned with the kids line's pacing contract.
    if duration < 2.0:
        raise CapabilityError(
            f"capability {name}: shot duration must be at least 2.0s, got {duration}"
        )

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        spec = _build_spec(name, params, duration, aspect, seed)
    except CapabilityError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise CapabilityError(f"scene3d failed to build scene: {exc}") from exc

    (out_dir / "scene.json").write_text(
        json.dumps(scene_to_dict(spec), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        r = SceneRenderer(spec, out_dir)
        metrics = r.render()
    except Exception as exc:
        raise CapabilityError(f"scene3d render failed for {name}: {exc}") from exc

    video = Path(metrics["video"])
    verified = _verify_video(
        video, duration=duration, fps=int(metrics["fps"]), name=name
    )
    probe = verified["probe"]
    counted = verified["counted"]
    return CapabilityResult(
        mp4=str(video),
        duration_s=metrics["duration_s"],
        sha256=sha256(video),
        qa={
            "frame_count": metrics["frame_count"],
            "nb_read_frames": counted["nb_read_frames"],
            "fps": metrics["fps"],
            "width": metrics["width"],
            "height": metrics["height"],
            "per_frame_s": metrics["per_frame_s"],
            "total_render_s": metrics["total_render_s"],
            "encode_s": metrics["encode_s"],
            "probe": probe,
            "seed": spec.seed,
            "aspect": aspect,
        },
    )


def register_scene3d_capabilities() -> list[Capability]:
    """Register the three scene3d capabilities into the global registry.

    Idempotent: re-running only refreshes the entries.  Returns the registered
    capabilities.
    """
    caps: list[Capability] = []
    for name, meta in _META.items():
        caps.append(
            register(
                Capability(
                    name=name,
                    kind=meta["kind"],
                    aspects=list(meta["aspects"]),
                    params_schema=_PARAMS_SCHEMA,
                    cpu_cost_hint=float(meta["cpu_cost_hint"]),
                    render=_make_render(name),
                    description=meta["description"],
                    line="scene3d",
                )
            )
        )
    return caps


def _make_render(name: str):
    """Bind a render closure to a specific capability name."""

    def _render(params: dict[str, Any], out_dir: str | Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
        return _render_capability(name, params, out_dir, duration=duration, aspect=aspect, seed=seed)

    _render.__name__ = f"render_{name.replace('.', '_')}"
    return _render


def register_scene3d_capabilities_once() -> list[Capability]:
    """Register only if not already present (keeps import-time idempotent)."""
    if all(contains(n) for n in _META):
        return [get(n) for n in _META]
    return register_scene3d_capabilities()
