"""SCENE3D — Hevi CPU 3D stylized scene line (clean-room, Three.js + Playwright/SwiftShader).

This module builds a deterministic, CPU-only 3D scene renderer that produces
9:16 / 16:9 "Little-Prince-style" shots: floating toon planets, instanced
wind-driven wheat/grass, a starfield, atmospheric fog and UnrealBloom glow —
all rendered deterministically frame-by-frame through ``window.__setTime`` so
that the same seed yields byte-identical frames.

Everything is offline-friendly: Three.js (r169) and its postprocessing passes
are vendored under ``vendor/three`` (MIT, https://github.com/mrdoob/three.js),
and no paid API / GPU is touched.
"""

from __future__ import annotations

from .schema import (
    SceneSpec,
    AssetSpec,
    CameraSpec,
    LightSpec,
    WeatherSpec,
    load_scene,
    validate_scene,
)
from .renderer import SceneRenderer
from .cli import main as cli_main

__all__ = [
    "SceneSpec",
    "AssetSpec",
    "CameraSpec",
    "LightSpec",
    "WeatherSpec",
    "load_scene",
    "validate_scene",
    "SceneRenderer",
    "cli_main",
]
