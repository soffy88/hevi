"""Video catcher input/output primitives; local paths and URLs stay explicit."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

QUALITY_LIMITS = {"best": None, "360p": 360, "480p": 480, "720p": 720, "1080p": 1080, "1440p": 1440, "2160p": 2160}


def is_url(value: str) -> bool:
    return value.startswith(("http://", "https://", "ftp://"))


@dataclass(frozen=True)
class VideoCatchRequest:
    source: str
    quality: str = "best"
    output_dir: str = "output/catcher"
    merge_audio: bool = True
    max_bytes: int = 1024 * 1024 * 1024
    timeout_s: int = 600
    playlist: bool = False

    def validate(self) -> list[str]:
        issues: list[str] = []
        if not self.source.strip():
            issues.append("source is required")
        if self.quality not in QUALITY_LIMITS:
            issues.append(f"unsupported quality: {self.quality}")
        if self.max_bytes <= 0:
            issues.append("max_bytes must be positive")
        if self.timeout_s <= 0:
            issues.append("timeout_s must be positive")
        if not is_url(self.source) and not Path(self.source).expanduser().is_file():
            issues.append(f"local source not found: {Path(self.source).expanduser()}")
        return issues

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VideoDiscovery:
    source: str
    source_type: str
    title: str = ""
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    formats: tuple[dict[str, Any], ...] = ()
    subtitle_languages: tuple[str, ...] = ()
    status: str = "discovered"
    errors: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["formats"] = [dict(item) for item in self.formats]
        body["subtitle_languages"] = list(self.subtitle_languages)
        return body


__all__ = ["QUALITY_LIMITS", "VideoCatchRequest", "VideoDiscovery", "is_url"]
