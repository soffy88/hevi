"""Contracts and data schemas for comic narration.

3O Pillar: oprim.comicnarr_contracts
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


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


@dataclass(frozen=True)
class ComicStyle:
    """Visual and layout template for comic generation."""

    name: str
    style_tokens: str
    negative_prompt: str
    subtitle_style: str
    transition: str
    bgm_mood: str = "bright"

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "topic": self.topic,
            "character_desc_zh": self.character_desc_zh,
            "character_desc_en": self.character_desc_en,
            "scenes": [s.to_dict() for s in self.scenes],
        }


__all__ = [
    "ComicScene",
    "ComicScript",
    "ComicStyle",
]
