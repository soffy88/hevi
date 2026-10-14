"""Value objects shared by the enhancement primitives (no side effects)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: Known enhancement operations.
ENHANCE_OPS = ("matte", "upscale", "face_restore", "lut")

#: Weight licence markers surfaced to callers / review artefacts.
LICENSE_COMMERCIAL_OK = "commercial-ok"
LICENSE_NONCOMMERCIAL_ONLY = "noncommercial-research-only"


@dataclass(frozen=True)
class MediaInfo:
    """Result of a real ffprobe probe (never guessed)."""

    path: str
    kind: str  # "video" | "audio" | "image" | "unknown"
    width: int = 0
    height: int = 0
    duration_s: float = 0.0
    fps: float = 0.0
    has_audio: bool = False
    size_bytes: int = 0
    codec: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EnhanceResult:
    """One enhancement operation's honest ledger entry.

    ``commercial_ok`` is False whenever a non-commercial-only weight was used
    (GFPGAN).  ``metrics`` carries the measured numbers, never a bare claim.
    """

    op: str
    input_path: str
    output_path: str
    backend: str
    model: str = ""
    license: str = LICENSE_COMMERCIAL_OK
    commercial_ok: bool = True
    metrics: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def enhance_result_to_dict(result: EnhanceResult) -> dict[str, Any]:
    return result.to_dict()


__all__ = [
    "ENHANCE_OPS",
    "LICENSE_COMMERCIAL_OK",
    "LICENSE_NONCOMMERCIAL_ONLY",
    "EnhanceResult",
    "MediaInfo",
    "enhance_result_to_dict",
]
