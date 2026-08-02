"""Remotion Step 9-10 adapter kept behind the 3O assembly boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.explainer.render import _run_remotion_render


async def render_explainer_composition(
    composition_id: str, output_path: Path, *, aspect_ratio: str = "9:16", **_: Any
) -> Path:
    """Render a declared Explainer composition and verify its MP4 artifact."""
    if aspect_ratio not in {"9:16", "16:9"}:
        raise ValueError("aspect_ratio 仅支持 9:16 或 16:9")
    await _run_remotion_render(composition_id, output_path)
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError(f"Remotion 未产出 MP4: {output_path}")
    return output_path
