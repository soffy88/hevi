"""SCENE3D JSON scene schema (dataclasses + jsonschema validation).

A scene is described entirely by JSON so the renderer is data-driven: assets,
camera path, lights, weather and duration all live in the scene spec.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # jsonschema ships in the repo tooling; degrade gracefully if missing.
    import jsonschema

    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover - jsonschema is always present in CI.
    _HAS_JSONSCHEMA = False


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class AssetSpec:
    """A scene object to instantiate.

    ``kind`` selects the procedural/built-in generator:
      planet | wheat | grass | fox | starfield | rock | tree | bush | ground
    ``params`` are kind-specific (color, scale, count, position, …).
    """

    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    name: str | None = None


@dataclass
class CameraSpec:
    """Camera framing + flight path, time in seconds."""

    aspect: str = "16:9"  # 16:9 | 9:16 | 1:1 | 21:9
    fov: float = 42.0
    near: float = 0.1
    far: float = 2000.0
    # Waypoints: list of {t, pos:[x,y,z], look:[x,y,z]}
    path: list[dict[str, Any]] = field(default_factory=list)
    # Per-aspect waypoint overrides: {"9:16": [...], "16:9": [...]}.  When the
    # requested aspect is present here it wins over ``path`` so a portrait
    # reframe can pull the camera back instead of reusing the landscape flight
    # (which would crop the subject out of the top of frame).
    paths: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # Optional dolly default position if no path given.
    pos: list[float] = field(default_factory=lambda: [0.0, 2.0, 12.0])
    look: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])


@dataclass
class LightSpec:
    """Sun + ambient + optional rim light."""

    sun_color: list[float] = field(default_factory=lambda: [1.0, 0.85, 0.6])
    sun_intensity: float = 1.4
    sun_pos: list[float] = field(default_factory=lambda: [8.0, 14.0, 6.0])
    ambient_color: list[float] = field(default_factory=lambda: [0.35, 0.45, 0.7])
    ambient_intensity: float = 0.7
    rim_color: list[float] = field(default_factory=lambda: [0.6, 0.8, 1.0])
    rim_intensity: float = 0.6


@dataclass
class WeatherSpec:
    """Sky + atmosphere + wind + particle behaviour."""

    background_top: list[float] = field(default_factory=lambda: [0.05, 0.07, 0.18])
    background_bottom: list[float] = field(default_factory=lambda: [0.25, 0.13, 0.20])
    fog_color: list[float] = field(default_factory=lambda: [0.18, 0.16, 0.28])
    fog_density: float = 0.012
    wind_strength: float = 1.0
    wind_speed: float = 1.4
    starfield: bool = True
    star_count: int = 1400
    # Star shell radius (world units).  A small value places the stars right in
    # the camera path so a push-in flies *through* them; a large value keeps
    # them as a distant backdrop.
    star_radius: float = 900.0
    star_size: float = 1.0
    bloom_strength: float = 0.55
    bloom_radius: float = 0.55
    bloom_threshold: float = 0.85
    shadows: bool = True
    # Gentle fox breathing/tail sway.  Disabled by the wind-determinism test so
    # that a static camera + wind off yields byte-identical frames.
    fox_sway: bool = True


@dataclass
class SceneSpec:
    """Top-level scene description."""

    name: str = "scene3d"
    duration_s: float = 12.0
    fps: int = 30
    resolution: int = 1080  # render height (width derived from aspect)
    seed: int = 1234
    camera: CameraSpec = field(default_factory=CameraSpec)
    lights: LightSpec = field(default_factory=LightSpec)
    weather: WeatherSpec = field(default_factory=WeatherSpec)
    assets: list[AssetSpec] = field(default_factory=list)

    @property
    def width(self) -> int:
        ar = self._aspect_ratio
        return round(self.resolution * (ar if ar >= 1 else 1))

    @property
    def height(self) -> int:
        ar = self._aspect_ratio
        return round(self.resolution * (1 if ar >= 1 else 1 / ar))

    @property
    def _aspect_ratio(self) -> float:
        # width / height, parsed from the human-readable aspect string.
        return {
            "9:16": 9 / 16,
            "1:1": 1.0,
            "21:9": 21 / 9,
        }.get(self.camera.aspect, 16 / 9)


# --------------------------------------------------------------------------- #
# JSON schema
# --------------------------------------------------------------------------- #
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "duration_s": {"type": "number", "minimum": 0.1, "maximum": 3600.0},
        "fps": {"type": "integer", "minimum": 1, "maximum": 120},
        "resolution": {"type": "integer", "minimum": 64, "maximum": 4320},
        "seed": {"type": "integer"},
        "camera": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "aspect": {"enum": ["16:9", "9:16", "1:1", "21:9"]},
                "fov": {"type": "number", "minimum": 1.0, "maximum": 179.0},
                "near": {"type": "number", "minimum": 0.001},
                "far": {"type": "number", "minimum": 1.0},
                "path": {
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
                "paths": {
                    "type": "object",
                    "additionalProperties": {
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
                "pos": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "look": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
            },
        },
        "lights": {"type": "object"},
        "weather": {"type": "object"},
        "assets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "name": {"type": ["string", "null"]},
                    "params": {"type": "object"},
                },
                "required": ["kind"],
            },
        },
    },
}


# --------------------------------------------------------------------------- #
# Loaders / validators
# --------------------------------------------------------------------------- #
def _to_asset(d: dict[str, Any]) -> AssetSpec:
    return AssetSpec(kind=d["kind"], params=d.get("params", {}), name=d.get("name"))


def load_scene(path: str | Path) -> SceneSpec:
    """Parse a JSON scene file into a ``SceneSpec`` (and validate it)."""
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    return parse_scene(data)


def parse_scene(data: dict[str, Any]) -> SceneSpec:
    # Validate the raw scene document before building the spec so structural
    # problems (e.g. an asset missing the required `kind`) are caught here
    # rather than via a late KeyError during construction.
    _validate_data(data)
    cam = data.get("camera", {})
    lig = data.get("lights", {})
    wea = data.get("weather", {})
    spec = SceneSpec(
        name=data.get("name", "scene3d"),
        duration_s=float(data.get("duration_s", 12.0)),
        fps=int(data.get("fps", 30)),
        resolution=int(data.get("resolution", 1080)),
        seed=int(data.get("seed", 1234)),
        camera=CameraSpec(
            aspect=cam.get("aspect", "16:9"),
            fov=float(cam.get("fov", 42.0)),
            near=float(cam.get("near", 0.1)),
            far=float(cam.get("far", 2000.0)),
            path=cam.get("path", []),
            paths=cam.get("paths", {}),
            pos=list(cam.get("pos", [0.0, 2.0, 12.0])),
            look=list(cam.get("look", [0.0, 0.0, 0.0])),
        ),
        lights=LightSpec(
            sun_color=list(lig.get("sun_color", [1.0, 0.85, 0.6])),
            sun_intensity=float(lig.get("sun_intensity", 1.4)),
            sun_pos=list(lig.get("sun_pos", [8.0, 14.0, 6.0])),
            ambient_color=list(lig.get("ambient_color", [0.35, 0.45, 0.7])),
            ambient_intensity=float(lig.get("ambient_intensity", 0.7)),
            rim_color=list(lig.get("rim_color", [0.6, 0.8, 1.0])),
            rim_intensity=float(lig.get("rim_intensity", 0.6)),
        ),
        weather=WeatherSpec(
            background_top=list(wea.get("background_top", [0.05, 0.07, 0.18])),
            background_bottom=list(wea.get("background_bottom", [0.25, 0.13, 0.20])),
            fog_color=list(wea.get("fog_color", [0.18, 0.16, 0.28])),
            fog_density=float(wea.get("fog_density", 0.012)),
            wind_strength=float(wea.get("wind_strength", 1.0)),
            wind_speed=float(wea.get("wind_speed", 1.4)),
            starfield=bool(wea.get("starfield", True)),
            star_count=int(wea.get("star_count", 1400)),
            star_radius=float(wea.get("star_radius", 900.0)),
            star_size=float(wea.get("star_size", 1.0)),
            bloom_strength=float(wea.get("bloom_strength", 0.55)),
            bloom_radius=float(wea.get("bloom_radius", 0.55)),
            bloom_threshold=float(wea.get("bloom_threshold", 0.85)),
            shadows=bool(wea.get("shadows", True)),
            fox_sway=bool(wea.get("fox_sway", True)),
        ),
        assets=[_to_asset(a) for a in data.get("assets", [])],
    )
    validate_scene(spec)
    return spec


def scene_to_dict(spec: SceneSpec) -> dict[str, Any]:
    """Serialise a ``SceneSpec`` back to the JSON document shape."""

    def vec(v: list[float]) -> list[float]:
        return [float(x) for x in v]

    return {
        "name": spec.name,
        "duration_s": spec.duration_s,
        "fps": spec.fps,
        "resolution": spec.resolution,
        "seed": spec.seed,
        "camera": {
            "aspect": spec.camera.aspect,
            "fov": spec.camera.fov,
            "near": spec.camera.near,
            "far": spec.camera.far,
            "path": [
                {"t": float(w["t"]), "pos": vec(w["pos"]), "look": vec(w["look"])}
                for w in spec.camera.path
            ],
            "paths": {
                aspect: [
                    {"t": float(w["t"]), "pos": vec(w["pos"]), "look": vec(w["look"])}
                    for w in waypoints
                ]
                for aspect, waypoints in spec.camera.paths.items()
            },
            "pos": vec(spec.camera.pos),
            "look": vec(spec.camera.look),
        },
        "lights": {
            "sun_color": vec(spec.lights.sun_color),
            "sun_intensity": spec.lights.sun_intensity,
            "sun_pos": vec(spec.lights.sun_pos),
            "ambient_color": vec(spec.lights.ambient_color),
            "ambient_intensity": spec.lights.ambient_intensity,
            "rim_color": vec(spec.lights.rim_color),
            "rim_intensity": spec.lights.rim_intensity,
        },
        "weather": {
            "background_top": vec(spec.weather.background_top),
            "background_bottom": vec(spec.weather.background_bottom),
            "fog_color": vec(spec.weather.fog_color),
            "fog_density": spec.weather.fog_density,
            "wind_strength": spec.weather.wind_strength,
            "wind_speed": spec.weather.wind_speed,
            "starfield": spec.weather.starfield,
            "star_count": spec.weather.star_count,
            "star_radius": spec.weather.star_radius,
            "star_size": spec.weather.star_size,
            "bloom_strength": spec.weather.bloom_strength,
            "bloom_radius": spec.weather.bloom_radius,
            "bloom_threshold": spec.weather.bloom_threshold,
            "shadows": spec.weather.shadows,
            "fox_sway": spec.weather.fox_sway,
        },
        "assets": [
            {"kind": a.kind, "name": a.name, "params": a.params} for a in spec.assets
        ],
    }


def _validate_data(data: dict[str, Any]) -> None:
    """Validate the raw scene document dict against the JSON schema."""
    if not _HAS_JSONSCHEMA:  # pragma: no cover
        return
    try:
        jsonschema.validate(instance=data, schema=_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"scene validation failed: {exc.message}") from exc


def validate_scene(spec: SceneSpec) -> None:
    """Validate a parsed spec (round-tripped through the schema) for symmetry."""
    if not _HAS_JSONSCHEMA:  # pragma: no cover
        return
    doc = scene_to_dict(spec)
    try:
        jsonschema.validate(instance=doc, schema=_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"scene validation failed: {exc.message}") from exc
