"""Idea2Video / Novel2Video / AutoCameo 的 obase 契约。

3O 归属(待上游): `obase.vimax_adapter_schemas`。阈值与路由不进本文件。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from hevi.script2video.schemas import KernelCharacter, KernelPlan, PortraitRegistry

SourceKind = Literal["idea", "script", "novel", "cameo"]
CameoRole = Literal["protagonist", "supporting", "cameo", "narrator"]


@dataclass
class LengthBudget:
    max_scenes: int = 1
    max_shots_per_scene: int = 5
    max_events: int = 50
    max_scenes_per_event: int = 5


@dataclass
class IdeaStory:
    title: str
    audience: str
    genre: str
    outline: str
    body: str
    scene_headings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "audience": self.audience,
            "genre": self.genre,
            "outline": self.outline,
            "body": self.body,
            "scene_headings": list(self.scene_headings),
        }


@dataclass
class SceneScript:
    idx: int
    slugline: str
    environment: str
    script: str
    characters: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "idx": self.idx,
            "slugline": self.slugline,
            "environment": self.environment,
            "script": self.script,
            "characters": list(self.characters),
        }


@dataclass
class IdeaPlan:
    story: IdeaStory
    characters: list[KernelCharacter]
    scenes: list[SceneScript]
    scene_kernels: list[KernelPlan] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "story": self.story.to_dict(),
            "characters": [
                {
                    "name": char.name,
                    "identifier": char.identifier,
                    "description": char.description,
                    "reference_photo": char.reference_photo,
                    "is_visible": char.is_visible,
                }
                for char in self.characters
            ],
            "scenes": [scene.to_dict() for scene in self.scenes],
            "scene_kernels": [kernel.to_dict() for kernel in self.scene_kernels],
        }


@dataclass
class NovelEvent:
    index: int
    description: str
    process_chain: list[str]
    is_last: bool = False
    characters: list[str] = field(default_factory=list)
    location: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "description": self.description,
            "process_chain": list(self.process_chain),
            "is_last": self.is_last,
            "characters": list(self.characters),
            "location": self.location,
        }


@dataclass
class NovelScene:
    event_index: int
    idx: int
    is_last: bool
    slugline: str
    script: str
    characters: list[KernelCharacter] = field(default_factory=list)
    relevant_chunks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_index": self.event_index,
            "idx": self.idx,
            "is_last": self.is_last,
            "slugline": self.slugline,
            "script": self.script,
            "characters": [char.identifier for char in self.characters],
        }


@dataclass
class NovelCharacterBook:
    """小说级角色账本:identifier → 出现过的 event/scene。"""

    identifier: str
    name: str
    static_features: str
    active_events: dict[int, str] = field(default_factory=dict)
    active_scenes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "name": self.name,
            "static_features": self.static_features,
            "active_events": {str(k): v for k, v in self.active_events.items()},
            "active_scenes": dict(self.active_scenes),
        }


@dataclass
class NovelPlan:
    original_chars: int
    compressed: str
    compression_ratio: float
    events: list[NovelEvent]
    scenes: list[NovelScene]
    book: list[NovelCharacterBook]
    scene_kernels: list[KernelPlan] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_chars": self.original_chars,
            "compressed": self.compressed,
            "compression_ratio": self.compression_ratio,
            "events": [event.to_dict() for event in self.events],
            "scenes": [scene.to_dict() for scene in self.scenes],
            "book": [item.to_dict() for item in self.book],
            "scene_kernels": [kernel.to_dict() for kernel in self.scene_kernels],
        }


@dataclass
class PersonInfo:
    name: str
    description: str
    age_estimate: str = ""
    gender: str = ""
    features: list[str] = field(default_factory=list)
    clothing: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "age_estimate": self.age_estimate,
            "gender": self.gender,
            "features": list(self.features),
            "clothing": self.clothing,
        }


@dataclass
class CameoCharacter:
    character_id: str
    person_info: PersonInfo
    reference_photo: Path
    role_in_story: CameoRole = "cameo"
    registry: PortraitRegistry | None = None

    def to_kernel_character(self) -> KernelCharacter:
        return KernelCharacter(
            name=self.person_info.name,
            identifier=self.character_id,
            description=self.person_info.description,
            reference_photo=str(self.reference_photo),
            is_visible=self.role_in_story != "narrator",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_id": self.character_id,
            "person_info": self.person_info.to_dict(),
            "reference_photo": str(self.reference_photo),
            "role_in_story": self.role_in_story,
        }


@dataclass
class CameoPlan:
    characters: list[CameoCharacter]
    integration_notes: str = ""
    merged_characters: list[KernelCharacter] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "characters": [item.to_dict() for item in self.characters],
            "integration_notes": self.integration_notes,
            "merged_characters": [char.identifier for char in self.merged_characters],
        }
