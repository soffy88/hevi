"""SCENE3D pipeline stages (called by the line YAML).

These are thin wrappers around :mod:`hevi.layer4_legacy.scene3d.renderer` so
the catalogued pipeline can be invoked via Hevi's stage runner.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .renderer import SceneRenderer, ffprobe, make_contact_sheet, sha256
from .schema import load_scene


def stage_load(state: dict[str, Any], *, scene: str, out: str) -> dict[str, Any]:
    spec = load_scene(scene)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    state["spec"] = spec
    state["out"] = out
    return state


def stage_render(state: dict[str, Any]) -> dict[str, Any]:
    spec = state["spec"]
    r = SceneRenderer(spec, state["out"])
    state["renderer"] = r
    state["frame_paths"] = r.render_frames()
    return state


def stage_encode(state: dict[str, Any]) -> dict[str, Any]:
    state["video_path"] = state["renderer"].encode(state["frame_paths"])
    return state


def stage_contact_sheet(state: dict[str, Any], cols: int = 5, thumb_w: int = 320) -> dict[str, Any]:
    spec = state["spec"]
    frames = state["frame_paths"]
    step = max(1, len(frames) // 25)
    sample = frames[::step] or frames
    out = state["out"] / f"{spec.name}_contact_sheet.png"
    state["contact_sheet"] = make_contact_sheet(sample, out, cols=cols, thumb_w=thumb_w)
    return state


def stage_report(state: dict[str, Any]) -> dict[str, Any]:
    spec = state["spec"]
    video = state["video_path"]
    import json

    info = {
        "video": str(video),
        "frame_count": len(state["frame_paths"]),
        "duration_s": spec.duration_s,
        "fps": spec.fps,
        "width": spec.width,
        "height": spec.height,
        "sha256": sha256(video),
        "probe": ffprobe(video),
        "contact_sheet": str(state.get("contact_sheet", "")),
    }
    (state["out"] / "metrics.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return state
