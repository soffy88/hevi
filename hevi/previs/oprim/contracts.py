"""Scene-block primitives used by a web 3D previs client."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CastItem:
    cast_id: str
    label: str
    asset_path: str | None = None
    pose: str = "neutral"


@dataclass(frozen=True)
class CameraCue:
    cue_id: str
    time_s: float
    shot_size: str = "medium"
    movement: str = "static"
    azimuth_deg: float = 0.0
    elevation_deg: float = 18.0


@dataclass(frozen=True)
class TimelineCue:
    cue_id: str
    start_s: float
    end_s: float
    prompt: str


@dataclass(frozen=True)
class PrevisScene:
    scene_id: str
    title: str
    cast: tuple[CastItem, ...] = ()
    cameras: tuple[CameraCue, ...] = ()
    timeline: tuple[TimelineCue, ...] = ()
    environment_prompt: str = ""
    reference_image: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.scene_id.strip() or not self.title.strip():
            errors.append("scene_id and title are required")
        if not self.cameras:
            errors.append("at least one camera cue is required")
        errors.extend(
            f"timeline cue has invalid range: {cue.cue_id}"
            for cue in self.timeline
            if cue.end_s <= cue.start_s
        )
        errors.extend(
            f"camera cue time must be >= 0: {cue.cue_id}"
            for cue in self.cameras
            if cue.time_s < 0
        )
        return errors

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["cast"] = [asdict(item) for item in self.cast]
        body["cameras"] = [asdict(item) for item in self.cameras]
        body["timeline"] = [asdict(item) for item in self.timeline]
        return body


__all__ = ["CameraCue", "CastItem", "PrevisScene", "TimelineCue"]
