"""SCENE3D asset manifest — the on-disk registry of admitted GLB assets.

Every asset that the SCENE3D line is allowed to place in a template must have a
manifest record: where it came from, its licence and attribution, its
measured spec, and the CPU budget it was admitted under.  The handbook's rule is
that a file is not an asset until you have read its numbers yourself (§03/§04),
so a record is only ever written from a real :func:`inspect_glb` pass.

The manifest is plain JSON so it is diffable in review and readable by the
capability layer without importing the pipeline.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .glb import GlbInfo, inspect_glb

__all__ = [
    "AssetRecord",
    "AssetManifest",
    "sha256_file",
    "build_record",
]

MANIFEST_SCHEMA_VERSION = 1


def sha256_file(path: str | Path) -> str:
    """SHA-256 of a file, streamed (never loads the whole file into memory)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class AssetRecord:
    """One admitted asset: provenance + licence + measured spec + budget."""

    asset_id: str
    source_pack: str
    source_file: str
    licence: str
    attribution: str
    sha256: str
    size_bytes: int
    triangles: int
    vertices: int
    texture_count: int
    max_texture_dim: int
    mesh_count: int
    skin_count: int = 0
    joint_count: int = 0
    animations: list[dict[str, Any]] = field(default_factory=list)
    double_sided_count: int = 0
    height_p90_fraction: float | None = None
    bbox_min: list[float] | None = None
    bbox_max: list[float] | None = None
    bbox_size: list[float] | None = None
    yaw_deg: float = 0.0
    # Pipeline-derived fields (filled by the optimiser, if any).
    optimized: bool = False
    optimized_sha256: str | None = None
    optimized_triangles: int | None = None
    optimized_size_bytes: int | None = None
    optimize_ratio: float | None = None
    texture_target: int | None = None
    kind: str = "prop"

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "kind": self.kind,
            "source_pack": self.source_pack,
            "source_file": self.source_file,
            "licence": self.licence,
            "attribution": self.attribution,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "triangles": self.triangles,
            "vertices": self.vertices,
            "texture_count": self.texture_count,
            "max_texture_dim": self.max_texture_dim,
            "mesh_count": self.mesh_count,
            "skin_count": self.skin_count,
            "joint_count": self.joint_count,
            "animations": list(self.animations),
            "double_sided_count": self.double_sided_count,
            "height_p90_fraction": self.height_p90_fraction,
            "bbox_min": self.bbox_min,
            "bbox_max": self.bbox_max,
            "bbox_size": self.bbox_size,
            "yaw_deg": self.yaw_deg,
            "optimized": self.optimized,
            "optimized_sha256": self.optimized_sha256,
            "optimized_triangles": self.optimized_triangles,
            "optimized_size_bytes": self.optimized_size_bytes,
            "optimize_ratio": self.optimize_ratio,
            "texture_target": self.texture_target,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssetRecord:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class AssetManifest:
    """The ordered collection of admitted assets, with a stable digest."""

    assets: list[AssetRecord] = field(default_factory=list)
    schema_version: int = MANIFEST_SCHEMA_VERSION

    def by_id(self, asset_id: str) -> AssetRecord:
        for a in self.assets:
            if a.asset_id == asset_id:
                return a
        raise KeyError(f"asset not in manifest: {asset_id}")

    def ids(self) -> list[str]:
        return [a.asset_id for a in self.assets]

    def digest(self) -> str:
        payload = json.dumps(
            [a.as_dict() for a in self.assets],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "asset_count": len(self.assets),
            "digest": self.digest(),
            "assets": [a.as_dict() for a in self.assets],
        }

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(self.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return p

    @classmethod
    def load(cls, path: str | Path) -> AssetManifest:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            assets=[AssetRecord.from_dict(a) for a in data.get("assets", [])],
            schema_version=int(data.get("schema_version", MANIFEST_SCHEMA_VERSION)),
        )


def build_record(
    asset_id: str,
    path: str | Path,
    *,
    source_pack: str,
    source_file: str,
    licence: str,
    attribution: str,
    kind: str = "prop",
    yaw_deg: float = 0.0,
    info: GlbInfo | None = None,
) -> AssetRecord:
    """Build an :class:`AssetRecord` by really measuring ``path``."""
    info = info or inspect_glb(path)
    return AssetRecord(
        asset_id=asset_id,
        kind=kind,
        source_pack=source_pack,
        source_file=source_file,
        licence=licence,
        attribution=attribution,
        sha256=sha256_file(path),
        size_bytes=info.byte_length,
        triangles=info.triangles,
        vertices=info.vertices,
        texture_count=info.texture_count,
        max_texture_dim=info.max_texture_dim,
        mesh_count=info.mesh_count,
        skin_count=info.skin_count,
        joint_count=info.joint_count,
        animations=[
            {
                "name": a.name,
                "channel_count": a.channel_count,
                "animated_channels": a.animated_channels,
                "duration_s": round(a.duration_s, 6),
            }
            for a in info.animations
        ],
        double_sided_count=info.double_sided_count,
        height_p90_fraction=(
            round(info.height_p90_fraction, 4)
            if info.height_p90_fraction is not None
            else None
        ),
        bbox_min=([round(v, 6) for v in info.bbox_min] if info.bbox_min else None),
        bbox_max=([round(v, 6) for v in info.bbox_max] if info.bbox_max else None),
        bbox_size=(
            [round(v, 6) for v in info.bbox_size] if info.bbox_size else None
        ),
        yaw_deg=yaw_deg,
    )
