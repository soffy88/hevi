"""Capability render result.

Returned by every ``Capability.render`` call.  Carries the produced artefact
path(s), the actual realised duration, a sha256 fingerprint and an optional qa
report so callers can verify determinism and integrity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CapabilityResult:
    """Outcome of a capability render.

    ``mp4``/``png``/``wav`` are optional paths to the produced artefacts.  At
    least one should be present for a successful render.  ``sha256`` fingerprints
    the primary artefact; ``qa`` is a free-form quality/integrity report.
    """

    mp4: str | None = None
    png: str | None = None
    wav: str | None = None
    duration_s: float = 0.0
    sha256: str = ""
    qa: dict = field(default_factory=dict)

    def primary_path(self) -> Path:
        for p in (self.mp4, self.png, self.wav):
            if p:
                return Path(p)
        raise ValueError("CapabilityResult has no artefact path")

    def as_dict(self) -> dict:
        return {
            "mp4": self.mp4,
            "png": self.png,
            "wav": self.wav,
            "duration_s": self.duration_s,
            "sha256": self.sha256,
            "qa": self.qa,
        }


__all__ = ["CapabilityResult"]
