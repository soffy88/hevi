"""Whiteboard explainer facade layer (hevi/whiteboard/adapter.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.layer4_legacy.whiteboard.omodul_impl.produce import produce_whiteboard


def render_whiteboard(
    storyboard: dict[str, Any],
    output_dir: Path,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute whiteboard video production pipeline."""
    return produce_whiteboard(
        storyboard_data=storyboard,
        output_dir=Path(output_dir),
        config=config or {},
    )
