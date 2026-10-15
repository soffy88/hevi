"""SCENE3D asset pipeline — import → validate → optimise → cache → manifest.

The single entry point the rest of Hevi uses to admit a GLB into the SCENE3D
line.  It implements the handbook's §17 four-step clean pipeline with the §04
per-geometry-class decimation ratios, and it writes every measured number into a
manifest record so nothing downstream has to trust a filename.

    import → validate (triangles/vertices/texture dims/size/rig/clips)
           → optimise (ratio by class + texture ceiling)
           → cache    (keyed by source sha256 + ratio + target)
           → manifest (provenance + licence + attribution + measured spec)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .budget import RenderBudget, measure_budget
from .glb import GlbInfo, inspect_glb
from .manifest import AssetManifest, AssetRecord, build_record
from .optimize import OptimizeResult, optimize_asset, ratio_for_kind, write_optimize_log

__all__ = [
    "AssetRejected",
    "ValidationReport",
    "PipelineResult",
    "validate_glb",
    "run_pipeline",
]

# Admission limits.  These are the ceilings the pipeline refuses to cross
# silently; a violation is a hard error, not a warning, because a manifest that
# records an out-of-budget asset is worse than no manifest at all.
MAX_SOURCE_TRIANGLES = 400_000
MAX_SOURCE_TEXTURE_DIM = 8192
MAX_SOURCE_MIB = 60.0
# Height p90 below this means the bbox is stretched by a thin pole / antenna /
# umbrella, so the asset must not be normalised by total height (§17).
MIN_HEIGHT_P90_FRACTION = 0.70


class AssetRejected(ValueError):
    """An asset failed an admission check and must not enter the manifest."""


@dataclass
class ValidationReport:
    """The result of validating one GLB against the SCENE3D admission rules."""

    asset_id: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: GlbInfo | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "passed": self.passed,
            "failures": list(self.failures),
            "warnings": list(self.warnings),
            "info": self.info.as_dict() if self.info else None,
        }


def validate_glb(asset_id: str, path: str | Path) -> ValidationReport:
    """Validate a GLB against the SCENE3D admission rules (real measurements)."""
    failures: list[str] = []
    warnings: list[str] = []
    info = inspect_glb(path)

    if info.meshopt:
        failures.append(
            "EXT_meshopt_compression present: run `gltf-transform copy` first "
            "(a hand parser reads it as garbage, §04 Appendix B)"
        )
    if info.quantization:
        warnings.append(
            "KHR_mesh_quantization present: positions are normalized ints, "
            "so accessor min/max are scaled — the pipeline normalizes before use"
        )
    if info.triangles > MAX_SOURCE_TRIANGLES:
        failures.append(f"{info.triangles} triangles > {MAX_SOURCE_TRIANGLES} ceiling")
    if info.mesh_count == 0:
        failures.append("no meshes")
    if info.max_texture_dim > MAX_SOURCE_TEXTURE_DIM:
        failures.append(f"texture {info.max_texture_dim}px > {MAX_SOURCE_TEXTURE_DIM}px ceiling")
    if info.size_mib > MAX_SOURCE_MIB:
        failures.append(f"{info.size_mib:.1f} MiB > {MAX_SOURCE_MIB} MiB ceiling")
    if info.double_sided_count:
        warnings.append(
            f"{info.double_sided_count} material(s) doubleSided: fragment cost is "
            "doubled and the render looks identical (§17)"
        )
    if info.height_p90_fraction is not None and info.height_p90_fraction < MIN_HEIGHT_P90_FRACTION:
        warnings.append(
            f"height p90 {info.height_p90_fraction:.2f} < {MIN_HEIGHT_P90_FRACTION}: "
            "bbox height is stretched by a thin feature — do not normalise by total height (§17)"
        )
    for anim in info.animations:
        if anim.channel_count and anim.animated_channels == 0:
            warnings.append(f"animation {anim.name!r} has {anim.channel_count} constant channels")
    if info.skin_count and info.animations and info.joint_count != 41:
        warnings.append(
            f"skinned mesh with {info.joint_count} joints (Tripo biped preset is 41)"
        )

    return ValidationReport(
        asset_id=asset_id,
        passed=not failures,
        failures=failures,
        warnings=warnings,
        info=info,
    )


@dataclass
class PipelineResult:
    """One asset's journey through import → validate → optimise → manifest."""

    record: AssetRecord
    validation: ValidationReport
    optimize: OptimizeResult | None
    budget: RenderBudget | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "record": self.record.as_dict(),
            "validation": self.validation.as_dict(),
            "optimize": self.optimize.as_dict() if self.optimize else None,
            "budget": self.budget.as_dict() if self.budget else None,
        }


# Source-pack provenance.  Every asset in assets/scene3d/source comes from the
# handbook's release packages (CC BY-NC-SA 4.0); the attribution string is the
# one written into NOTICE and ATTRIBUTION.
HANDBOOK_LICENCE = "CC BY-NC-SA 4.0"
HANDBOOK_ATTRIBUTION = (
    "花叔《3D Vibe Coding 手册》随书资源包 (v260914c), "
    "https://github.com/alchaincyf/3d-vibe-coding-handbook"
)

# yaw conventions from §06: P2.0 family faces +X, so a pedestrian faces the
# camera with yaw -90 and a building needs +90 to face down the street.
_YAW_BY_KIND = {"character": -90.0, "building": 90.0, "vehicle": -90.0}


def run_pipeline(
    source_dir: str | Path,
    *,
    out_manifest: str | Path,
    cache_dir: str | Path,
    optimize_log: str | Path | None = None,
    texture_target: int = 512,
    repo_root: str | Path | None = None,
    spec: dict[str, dict[str, Any]] | None = None,
) -> tuple[AssetManifest, list[PipelineResult]]:
    """Run the whole pipeline over ``source_dir`` and write the manifest.

    ``spec`` maps asset_id -> overrides (``kind``, ``yaw_deg``, ``source_file``).
    Assets not listed are still admitted with a filename-derived id and the
    default ``prop`` class, so a new drop is never silently skipped.
    """
    source_dir = Path(source_dir)
    spec = spec or {}
    manifest = AssetManifest()
    results: list[PipelineResult] = []

    for glb in sorted(source_dir.glob("*.glb")):
        asset_id = glb.stem
        overrides = spec.get(asset_id, {})
        kind = str(overrides.get("kind", "prop"))
        yaw = float(overrides.get("yaw_deg", _YAW_BY_KIND.get(kind, 0.0)))

        report = validate_glb(asset_id, glb)
        if not report.passed:
            raise AssetRejected(f"{asset_id}: {'; '.join(report.failures)}")

        opt = optimize_asset(
            asset_id,
            glb,
            cache_dir,
            kind=kind,
            texture_target=texture_target,
            repo_root=repo_root,
        )

        record = build_record(
            asset_id,
            glb,
            source_pack=str(overrides.get("source_pack", "3d-vibe-coding-handbook v260914c")),
            source_file=str(overrides.get("source_file", glb.name)),
            licence=HANDBOOK_LICENCE,
            attribution=HANDBOOK_ATTRIBUTION,
            kind=kind,
            yaw_deg=yaw,
            info=report.info,
        )
        record.optimized = True
        record.optimized_sha256 = opt.optimized_sha256
        record.optimized_triangles = opt.after.triangles
        record.optimized_size_bytes = opt.after.byte_length
        record.optimize_ratio = opt.ratio
        record.texture_target = texture_target

        manifest.assets.append(record)
        results.append(PipelineResult(record=record, validation=report, optimize=opt))

    manifest.write(out_manifest)
    if optimize_log is not None:
        write_optimize_log([r.optimize for r in results if r.optimize], optimize_log)
    return manifest, results
