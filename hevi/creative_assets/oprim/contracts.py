"""Stable visual asset primitives.  Plans never imply that an image exists."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PLATFORMS = ("generic", "douyin", "kuaishou", "xiaohongshu", "bilibili", "youtube")
ASPECT_RATIOS = ("16:9", "9:16", "1:1", "4:5", "3:4", "4:3")
ASSET_KINDS = ("cover", "avatar", "thumbnail", "character_card", "scene_reference")


@dataclass(frozen=True)
class VisualAssetRequest:
    kind: str
    subject: str
    platform: str = "generic"
    aspect_ratio: str | None = None
    style: str = "cinematic"
    reference_path: str | None = None
    prompt_only: bool = False
    negative_prompt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        issues: list[str] = []
        if self.kind not in ASSET_KINDS:
            issues.append(f"unsupported asset kind: {self.kind}")
        if not self.subject.strip():
            issues.append("subject is required")
        if self.platform not in PLATFORMS:
            issues.append(f"unsupported platform: {self.platform}")
        if self.aspect_ratio is not None and self.aspect_ratio not in ASPECT_RATIOS:
            issues.append(f"unsupported aspect ratio: {self.aspect_ratio}")
        if self.reference_path:
            issues.extend(validate_local_reference(self.reference_path))
        return issues

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VisualAssetPlan:
    request: VisualAssetRequest
    prompt: str
    size: str
    status: str = "planned"
    errors: tuple[str, ...] = ()
    output_path: str | None = None
    provider: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "prompt": self.prompt,
            "size": self.size,
            "status": self.status,
            "errors": list(self.errors),
            "output_path": self.output_path,
            "provider": self.provider,
        }


def validate_local_reference(path: str | Path) -> list[str]:
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        return [f"reference file not found: {candidate}"]
    return []


__all__ = [
    "ASPECT_RATIOS",
    "ASSET_KINDS",
    "PLATFORMS",
    "VisualAssetPlan",
    "VisualAssetRequest",
    "validate_local_reference",
]
