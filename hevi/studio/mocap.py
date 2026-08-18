"""OpenMontage ink-theater 动作卡。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.studio.voices import asset_root


def mocap_dir(*, root: Path | None = None) -> Path:
    return (root or asset_root()) / "mocap-clips"


def list_mocap(*, root: Path | None = None) -> list[dict[str, Any]]:
    dest = mocap_dir(root=root)
    catalog = dest / "catalog.json"
    if catalog.exists():
        data = json.loads(catalog.read_text(encoding="utf-8"))
        if isinstance(data, list):
            rows = [dict(item) for item in data if isinstance(item, dict)]
            for row in rows:
                clip = dest / "clips" / f"{row.get('name')}.json"
                if clip.exists():
                    row["path"] = str(clip)
            return rows
    clips = dest / "clips"
    if not clips.is_dir():
        return []
    return [
        {"name": path.stem, "path": str(path)}
        for path in sorted(clips.glob("*.json"))
    ]


def get_mocap(name: str, *, root: Path | None = None) -> dict[str, Any] | None:
    needle = (name or "").strip().lower()
    for item in list_mocap(root=root):
        if str(item.get("name") or "").lower() == needle:
            return item
    return None
