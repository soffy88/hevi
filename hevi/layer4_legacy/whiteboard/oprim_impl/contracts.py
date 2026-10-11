"""Whiteboard contracts and domain data structures (oprim layer)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WhiteboardBeat:
    """A single narrative beat within a whiteboard scene."""
    index: int
    narration: str
    title: str
    points: tuple[str, ...] = ()
    motif: str = "card"
    accent_color: str = "#2f9e44"


@dataclass(frozen=True)
class WhiteboardSegment:
    """A segment (scene) of the storyboard."""
    scene_id: str
    scene_type: str
    narration: str
    beats: tuple[WhiteboardBeat, ...] = ()
    keywords: tuple[str, ...] = ()
    props: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WhiteboardGate:
    """Quality gate result for whiteboard video verification."""
    name: str
    passed: bool
    value: Any
    threshold: Any = None
    message: str = ""


@dataclass(frozen=True)
class WhiteboardRecord:
    """Structured production record for a single whiteboard video artifact."""
    video_path: str
    orientation: str
    width: int
    height: int
    duration_s: float
    passed: bool
    gates: tuple[WhiteboardGate, ...] = ()
    sha256: str = ""
