"""Hevi MANGA unit — shared helpers.

Everything here is pure-Python, dependency-light, and deterministic.  The
unit renders 3D manga backgrounds and storyboards on CPU-only via Three.js
+ Playwright SwiftShader (see ``common/renderer.py``).  No paid APIs, no GPU.

This file is intentionally free of heavy imports so it can be unit-tested
without a browser.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Deterministic PRNG (mulberry32).  Same seed -> identical stream on any
# machine.  All manga randomness must flow through this so that "same seed
# reproduces byte-identical output" holds end-to-end.
# ---------------------------------------------------------------------------


def hash_seed(seed: str | int) -> int:
    """Map a string/int seed to a stable uint32 used by mulberry32."""
    if isinstance(seed, int):
        return seed & 0xFFFFFFFF
    b = hashlib.sha256(seed.encode("utf-8")).digest()
    return int.from_bytes(b[:4], "little")


class PRNG:
    """mulberry32 deterministic PRNG."""

    def __init__(self, seed: str | int) -> None:
        self.state = hash_seed(seed) | 0

    def next(self) -> float:
        a = self.state + 0x6D2B79F5
        a &= 0xFFFFFFFF
        self.state = a
        t = (a ^ (a >> 15)) & 0xFFFFFFFF
        t = (t + ((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF) & 0xFFFFFFFF
        t ^= t >> 14
        return (t & 0xFFFFFFFF) / 4294967296

    def range(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self.next()

    def int(self, lo: int, hi: int) -> int:
        return int(self.range(lo, hi + 1))

    def choose(self, items: list[Any]) -> Any:
        return items[int(self.next() * len(items)) % len(items)]


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def aspect_ratio_value(aspect: str) -> float:
    """Return width/height for a known aspect label."""
    mapping = {"B5": 0.707, "4:5": 0.8, "1:1": 1.0, "9:16": 0.5625, "16:9": 1.7778}
    if aspect in mapping:
        return mapping[aspect]
    a = aspect.replace(" ", "")
    parts = a.split(":")
    if len(parts) != 2:
        raise ValueError(f"bad aspect: {aspect!r}")
    return float(parts[0]) / float(parts[1])


@dataclass
class RenderSize:
    """Pixel dimensions for a given aspect + long-edge resolution."""

    width: int
    height: int

    @classmethod
    def for_aspect(cls, aspect: str, long_edge: int) -> "RenderSize":
        ratio = aspect_ratio_value(aspect)
        if ratio >= 1:
            w = long_edge
            h = int(round(long_edge / ratio))
        else:
            h = long_edge
            w = int(round(long_edge * ratio))
        return cls(width=w, height=h)


# ---------------------------------------------------------------------------
# Manifest the E2E / capability pipeline returns.
# ---------------------------------------------------------------------------


@dataclass
class ArtifactManifest:
    """What a render returns: paths + qa facts so callers can verify."""

    mp4: str | None = None
    png: str | None = None
    wav: str | None = None
    duration_s: float = 0.0
    fps: int = 30
    width: int = 0
    height: int = 0
    sha256: str = ""
    qa: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mp4": self.mp4,
            "png": self.png,
            "wav": self.wav,
            "duration_s": self.duration_s,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "sha256": self.sha256,
            "qa": self.qa,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ArtifactManifest":
        return cls(
            mp4=d.get("mp4"),
            png=d.get("png"),
            wav=d.get("wav"),
            duration_s=float(d.get("duration_s", 0.0)),
            fps=int(d.get("fps", 30)),
            width=int(d.get("width", 0)),
            height=int(d.get("height", 0)),
            sha256=d.get("sha256", ""),
            qa=d.get("qa", {}),
        )


def write_json(path: str | Path, obj: Any) -> None:
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
