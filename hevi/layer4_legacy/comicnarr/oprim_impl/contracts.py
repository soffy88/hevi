"""Contracts and data schemas for comic narration.

3O Pillar: oprim.comicnarr_contracts
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# ComicStyle is the shared keyframe-layer style preset (single source of truth
# shared with dramakey).  Re-exported under the historical name for backward
# compatibility with existing comicnarr call sites.
from hevi.layer4_legacy.keyframe.oprim_impl.style_presets import (
    StylePreset as ComicStyle,
)


@dataclass
class ComicScene:
    """A single narration sentence and corresponding comic panel."""

    index: int
    narration: str
    visual_desc: str
    prompt_en: str
    negative_prompt: str
    seed: int
    duration_s: float = 3.5
    image_path: str | None = None
    audio_path: str | None = None
    clip_path: str | None = None
    clip_score: float = 0.0
    rejected_seed: int | None = None
    rejected_image_path: str | None = None
    rejected_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ComicScript:
    """The complete comic narration script."""

    title: str
    topic: str
    character_desc_zh: str
    character_desc_en: str
    scenes: list[ComicScene] = field(default_factory=list)
    character_tokens: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "topic": self.topic,
            "character_desc_zh": self.character_desc_zh,
            "character_desc_en": self.character_desc_en,
            "character_tokens": list(self.character_tokens),
            "scenes": [s.to_dict() for s in self.scenes],
        }


__all__ = [
    "ComicScene",
    "ComicScript",
    "ComicStyle",
]
