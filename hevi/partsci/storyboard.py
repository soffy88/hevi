"""Storyboard script with approval status and per-shot source provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PartsciShot:
    shot_index: int
    duration: float
    concept: str
    keyword: str  # ≤ 4 chars for kids
    narration: str
    mechanism: str
    theme: str = "sky"
    approved: bool = False
    source_provenance: dict[str, Any] = field(default_factory=lambda: {
        "kind": "vector_self_drawn",
        "license": "CC0-dedicated",
        "url": None
    })

    def validate(self) -> None:
        if not self.approved:
            raise RuntimeError(f"Shot {self.shot_index} is NOT approved. Unapproved shots cannot be rendered per SAFETY contract.")
        if len(self.keyword) > 4:
            raise ValueError(f"Kids keyword {self.keyword!r} exceeds length 4 (got {len(self.keyword)})")
        if self.duration < 2.5:
            raise ValueError(f"Shot duration {self.duration}s < 2.5s violates kids safety gate (min shot duration)")


@dataclass
class PartsciStoryboard:
    title: str
    concept_key: str
    aspect: str  # "16:9" or "9:16"
    shots: list[PartsciShot] = field(default_factory=list)
    approved: bool = False

    def validate_all(self) -> None:
        if not self.approved:
            raise RuntimeError(f"Storyboard {self.title!r} is not approved. Approval required before production.")
        for s in self.shots:
            s.validate()


__all__ = ["PartsciShot", "PartsciStoryboard"]
