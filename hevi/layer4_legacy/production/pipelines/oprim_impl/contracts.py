"""OpenMontage-shaped pipeline contracts with HEVI-owned execution stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PipelineSpec:
    pipeline_id: str
    name: str
    description: str
    stages: tuple[str, ...]
    roles: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    source_repos: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        for key in ("stages", "roles", "required_capabilities", "source_repos"):
            body[key] = list(body[key])
        return body


@dataclass(frozen=True)
class PipelineRequest:
    pipeline_id: str
    brief: str
    aspect_ratio: str = "9:16"
    images: tuple[str, ...] = ()
    videos: tuple[str, ...] = ()
    audios: tuple[str, ...] = ()
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["images"] = list(self.images)
        body["videos"] = list(self.videos)
        body["audios"] = list(self.audios)
        return body


__all__ = ["PipelineRequest", "PipelineSpec"]
