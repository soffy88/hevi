"""Provider abstraction for ai_drama video segments."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class VideoRequest:
    prompt: str
    output_path: Path
    duration_s: float
    aspect: str = "9:16"
    mode: str = "reference"  # reference | first_last | digital_human | t2v
    seed: int = 42
    reference_images: list[str] = field(default_factory=list)
    reference_audio: list[str] = field(default_factory=list)
    first_frame: str | None = None
    last_frame: str | None = None
    image: str | None = None          # offline still plate
    audio: str | None = None          # offline dialogue track
    lipsync_portrait: str | None = None
    lipsync: bool = False
    sound_description: str = ""
    shot_id: str = ""
    episode_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoResult:
    path: Path
    provider: str
    duration_s: float
    meta: dict[str, Any] = field(default_factory=dict)


class VideoProvider(Protocol):
    name: str

    def available(self) -> tuple[bool, str]:
        """Return (available, reason).  Never raises."""
        ...

    def render(self, req: VideoRequest) -> VideoResult:
        ...
