"""Capability adapter: ``scene3d.generic`` - render any generic scene JSON (or a
template + overrides) via :mod:`hevi.scene3d.generic`.  The old three presets
are reachable as templates (``template: planet_orbit|fox_wheat|star_sea``)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.capabilities import Capability, CapabilityError, CapabilityResult, contains, register

NAME = "scene3d.generic"
_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "scene": {"type": "object", "description": "generic scene JSON (see hevi/scene3d/generic/spec.py)"},
        "scene_path": {"type": "string"},
        "template": {"type": "string", "description": "boat_sea_islands|planet_orbit|fox_wheat|star_sea"},
        "overrides": {"type": "object"},
        "resolution": {"type": "integer", "minimum": 64, "maximum": 2160},
        "fps": {"type": "integer", "minimum": 1, "maximum": 60},
        "enforce_prompt": {"type": "boolean"},
    },
}


def _render(params: dict[str, Any], out_dir: str | Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    import json
    from hevi.scene3d.generic import render_scene
    from hevi.scene3d.generic.spec import SceneError
    from hevi.scene3d.generic.templates import deep_merge

    base_dir = None
    if params.get("scene_path"):
        p = Path(params["scene_path"])
        doc, base_dir = json.loads(p.read_text(encoding="utf-8")), p.parent
    elif params.get("scene"):
        doc = dict(params["scene"])
    elif params.get("template"):
        doc = {"template": params["template"]}
    else:
        raise CapabilityError("scene3d.generic needs one of scene / scene_path / template")
    over: dict[str, Any] = dict(params.get("overrides") or {})
    over["duration_s"] = float(duration)
    over["seed"] = int(seed)
    over.setdefault("camera", {})["aspect"] = aspect
    for k in ("resolution", "fps"):
        if k in params:
            over[k] = params[k]
    doc = deep_merge(doc, over)
    try:
        r = render_scene(doc, out_dir, base_dir=base_dir, enforce_prompt=params.get("enforce_prompt", True))
    except SceneError as exc:
        raise CapabilityError(f"scene3d.generic: {exc}") from exc
    except Exception as exc:
        raise CapabilityError(f"scene3d.generic render failed: {exc}") from exc
    return CapabilityResult(mp4=r["mp4"], duration_s=r["duration_s"], sha256=r["sha256"],
                            qa={k: r[k] for k in ("frame_count", "nb_read_frames", "width", "height", "fps",
                                                   "frames_sha256", "prompt_report", "contact_sheet", "total_s")})


def register_scene3d_generic_once() -> None:
    if contains(NAME):
        return
    register(Capability(name=NAME, kind="shot", aspects=["16:9", "9:16", "1:1", "21:9", "4:3", "3:4"],
                        params_schema=_SCHEMA, cpu_cost_hint=1.5, render=_render, line="scene3d",
                        description="通用 three.js 场景：JSON 描述物体/材质/灯光/雾/背景 + CatmullRom 镜头路径（FOV/roll 关键帧），"
                                    "提示词三段式(主体/应有/禁止)硬校验，确定性逐帧截图 + ffmpeg；预设即模板。"))


register_scene3d_generic_once()
