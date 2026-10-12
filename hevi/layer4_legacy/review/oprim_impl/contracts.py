"""Value objects for the review primitives (no side effects)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: Ordered review stages (a stage that cannot run is reported, never skipped silently).
REVIEW_STAGES = ("probe", "frames", "audio", "subtitle", "slideshow")

#: Verdict vocabulary.  "blocked" is not a pass and not a defect.
VERDICT_OK = "ok"
VERDICT_WARN = "warn"
VERDICT_RED = "red"
VERDICT_BLOCKED = "blocked"


@dataclass(frozen=True)
class ProbeReport:
    """Real ffprobe result (never a guess)."""

    path: str
    kind: str = "unknown"
    width: int = 0
    height: int = 0
    duration_s: float = 0.0
    fps: float = 0.0
    has_audio: bool = False
    size_bytes: int = 0
    video_codec: str = ""
    audio_codec: str = ""
    nb_frames: int = 0
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FrameCheck:
    """One sampled frame's measured darkness / flatness / motion evidence."""

    index: int
    timestamp_s: float
    path: str = ""
    mean_luma: float = 0.0
    stdev_luma: float = 0.0
    is_black: bool = False
    is_flat: bool = False
    is_broken: bool = False
    # --- spatial quality (破图/花屏) ---
    gradient_x: float = 0.0
    gradient_y: float = 0.0
    edge_density_h: float = 0.0
    edge_density_v: float = 0.0
    local_diff: float = 0.0
    blockiness: float = 0.0
    is_noise: bool = False       # high-frequency noise dominates
    is_blocky: bool = False      # macroblock artefacts
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewVerdict:
    """Compose-gate outcome for one finished video."""

    path: str
    status: str = VERDICT_BLOCKED
    verdict: str = VERDICT_BLOCKED
    reasons: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def allows_compose(self) -> bool:
        """Only an actually-measured ok/warn may proceed (blocked/red never do)."""
        return self.status == "ok" and self.verdict in (VERDICT_OK, VERDICT_WARN)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["allows_compose"] = self.allows_compose
        return data


__all__ = [
    "REVIEW_STAGES",
    "VERDICT_BLOCKED",
    "VERDICT_OK",
    "VERDICT_RED",
    "VERDICT_WARN",
    "FrameCheck",
    "ProbeReport",
    "ReviewVerdict",
]
