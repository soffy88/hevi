"""Capability registration for collage_broll."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import Capability, CapabilityError, CapabilityResult, compute_sha256, register

from .metaphor import generate_metaphor
from .spec import build_visual_spec


def _render_metaphor(params, out_dir, *, duration=5.0, aspect="9:16", seed=42):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sentence = params.get("sentence") or params.get("text") or "橘猫看海"
    m = generate_metaphor(sentence)
    build_visual_spec(m, out_dir / "visual-spec.json")
    meta_path = out_dir / "metaphor.json"
    meta_path.write_text(__import__("json").dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

    narration = bool(params.get("narration", False))
    if params.get("mode") in ("narration", "audio"):
        narration = True
    if params.get("mode") in ("broll", "procedural", "codex"):
        narration = False
    if narration is False and params.get("narration") is None and float(duration) >= 10:
        narration = True

    from .render import procedural_render

    res = procedural_render(m, out_dir, "clip", duration=float(duration), narration=narration, narration_text=sentence)
    mp4 = Path(res["mp4"])
    if not mp4.exists():
        raise CapabilityError("collage_broll render produced no mp4")
    sha = compute_sha256(mp4)
    return CapabilityResult(
        duration_s=float(duration),
        sha256=sha,
        qa={"layers": res.get("layers"), "gif": res.get("gif"), "narration": res.get("narration")},
        mp4=str(mp4),
    )


def register_collage_broll_capabilities_once() -> None:
    for name in ("collage_broll.metaphor", "collage_broll.run", "collage_broll.render"):
        cap = Capability(
            name=name,
            kind="shot",
            line="collage_broll",
            aspects=["9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "sentence": {"type": "string"},
                    "text": {"type": "string"},
                    "narration": {"type": "boolean"},
                    "mode": {"type": "string"},
                },
                "required": [],
            },
            cpu_cost_hint=2.0,
            render=_render_metaphor,
        )
        register(cap, overwrite=True)


register_collage_broll_capabilities_once()
