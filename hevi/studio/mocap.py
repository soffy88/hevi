"""CMU motion-capture clip catalogue for the SVG character renderer.

The clips under ``assets/mocap-clips/clips`` are 2-D joint tracks derived from
the **CMU Graphics Lab Motion Capture Database** by :mod:`hevi.studio.cmumocap`
(see ``assets/mocap-clips/README.md`` for provenance).  This module is the thin
catalogue the studio tools read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.studio.voices import asset_root


def mocap_dir(*, root: Path | None = None) -> Path:
    return (root or asset_root()) / "mocap-clips"


def _clip_meta(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    return {
        "name": data.get("name") or path.stem,
        "path": str(path),
        "source": data.get("source", ""),
        "plane": data.get("plane", ""),
        "fps": data.get("fps"),
        "frameCount": data.get("frameCount"),
        "label": data.get("label", ""),
        "duration": round((data.get("frameCount") or 0) / (data.get("fps") or 30), 3),
    }


def list_mocap(*, root: Path | None = None) -> list[dict[str, Any]]:
    clips = mocap_dir(root=root) / "clips"
    if not clips.is_dir():
        return []
    return [_clip_meta(path) for path in sorted(clips.glob("*.json"))]


def get_mocap(name: str, *, root: Path | None = None) -> dict[str, Any] | None:
    needle = (name or "").strip().lower()
    for item in list_mocap(root=root):
        if str(item.get("name") or "").lower() == needle:
            return item
    return None
