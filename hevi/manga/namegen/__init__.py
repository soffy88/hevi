"""M1 分镜生成器 (namegen) — data model.

Clean-room, public-page-only re-implementation of comicalizer-style features:
panel layout, camera, character poses, dialogue bubbles, effect lines, and a
180-degree axis diagnostic overlay.  No code is copied from any upstream repo;
only the *feature set* described in the task is reproduced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Page aspect presets.  Value is width / height.
ASPECTS: dict[str, float] = {
    "B5": 0.707,      # B5 paper portrait proportion (width/height ~ 1/1.414 = 0.707)
    "4:5": 0.8,       # portrait 4:5
    "1:1": 1.0,
    "9:16": 0.5625,   # portrait 9:16
    "16:9": 1.7778,
}

POSES = ("idle", "walk", "run", "wave", "sit", "point")
SHOT_SIZES = ("establishing", "wide", "medium", "close", "extreme")
PITCHES = ("high", "eye", "low")
TILTS = ("none", "left", "right")
EMOTIONS = ("neutral", "shout", "sad", "happy", "think", "whisper")
BG_KINDS = ("roomgacha", "locscout", "none")


class ReadingDir(str, Enum):
    RIGHT_TO_LEFT = "rtl"
    LEFT_TO_RIGHT = "ltr"


@dataclass
class Beat:
    """One story beat (maps to one panel)."""

    speaker: str | None           # character name, or None for narration/caption
    text: str                     # original script sentence (kept verbatim)
    emotion: str = "neutral"      # drives bubble shape
    action: str = ""              # stage direction (not drawn as text)
    pose: str = "idle"            # character pose
    shot: str = "medium"          # shot size
    bg_kind: str = "none"         # roomgacha | locscout | none
    bg_ref: str | None = None     # plate key / path reference
    camera_side: float = 0.0      # signed value used by the 180-degree gate


@dataclass
class Panel:
    index: int
    x: int
    y: int
    w: int
    h: int
    beat: Beat
    camera: dict[str, Any] = field(default_factory=dict)
    characters: list[dict[str, Any]] = field(default_factory=list)
    dialogue: dict[str, Any] | None = None
    effects: list[str] = field(default_factory=list)
    read_order: int = 0


@dataclass
class Storyboard:
    aspect: str
    reading_direction: str
    seed: str
    variation: float
    page_w: int
    page_h: int
    panels: list[Panel]
    axis_violations: list[dict[str, Any]] = field(default_factory=list)
    to_dict: Any = None  # filled by generator

    def model(self) -> dict[str, Any]:
        return {
            "aspect": self.aspect,
            "reading_direction": self.reading_direction,
            "seed": self.seed,
            "variation": self.variation,
            "page": {"w": self.page_w, "h": self.page_h},
            "panels": [
                {
                    "index": p.index,
                    "rect": {"x": p.x, "y": p.y, "w": p.w, "h": p.h},
                    "read_order": p.read_order,
                    "beat": {
                        "speaker": p.beat.speaker,
                        "text": p.beat.text,
                        "emotion": p.beat.emotion,
                        "action": p.beat.action,
                        "pose": p.beat.pose,
                        "shot": p.beat.shot,
                        "bg_kind": p.beat.bg_kind,
                        "bg_ref": p.beat.bg_ref,
                        "camera_side": p.beat.camera_side,
                    },
                    "camera": p.camera,
                    "characters": p.characters,
                    "dialogue": p.dialogue,
                    "effects": p.effects,
                }
                for p in self.panels
            ],
            "axis_violations": self.axis_violations,
        }


@dataclass
class Script:
    """Parsed input story. Text-only; never stores generated pixels."""

    title: str
    characters: list[str]
    beats: list[Beat]

    @classmethod
    def from_lines(cls, title: str, characters: list[str], lines: list[dict[str, Any]]) -> "Script":
        beats: list[Beat] = []
        for ln in lines:
            beats.append(
                Beat(
                    speaker=ln.get("speaker"),
                    text=str(ln.get("text", "")),
                    emotion=ln.get("emotion", "neutral"),
                    action=ln.get("action", ""),
                    pose=ln.get("pose", "idle"),
                    shot=ln.get("shot", "medium"),
                    bg_kind=ln.get("bg_kind", "none"),
                    bg_ref=ln.get("bg_ref"),
                    camera_side=float(ln.get("camera_side", 0.0)),
                )
            )
        return cls(title=title, characters=characters, beats=beats)


from .generator import generate  # noqa: E402

__all__ = [
    "ASPECTS",
    "POSES",
    "SHOT_SIZES",
    "PITCHES",
    "TILTS",
    "EMOTIONS",
    "BG_KINDS",
    "ReadingDir",
    "Beat",
    "Panel",
    "Storyboard",
    "Script",
    "generate",
]
