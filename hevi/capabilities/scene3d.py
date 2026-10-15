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


# --------------------------------------------------------------------------- #
# VIBE3D-R1 additions: asset import / template / character animation
#
# Three product-line-agnostic capabilities so any line (ShotSpec workbench, zero,
# kids) can call the 3D pipeline by name without a private entry point
# (CAPABILITY_CONTRACT.md).
# --------------------------------------------------------------------------- #
_ASSET_IMPORT_NAME = "scene3d_asset_import"
_TEMPLATE_NAME = "scene3d_template"
_CHARACTER_NAME = "scene3d_character_anim"

_ASSET_IMPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "asset_id": {"type": "string", "minLength": 1},
    },
    "required": ["asset_id"],
}

_TEMPLATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "template": {"enum": ["little_planet", "town_street", "playground"]},
        "camera_preset": {"enum": ["orbit", "push_in", "follow"]},
        "seed": {"type": "integer"},
        "resolution": {"type": "integer", "minimum": 64, "maximum": 4320},
        "fps": {"type": "integer", "minimum": 1, "maximum": 120},
    },
    "required": ["template"],
}

_CHARACTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "template": {"enum": ["little_planet", "town_street", "playground"]},
        "camera_preset": {"enum": ["orbit", "push_in", "follow"]},
        "asset_id": {"type": "string", "minLength": 1},
        "clip": {"type": "string", "minLength": 1},
        "time_scale": {"type": "number", "minimum": 0.1, "maximum": 4.0},
        "seed": {"type": "integer"},
        "resolution": {"type": "integer", "minimum": 64, "maximum": 4320},
        "fps": {"type": "integer", "minimum": 1, "maximum": 120},
    },
    "required": ["template"],
}


def _render_asset_import(
    params: dict[str, Any], out_dir: str | Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    """Validate + describe one admitted GLB asset (no render; a data capability).

    Returns the manifest record so a caller can inspect triangle/texture/skin
    facts before binding the asset into a scene.  A missing asset is a
    :class:`CapabilityError`, never a fabricated record.
    """
    from hevi.layer4_legacy.scene3d.renderer import _load_asset_manifest

    cap = get(_ASSET_IMPORT_NAME)
    cap.validate_params(params)
    asset_id = str(params["asset_id"])
    record = _load_asset_manifest().get(asset_id)
    if record is None:
        raise CapabilityError(f"scene3d asset {asset_id!r} is not in the manifest")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"asset_{asset_id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=duration,
        sha256=record.get("optimized_sha256") or record.get("sha256"),
        qa={
            "asset_id": asset_id,
            "kind": record.get("kind"),
            "licence": record.get("licence"),
            "attribution": record.get("attribution"),
            "triangles": record.get("optimized_triangles") or record.get("triangles"),
            "source_triangles": record.get("triangles"),
            "max_texture_dim": record.get("max_texture_dim"),
            "texture_target": record.get("texture_target"),
            "skin_count": record.get("skin_count"),
            "joint_count": record.get("joint_count"),
            "animations": record.get("animations", []),
            "yaw_deg": record.get("yaw_deg"),
        },
    )


def _render_template(
    name: str,
    params: dict[str, Any],
    out_dir: str | Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    """Render a named preschool scene template through the CPU renderer."""
    from hevi.layer4_legacy.scene3d.renderer import SceneRenderer
    from hevi.layer4_legacy.scene3d.templates import build_template

    cap = get(name)
    cap.validate_params(params)
    if not cap.supports_aspect(aspect):
        raise CapabilityError(
            f"capability {name} does not support aspect {aspect!r} (supported: {cap.aspects})"
        )
    if duration <= 0:
        raise CapabilityError(f"capability {name}: duration must be positive, got {duration}")
    if duration < 2.0:
        raise CapabilityError(
            f"capability {name}: shot duration must be at least 2.0s, got {duration}"
        )

    template = str(params.get("template") or "little_planet")
    resolution = int(params.get("resolution", 1080))
    fps = int(params.get("fps", 30))
    use_seed = int(params["seed"]) if "seed" in params else seed
    try:
        spec = build_template(
            template,
            aspect=aspect,
            duration=float(duration),
            seed=use_seed,
            camera_preset=str(params.get("camera_preset", "")),
            resolution=resolution,
        )
    except ValueError as exc:
        raise CapabilityError(f"capability {name}: {exc}") from exc
    spec.fps = fps

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scene.json").write_text(
        json.dumps(scene_to_dict(spec), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        metrics = SceneRenderer(spec, out_dir).render()
    except Exception as exc:
        raise CapabilityError(f"capability {name} render failed: {exc}") from exc

    video = Path(metrics["video"])
    verified = _verify_video(video, duration=duration, fps=fps, name=name)
    return CapabilityResult(
        mp4=str(video),
        duration_s=metrics["duration_s"],
        sha256=sha256(video),
        qa={
            "template": template,
            "camera_preset": spec.camera.preset,
            "frame_count": metrics["frame_count"],
            "nb_read_frames": verified["counted"]["nb_read_frames"],
            "fps": metrics["fps"],
            "width": metrics["width"],
            "height": metrics["height"],
            "per_frame_s": metrics["per_frame_s"],
            "total_render_s": metrics["total_render_s"],
            "encode_s": metrics["encode_s"],
            "seed": spec.seed,
            "aspect": aspect,
        },
    )


def _render_character_anim(
    name: str,
    params: dict[str, Any],
    out_dir: str | Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    """Render a template and *verify* the character really moves skeletonally.

    The capability fails if no character is present or if limb bones do not
    displace across the shot — a walking capability that renders a static rig is
    a fake success and must not pass.
    """
    from hevi.layer4_legacy.scene3d.renderer import SceneRenderer
    from hevi.layer4_legacy.scene3d.templates import build_template

    cap = get(name)
    cap.validate_params(params)
    if not cap.supports_aspect(aspect):
        raise CapabilityError(
            f"capability {name} does not support aspect {aspect!r} (supported: {cap.aspects})"
        )
    if duration < 2.0:
        raise CapabilityError(
            f"capability {name}: shot duration must be at least 2.0s, got {duration}"
        )

    template = str(params.get("template") or "town_street")
    resolution = int(params.get("resolution", 1080))
    fps = int(params.get("fps", 30))
    use_seed = int(params["seed"]) if "seed" in params else seed
    try:
        spec = build_template(
            template,
            aspect=aspect,
            duration=float(duration),
            seed=use_seed,
            camera_preset=str(params.get("camera_preset", "")),
            resolution=resolution,
        )
    except ValueError as exc:
        raise CapabilityError(f"capability {name}: {exc}") from exc
    spec.fps = fps
    # Force the requested character asset/clip when provided.
    if params.get("asset_id") or params.get("clip") or "time_scale" in params:
        for asset in spec.assets:
            if asset.kind == "character":
                if params.get("asset_id"):
                    asset.params["asset_id"] = str(params["asset_id"])
                if params.get("clip"):
                    asset.params["clip"] = str(params["clip"])
                if "time_scale" in params:
                    asset.params["time_scale"] = float(params["time_scale"])

    if not any(a.kind == "character" for a in spec.assets):
        raise CapabilityError(
            f"capability {name}: template {template!r} has no character to animate"
        )

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scene.json").write_text(
        json.dumps(scene_to_dict(spec), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    renderer = SceneRenderer(spec, out_dir)
    try:
        times = [0.0, duration * 0.25, duration * 0.5, duration * 0.75, duration]
        stats = renderer.probe_character_stats(times)
        motion = _character_motion(stats)
        if motion["max_limb_displacement"] < 0.05:
            raise CapabilityError(
                f"capability {name}: character limbs do not move "
                f"(max displacement {motion['max_limb_displacement']:.4f} m)"
            )
        metrics = renderer.render()
    except CapabilityError:
        raise
    except Exception as exc:
        raise CapabilityError(f"capability {name} render failed: {exc}") from exc

    video = Path(metrics["video"])
    verified = _verify_video(video, duration=duration, fps=fps, name=name)
    # Chain the kids gate + layout gate.  A shot that fails either gate is a
    # CapabilityError: the contract forbids returning a fake success.
    from hevi.layer4_legacy.scene3d.gates import run_scene_gates

    gate_boxes = renderer.probe_subject_bboxes(times)
    gate_report = run_scene_gates(
        video,
        fps=float(fps),
        duration_s=float(duration),
        boxes=gate_boxes,
        frame_dir=out_dir / "gate_frames",
    )
    if not gate_report.passed:
        raise CapabilityError(
            f"capability {name}: scene gates failed: {'; '.join(gate_report.failures[:4])}"
        )
    return CapabilityResult(
        mp4=str(video),
        duration_s=metrics["duration_s"],
        sha256=sha256(video),
        qa={
            "template": template,
            "camera_preset": spec.camera.preset,
            "character_motion": motion,
            "scene_gates": gate_report.as_dict(),
            "frame_count": metrics["frame_count"],
            "nb_read_frames": verified["counted"]["nb_read_frames"],
            "fps": metrics["fps"],
            "width": metrics["width"],
            "height": metrics["height"],
            "per_frame_s": metrics["per_frame_s"],
            "total_render_s": metrics["total_render_s"],
            "seed": spec.seed,
            "aspect": aspect,
        },
    )


def _character_motion(stats: list[dict[str, Any]]) -> dict[str, Any]:
    """Max world-space limb displacement across sampled times (metres)."""
    import math

    if len(stats) < 2:
        return {"max_limb_displacement": 0.0, "samples": len(stats), "bones": []}
    bone_names: set[str] = set()
    for row in stats:
        for c in row["characters"]:
            bone_names |= set(c["bones"].keys())
    peak = 0.0
    per_bone: dict[str, float] = {}
    for bone in sorted(bone_names):
        pts = []
        for row in stats:
            for c in row["characters"]:
                if bone in c["bones"]:
                    pts.append(c["bones"][bone])
        if len(pts) < 2:
            continue
        d = 0.0
        for i in range(1, len(pts)):
            d = max(d, math.dist(pts[0], pts[i]))
        per_bone[bone] = round(d, 4)
        peak = max(peak, d)
    return {
        "max_limb_displacement": round(peak, 4),
        "samples": len(stats),
        "bones": sorted(per_bone),
        "per_bone": per_bone,
    }


register(
    Capability(
        name=_ASSET_IMPORT_NAME,
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema=_ASSET_IMPORT_SCHEMA,
        cpu_cost_hint=0.05,
        render=lambda params, out_dir, *, duration, aspect, seed: _render_asset_import(
            params, out_dir, duration=duration, aspect=aspect, seed=seed
        ),
        description="导入并校验一件 GLB 资产（读三角面/顶点/贴图/骨骼/动画剪辑，返回清单记录）。",
        line="scene3d",
    )
)

register(
    Capability(
        name=_TEMPLATE_NAME,
        kind="shot",
        aspects=["16:9", "9:16"],
        params_schema=_TEMPLATE_SCHEMA,
        cpu_cost_hint=1.5,
        render=lambda params, out_dir, *, duration, aspect, seed: _render_template(
            _TEMPLATE_NAME, params, out_dir, duration=duration, aspect=aspect, seed=seed
        ),
        description="渲染幼儿向 3D 场景模板（小星球 / 小镇街道 / 游乐园一角，含环绕/推近/跟随相机预设）。",
        line="scene3d",
    )
)

register(
    Capability(
        name=_CHARACTER_NAME,
        kind="shot",
        aspects=["16:9", "9:16"],
        params_schema=_CHARACTER_SCHEMA,
        cpu_cost_hint=1.8,
        render=lambda params, out_dir, *, duration, aspect, seed: _render_character_anim(
            _CHARACTER_NAME, params, out_dir, duration=duration, aspect=aspect, seed=seed
        ),
        description="渲染带骨骼 GLB 角色的行走镜头（AnimationMixer 确定性时间步驱动，肢体位移被实测校验）。",
        line="scene3d",
    )
)


def register_scene3d_vibe_capabilities() -> list[Capability]:
    """Register the three VIBE3D-R1 capabilities (idempotent)."""
    names = (_ASSET_IMPORT_NAME, _TEMPLATE_NAME, _CHARACTER_NAME)
    if all(contains(n) for n in names):
        return [get(n) for n in names]
    # The three ``register`` calls above run at import time; re-running is safe.
    return [get(n) for n in names]
