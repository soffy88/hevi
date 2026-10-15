"""Pure-Python GLB inspector (no engine, no Blender, no gltf-transform needed).

Implements the parts of the glTF 2.0 spec that the SCENE3D asset pipeline needs to
make an *evidence-based* admission decision, following the handbook's rule that
"所有面数都自己读过" (§04/§05) and that a converter's own readout must never be
the only evidence (§17):

* triangle / vertex counts straight from the index + POSITION accessors;
* per-image pixel dimensions read from the PNG / JPEG file headers;
* the POSITION bounding box (accessor ``min``/``max``);
* skin joint counts and animation clip inventory (name, channels, duration);
* vertex height distribution (p90) used to detect a bbox stretched by a thin
  pole / antenna / umbrella (§17 "包围盒一样，几何不一样");
* ``doubleSided`` / material inventory, and the ``extensionsUsed`` list so a
  ``_meshopt`` / quantization variant is *detected* rather than silently
  mis-parsed (§04 Appendix B).

Everything here reads bytes only.  A malformed file raises :class:`GlbError`
instead of returning a plausible-looking wrong number.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "GlbError",
    "Accessor",
    "ImageInfo",
    "AnimationInfo",
    "GlbInfo",
    "inspect_glb",
    "parse_glb",
]

# glTF componentType -> (struct code, byte size, is_float, is_signed)
_COMPONENT_TYPES: dict[int, tuple[str, int, bool, bool]] = {
    5120: ("b", 1, False, True),   # BYTE
    5121: ("B", 1, False, False),  # UNSIGNED_BYTE
    5122: ("h", 2, False, True),   # SHORT
    5123: ("H", 2, False, False),  # UNSIGNED_SHORT
    5125: ("I", 4, False, False),  # UNSIGNED_INT
    5126: ("f", 4, True, True),    # FLOAT
}

_TYPE_COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}


class GlbError(ValueError):
    """A GLB that cannot be parsed as spec-conformant glTF 2.0."""


@dataclass(frozen=True)
class Accessor:
    """A resolved accessor: its values plus the spec metadata we care about."""

    values: tuple[tuple[float, ...], ...]
    component_type: int
    type: str
    count: int
    normalized: bool
    minimum: tuple[float, ...] | None
    maximum: tuple[float, ...] | None


@dataclass(frozen=True)
class ImageInfo:
    """One embedded texture image."""

    name: str
    mime_type: str
    byte_length: int
    width: int | None
    height: int | None


@dataclass(frozen=True)
class AnimationInfo:
    """One animation clip."""

    name: str
    channel_count: int
    sampler_count: int
    duration_s: float
    # Channels whose sampler output has more than one keyframe (i.e. actually
    # move).  The handbook's 123-channels-but-16-real reading (§06).
    animated_channels: int


@dataclass
class GlbInfo:
    """Everything the pipeline needs to know about one GLB file."""

    path: str
    byte_length: int
    triangles: int
    vertices: int
    mesh_count: int
    primitive_count: int
    material_count: int
    double_sided_count: int
    images: list[ImageInfo] = field(default_factory=list)
    animations: list[AnimationInfo] = field(default_factory=list)
    skin_count: int = 0
    joint_count: int = 0
    extensions_used: list[str] = field(default_factory=list)
    bbox_min: tuple[float, float, float] | None = None
    bbox_max: tuple[float, float, float] | None = None
    height_p90_fraction: float | None = None
    quantization: bool = False
    meshopt: bool = False

    @property
    def texture_count(self) -> int:
        return len(self.images)

    @property
    def max_texture_dim(self) -> int:
        dims = [max(i.width or 0, i.height or 0) for i in self.images]
        return max(dims) if dims else 0

    @property
    def texture_bytes(self) -> int:
        return sum(i.byte_length for i in self.images)

    @property
    def size_mib(self) -> float:
        return self.byte_length / (1024 * 1024)

    @property
    def bbox_size(self) -> tuple[float, float, float] | None:
        if self.bbox_min is None or self.bbox_max is None:
            return None
        return tuple(self.bbox_max[i] - self.bbox_min[i] for i in range(3))  # type: ignore[return-value]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "byte_length": self.byte_length,
            "size_mib": round(self.size_mib, 4),
            "triangles": self.triangles,
            "vertices": self.vertices,
            "mesh_count": self.mesh_count,
            "primitive_count": self.primitive_count,
            "material_count": self.material_count,
            "double_sided_count": self.double_sided_count,
            "textures": [
                {
                    "name": i.name,
                    "mime_type": i.mime_type,
                    "byte_length": i.byte_length,
                    "width": i.width,
                    "height": i.height,
                }
                for i in self.images
            ],
            "texture_count": self.texture_count,
            "max_texture_dim": self.max_texture_dim,
            "texture_bytes": self.texture_bytes,
            "animations": [
                {
                    "name": a.name,
                    "channel_count": a.channel_count,
                    "sampler_count": a.sampler_count,
                    "animated_channels": a.animated_channels,
                    "duration_s": round(a.duration_s, 6),
                }
                for a in self.animations
            ],
            "skin_count": self.skin_count,
            "joint_count": self.joint_count,
            "extensions_used": list(self.extensions_used),
            "quantization": self.quantization,
            "meshopt": self.meshopt,
            "bbox_min": list(self.bbox_min) if self.bbox_min else None,
            "bbox_max": list(self.bbox_max) if self.bbox_max else None,
            "bbox_size": list(self.bbox_size) if self.bbox_size else None,
            "height_p90_fraction": (
                round(self.height_p90_fraction, 4) if self.height_p90_fraction is not None else None
            ),
        }


# --------------------------------------------------------------------------- #
# Container
# --------------------------------------------------------------------------- #
def parse_glb(path: str | Path) -> tuple[dict[str, Any], bytes]:
    """Split a GLB into (glTF JSON dict, BIN chunk bytes).

    Raises :class:`GlbError` on a bad magic, a truncated header, or a missing
    JSON chunk — never returns a partially-parsed document.
    """
    raw = Path(path).read_bytes()
    if len(raw) < 12:
        raise GlbError(f"{path}: file shorter than a GLB header ({len(raw)} bytes)")
    magic, version, _length = struct.unpack_from("<4sII", raw, 0)
    if magic != b"glTF":
        raise GlbError(f"{path}: bad magic {magic!r} (not a GLB)")
    if version != 2:
        raise GlbError(f"{path}: unsupported GLB version {version}")
    gltf: dict[str, Any] | None = None
    bin_chunk = b""
    offset = 12
    while offset + 8 <= len(raw):
        chunk_len, chunk_type = struct.unpack_from("<II", raw, offset)
        start = offset + 8
        end = start + chunk_len
        if end > len(raw):
            raise GlbError(f"{path}: chunk overruns file ({end} > {len(raw)})")
        chunk = raw[start:end]
        if chunk_type == 0x4E4F534A:  # 'JSON'
            try:
                gltf = json.loads(chunk.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise GlbError(f"{path}: JSON chunk not parseable: {exc}") from exc
        elif chunk_type == 0x004E4942:  # 'BIN'
            bin_chunk = chunk
        offset = end
    if gltf is None:
        raise GlbError(f"{path}: no JSON chunk")
    return gltf, bin_chunk


# --------------------------------------------------------------------------- #
# Accessors
# --------------------------------------------------------------------------- #
def _read_accessor(gltf: dict[str, Any], bin_chunk: bytes, index: int) -> Accessor:
    try:
        acc = gltf["accessors"][index]
    except (KeyError, IndexError) as exc:
        raise GlbError(f"accessor {index} missing") from exc
    component_type = acc["componentType"]
    if component_type not in _COMPONENT_TYPES:
        raise GlbError(f"accessor {index}: unknown componentType {component_type}")
    code, size, _is_float, _signed = _COMPONENT_TYPES[component_type]
    n_comp = _TYPE_COUNTS.get(acc["type"])
    if n_comp is None:
        raise GlbError(f"accessor {index}: unknown type {acc['type']}")
    count = int(acc["count"])
    normalized = bool(acc.get("normalized", False))
    minimum = tuple(float(v) for v in acc["min"]) if "min" in acc else None
    maximum = tuple(float(v) for v in acc["max"]) if "max" in acc else None

    values: list[tuple[float, ...]] = []
    if "bufferView" in acc and bin_chunk:
        bv = gltf["bufferViews"][acc["bufferView"]]
        base = int(bv.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
        stride = int(bv.get("byteStride") or size * n_comp)
        for k in range(count):
            start = base + k * stride
            if start + size * n_comp > len(bin_chunk):
                raise GlbError(f"accessor {index}: element {k} overruns BIN chunk")
            row = struct.unpack_from("<" + code * n_comp, bin_chunk, start)
            if normalized and component_type != 5126:
                row = tuple(_normalize_component(v, component_type) for v in row)
            values.append(row)
    return Accessor(
        values=tuple(values),
        component_type=component_type,
        type=acc["type"],
        count=count,
        normalized=normalized,
        minimum=minimum,
        maximum=maximum,
    )


def _normalize_component(v: float, component_type: int) -> float:
    """Normalize one integer component per the glTF spec's ``normalized`` rule.

    A ``KHR_mesh_quantization`` file stores positions as normalized int16; a
    parser that ignores the flag reads the raw integer as a world coordinate and
    reports a 1.0 m model as 32767 m (§04 Appendix B).
    """
    if component_type == 5120:  # BYTE
        return max(float(v) / 127.0, -1.0)
    if component_type == 5122:  # SHORT
        return max(float(v) / 32767.0, -1.0)
    if component_type == 5121:  # UNSIGNED_BYTE
        return float(v) / 255.0
    if component_type == 5123:  # UNSIGNED_SHORT
        return float(v) / 65535.0
    return float(v)


def _read_scalar_floats(gltf: dict[str, Any], bin_chunk: bytes, index: int) -> list[float]:
    """Read a SCALAR accessor as floats (normalization already applied)."""
    acc = _read_accessor(gltf, bin_chunk, index)
    return [float(row[0]) for row in acc.values]


def _image_dimensions(blob: bytes) -> tuple[int | None, int | None]:
    """PNG / JPEG pixel dimensions from the file header (no decoder)."""
    if blob[:8] == b"\x89PNG\r\n\x1a\n" and len(blob) >= 24:
        w, h = struct.unpack(">II", blob[16:24])
        return int(w), int(h)
    if blob[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(blob):
            if blob[i] != 0xFF:
                i += 1
                continue
            marker = blob[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", blob[i + 5 : i + 9])
                return int(w), int(h)
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg_len = struct.unpack(">H", blob[i + 2 : i + 4])[0]
            i += 2 + seg_len
    return None, None


# --------------------------------------------------------------------------- #
# Inspector
# --------------------------------------------------------------------------- #
def inspect_glb(path: str | Path) -> GlbInfo:
    """Read every admission-relevant fact out of one GLB."""
    p = Path(path)
    gltf, bin_chunk = parse_glb(p)

    meshes = gltf.get("meshes", [])
    triangles = 0
    vertices = 0
    primitive_count = 0
    for mesh in meshes:
        for prim in mesh.get("primitives", []):
            primitive_count += 1
            attrs = prim.get("attributes", {})
            if "POSITION" in attrs:
                vertices += int(gltf["accessors"][attrs["POSITION"]]["count"])
            if "indices" in prim:
                triangles += int(gltf["accessors"][prim["indices"]]["count"]) // 3
            elif prim.get("mode", 4) == 4 and "POSITION" in attrs:
                triangles += int(gltf["accessors"][attrs["POSITION"]]["count"]) // 3

    materials = gltf.get("materials", [])
    double_sided = sum(1 for m in materials if m.get("doubleSided"))

    images: list[ImageInfo] = []
    for idx, img in enumerate(gltf.get("images", [])):
        blob = b""
        if "bufferView" in img and bin_chunk:
            bv = gltf["bufferViews"][img["bufferView"]]
            off = int(bv.get("byteOffset", 0))
            blob = bin_chunk[off : off + int(bv["byteLength"])]
        w, h = _image_dimensions(blob)
        images.append(
            ImageInfo(
                name=str(img.get("name", f"image_{idx}")),
                mime_type=str(img.get("mimeType", "")),
                byte_length=len(blob),
                width=w,
                height=h,
            )
        )

    animations: list[AnimationInfo] = []
    for idx, anim in enumerate(gltf.get("animations", [])):
        samplers = anim.get("samplers", [])
        duration = 0.0
        animated = 0
        for s in samplers:
            times = _read_scalar_floats(gltf, bin_chunk, s["input"])
            if times:
                duration = max(duration, max(times))
            # A sampler is "animated" when its output actually varies.  Tripo's
            # retarget clips ship 107 constant channels with two identical
            # keyframes alongside the ~16 that move (§06), so counting
            # keyframes alone would over-report.
            out_acc = _read_accessor(gltf, bin_chunk, s["output"])
            if out_acc.count > 1 and len(set(out_acc.values)) > 1:
                animated += 1
        animations.append(
            AnimationInfo(
                name=str(anim.get("name", f"anim_{idx}")),
                channel_count=len(anim.get("channels", [])),
                sampler_count=len(samplers),
                duration_s=duration,
                animated_channels=animated,
            )
        )

    skins = gltf.get("skins", [])
    joint_count = max((len(s.get("joints", [])) for s in skins), default=0)

    extensions = list(gltf.get("extensionsUsed", []))
    quantization = "KHR_mesh_quantization" in extensions
    meshopt = "EXT_meshopt_compression" in extensions or any(
        "EXT_meshopt_compression" in bv.get("extensions", {})
        for bv in gltf.get("bufferViews", [])
    )

    # Bounding box + height distribution from POSITION accessors.  When an
    # accessor carries spec min/max we trust it; otherwise we compute it.
    bbox_min: list[float] | None = None
    bbox_max: list[float] | None = None
    heights: list[float] = []
    for mesh in meshes:
        for prim in mesh.get("primitives", []):
            attrs = prim.get("attributes", {})
            if "POSITION" not in attrs:
                continue
            acc = _read_accessor(gltf, bin_chunk, attrs["POSITION"])
            if acc.minimum and acc.maximum and not quantization:
                lo, hi = list(acc.minimum), list(acc.maximum)
            elif acc.values:
                lo = [min(v[i] for v in acc.values) for i in range(3)]
                hi = [max(v[i] for v in acc.values) for i in range(3)]
            else:
                continue
            bbox_min = lo if bbox_min is None else [min(bbox_min[i], lo[i]) for i in range(3)]
            bbox_max = hi if bbox_max is None else [max(bbox_max[i], hi[i]) for i in range(3)]
            if acc.values:
                heights.extend(v[1] for v in acc.values)

    p90 = None
    if heights and bbox_min is not None and bbox_max is not None:
        span = bbox_max[1] - bbox_min[1]
        if span > 1e-9:
            ordered = sorted(heights)
            idx = min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))
            p90 = (ordered[idx] - bbox_min[1]) / span

    return GlbInfo(
        path=str(p),
        byte_length=p.stat().st_size,
        triangles=triangles,
        vertices=vertices,
        mesh_count=len(meshes),
        primitive_count=primitive_count,
        material_count=len(materials),
        double_sided_count=double_sided,
        images=images,
        animations=animations,
        skin_count=len(skins),
        joint_count=joint_count,
        extensions_used=extensions,
        bbox_min=tuple(bbox_min) if bbox_min else None,  # type: ignore[arg-type]
        bbox_max=tuple(bbox_max) if bbox_max else None,  # type: ignore[arg-type]
        height_p90_fraction=p90,
        quantization=quantization,
        meshopt=meshopt,
    )
