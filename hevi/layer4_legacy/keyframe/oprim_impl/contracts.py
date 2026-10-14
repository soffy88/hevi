"""Keyframe engine contracts and abstract base class.

3O Pillar: oprim.keyframe_contracts
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class KeyframeResult:
    """Outcome of generating a single keyframe."""

    path: Path
    seed: int
    engine: str
    model: str
    sec: float
    rss_mb: float
    width: int = 512
    height: int = 512
    steps: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "seed": self.seed,
            "engine": self.engine,
            "model": self.model,
            "sec": round(self.sec, 3),
            "rss_mb": round(self.rss_mb, 1),
            "width": self.width,
            "height": self.height,
            "steps": self.steps,
        }


class KeyframeEngine(ABC):
    """Abstract interface for local/cloud keyframe generation engines."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Engine identifier (e.g. 'sdturbo_cpu', 'fake', 'cloud_stub')."""

    @abstractmethod
    def available(self) -> bool:
        """Whether this engine is available on the current machine/environment."""

    @property
    @abstractmethod
    def max_resident_mb(self) -> float:
        """Estimated peak resident memory in megabytes."""

    @abstractmethod
    def generate(
        self,
        prompt_en: str,
        *,
        negative: str | None = None,
        width: int = 512,
        height: int = 512,
        steps: int = 2,
        seed: int | None = None,
        ref_image: Path | None = None,
        output_path: Path | None = None,
    ) -> KeyframeResult:
        """Generate a single keyframe image.

        Args:
            prompt_en: English diffusion prompt.
            negative: Optional negative prompt.
            width: Output width (default 512).
            height: Output height (default 512).
            steps: Diffusion inference steps (default 2 for turbo).
            seed: RNG seed for reproducible generation.
            ref_image: Optional reference image (for IP-Adapter / conditioning).
            output_path: Optional explicit file path to write image.
        """
