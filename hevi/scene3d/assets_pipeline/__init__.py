"""SCENE3D asset pipeline (hevi/scene3d/assets_pipeline).

Import → validate → decimate + texture-downscale → cache → manifest, following
the method internalised in ``docs/SCENE3D_VIBE_RULES.md`` (§04 / §17).

Public surface:

* :func:`inspect_glb` — pure-Python GLB reader (triangles/vertices/textures/
  bbox/skins/clips), no engine required.
* :func:`validate_glb` — admission checks against the SCENE3D ceilings.
* :func:`optimize_asset` — decimate by geometry class + texture ceiling, cached.
* :func:`run_pipeline` — the whole batch, writing an :class:`AssetManifest`.
* :class:`RenderBudget` / :func:`enforce_budget` — the per-frame CPU budget gate.
"""

from __future__ import annotations

from .budget import (
    BudgetExceeded,
    BudgetNotMeasured,
    RenderBudget,
    enforce_budget,
    measure_budget,
)
from .glb import GlbError, GlbInfo, inspect_glb
from .manifest import AssetManifest, AssetRecord, build_record, sha256_file
from .optimize import (
    DEFAULT_RATIOS,
    OptimizeResult,
    OptimizerUnavailable,
    find_gltf_transform,
    optimize_asset,
    ratio_for_kind,
)
from .pipeline import (
    AssetRejected,
    PipelineResult,
    ValidationReport,
    run_pipeline,
    validate_glb,
)

__all__ = [
    "AssetManifest",
    "AssetRecord",
    "AssetRejected",
    "BudgetExceeded",
    "BudgetNotMeasured",
    "DEFAULT_RATIOS",
    "GlbError",
    "GlbInfo",
    "OptimizeResult",
    "OptimizerUnavailable",
    "PipelineResult",
    "RenderBudget",
    "ValidationReport",
    "build_record",
    "enforce_budget",
    "find_gltf_transform",
    "inspect_glb",
    "measure_budget",
    "optimize_asset",
    "ratio_for_kind",
    "run_pipeline",
    "sha256_file",
    "validate_glb",
]
