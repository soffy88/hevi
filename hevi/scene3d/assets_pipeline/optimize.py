"""CPU-budget-aware GLB optimiser (decimation + texture downscale + cache).

Implements the handbook's §04/§17 cleaning pipeline for the SCENE3D line:

* **Decimate by geometry class, never one ratio for the whole library** — the
  E1 experiment showed continuous surfaces survive 0.25 while buildings need
  0.45 and trees/landmarks are effectively immovable at 0.75 (§04).
* **Downscale textures to a 512 / 1K ceiling** — the handbook's single biggest
  win was texture memory, not triangles (§04 "减面之前先去量贴图").
* **Never decimate a skinned mesh** — the rig lives on the mesh; dropping
  triangles under a 41-joint skin is not something we validated, so it is
  refused rather than guessed at.
* **Cache by (source sha256, ratio, texture target)** so a repeat run reuses the
  artefact instead of shelling out again.

The optimiser shells out to the locally installed ``gltf-transform`` CLI.  When
the tool is missing the caller gets a :class:`OptimizerUnavailable` — never a
silent pass-through that would make the manifest lie about what was produced.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .glb import GlbInfo, inspect_glb
from .manifest import sha256_file

__all__ = [
    "OptimizerUnavailable",
    "OptimizeResult",
    "DEFAULT_RATIOS",
    "ratio_for_kind",
    "find_gltf_transform",
    "optimize_asset",
]

# Decimation ratio by geometry class (E2 production values, §04).
DEFAULT_RATIOS: dict[str, float] = {
    "character": 0.25,
    "vehicle": 0.25,
    "prop": 0.25,
    "building": 0.45,
    "landmark": 0.75,
    "vegetation": 0.75,
}


class OptimizerUnavailable(RuntimeError):
    """``gltf-transform`` could not be located on this host."""


@dataclass
class OptimizeResult:
    """Outcome of one optimisation: before/after facts, all measured."""

    asset_id: str
    source_path: str
    output_path: str
    ratio: float
    texture_target: int
    cache_hit: bool
    before: GlbInfo
    after: GlbInfo
    optimized_sha256: str

    @property
    def triangle_reduction(self) -> float:
        if self.before.triangles == 0:
            return 0.0
        return 1.0 - self.after.triangles / self.before.triangles

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "source_path": self.source_path,
            "output_path": self.output_path,
            "ratio": self.ratio,
            "texture_target": self.texture_target,
            "cache_hit": self.cache_hit,
            "before": {
                "triangles": self.before.triangles,
                "vertices": self.before.vertices,
                "size_bytes": self.before.byte_length,
                "max_texture_dim": self.before.max_texture_dim,
            },
            "after": {
                "triangles": self.after.triangles,
                "vertices": self.after.vertices,
                "size_bytes": self.after.byte_length,
                "max_texture_dim": self.after.max_texture_dim,
            },
            "triangle_reduction": round(self.triangle_reduction, 4),
            "optimized_sha256": self.optimized_sha256,
        }


def ratio_for_kind(kind: str) -> float:
    """Decimation ratio for a geometry class (defaults to the prop ratio)."""
    return DEFAULT_RATIOS.get(kind, DEFAULT_RATIOS["prop"])


def find_gltf_transform(repo_root: str | Path | None = None) -> str | None:
    """Locate the ``gltf-transform`` binary (PATH first, then repo node_modules)."""
    found = shutil.which("gltf-transform")
    if found:
        return found
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[3]
    for candidate in (
        Path(repo_root) / "node_modules" / ".bin" / "gltf-transform",
        Path(repo_root) / "node_modules" / "gltf-transform" / "bin" / "cli.js",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"gltf-transform failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"stderr: {proc.stderr[-800:]}"
        )


def _cache_key(source_sha: str, ratio: float, texture_target: int) -> str:
    raw = f"{source_sha}:{ratio:.4f}:{texture_target}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def optimize_asset(
    asset_id: str,
    source_path: str | Path,
    cache_dir: str | Path,
    *,
    kind: str = "prop",
    ratio: float | None = None,
    texture_target: int = 512,
    repo_root: str | Path | None = None,
) -> OptimizeResult:
    """Decimate + downscale one GLB into ``cache_dir`` and measure both ends.

    A skinned mesh (``skin_count > 0``) is copied through unchanged: the handbook
    validates decimation on static assets only, and re-rigging a decimated mesh
    is out of scope, so guessing would put an unverified number in the manifest.
    """
    src = Path(source_path)
    src_info = inspect_glb(src)
    ratio = ratio_for_kind(kind) if ratio is None else ratio

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    source_sha = sha256_file(src)
    key = _cache_key(source_sha, ratio, texture_target)
    out = cache_dir / f"{asset_id}-{key}.glb"

    skinned = src_info.skin_count > 0
    if out.exists():
        after = inspect_glb(out)
        return OptimizeResult(
            asset_id=asset_id,
            source_path=str(src),
            output_path=str(out),
            ratio=ratio,
            texture_target=texture_target,
            cache_hit=True,
            before=src_info,
            after=after,
            optimized_sha256=sha256_file(out),
        )

    binary = find_gltf_transform(repo_root)
    if binary is None:
        raise OptimizerUnavailable(
            "gltf-transform not found (PATH or repo node_modules); "
            "run `npm install @gltf-transform/cli` in the worktree"
        )

    tmp = cache_dir / f".{asset_id}-{key}.tmp.glb"
    if skinned:
        # No decimation under a skin; only the texture ceiling is applied.
        _run([binary, "resize", str(src), str(tmp), "--width", str(texture_target), "--height", str(texture_target)])
    else:
        simplified = cache_dir / f".{asset_id}-{key}.simplify.glb"
        _run([binary, "simplify", str(src), str(simplified), "--ratio", str(ratio), "--error", "1"])
        _run(
            [
                binary, "optimize", str(simplified), str(tmp),
                "--compress", "quantize",
                "--texture-size", str(texture_target),
            ]
        )
        simplified.unlink(missing_ok=True)
    tmp.replace(out)

    after = inspect_glb(out)
    return OptimizeResult(
        asset_id=asset_id,
        source_path=str(src),
        output_path=str(out),
        ratio=ratio,
        texture_target=texture_target,
        cache_hit=False,
        before=src_info,
        after=after,
        optimized_sha256=sha256_file(out),
    )


def write_optimize_log(results: list[OptimizeResult], path: str | Path) -> Path:
    """Write a machine-readable before/after log for the whole batch."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "count": len(results),
        "total_before_bytes": sum(r.before.byte_length for r in results),
        "total_after_bytes": sum(r.after.byte_length for r in results),
        "total_before_triangles": sum(r.before.triangles for r in results),
        "total_after_triangles": sum(r.after.triangles for r in results),
        "results": [r.as_dict() for r in results],
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p
