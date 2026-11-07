"""Capability registration for collage_broll."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import Capability, CapabilityError, CapabilityResult, compute_sha256, register


def _render_metaphor(params, out_dir, *, duration=5.0, aspect="9:16", seed=42):
    from .metaphor import generate_metaphor
    from .spec import build_visual_spec

    sentence = params.get("sentence") or params.get("text") or ""
    m = generate_metaphor(sentence)
    build_visual_spec(m, Path(out_dir) / "visual-spec.json")
    # procedural render
    from .render import procedural_render

    res = procedural_render(m, Path(out_dir), "clip")
    mp4 = Path(res["mp4"])
    sha = compute_sha256(mp4)
    return CapabilityResult(duration_s=duration, sha256=sha, qa={"layers": res["layers"]}, mp4=str(mp4), gif=res["gif"])


def _render_run(params, out_dir, *, duration=5.0, aspect="9:16", seed=42):
    # full run for one sentence
    return _render_metaphor(params, out_dir, duration=duration, aspect=aspect, seed=seed)


def register_collage_broll_capabilities_once() -> None:
    for name in ("collage_broll.metaphor", "collage_broll.run", "collage_broll.render"):
        cap = Capability(
            name=name,
            kind="shot",
            line="collage_broll",
            aspects=["9:16"],
            params_schema={"type": "object", "properties": {"sentence": {"type": "string"}, "text": {"type": "string"}}, "required": []},
            cpu_cost_hint=2.0,
            render=_render_metaphor,
        )
        register(cap, overwrite=True)


register_collage_broll_capabilities_once()
