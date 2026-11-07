"""Orchestration: a persistent scene session.

Blender runs one-shot per render (headless, no daemon): the session stores the
scene op list on disk and replays it before each render. Cheap (<1s scene
build) and deterministic; AI looks at the returned PNG, then edits ops."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .obase_runner import run_ops
from .oskill_ops import SCENE_OPS, validate_op, clay_base_ops


class BlenderSession:
    def __init__(self, workdir: str | Path):
        self.dir = Path(workdir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "scene_ops.json"
        self.ops: list[dict] = json.loads(self.file.read_text()) if self.file.exists() else []
        self._n = len(list(self.dir.glob("shot_*.png")))

    def save(self):
        self.file.write_text(json.dumps(self.ops, indent=1))

    def reset(self, clay_stage: bool = True, **kw) -> dict:
        self.ops = clay_base_ops(**kw) if clay_stage else []
        self.save()
        return self.summary()

    def add(self, op: dict) -> dict:
        o = validate_op(op)
        if o["op"] not in SCENE_OPS:
            raise ValueError(f"{o['op']} is not a scene op")
        if o["op"] == "delete":  # also drop earlier ops on that object
            self.ops = [x for x in self.ops if x.get("name") != o["target"] and x.get("target") != o["target"]]
        else:
            self.ops.append(o)
        self.save()
        return self.summary()

    def summary(self) -> dict:
        names = [o["name"] for o in self.ops if o["op"] in ("add", "light") and "name" in o]
        return {"ops": len(self.ops), "objects": names, "keyframes": sum(o["op"] == "keyframe" for o in self.ops)}

    def render_frame(self, frame: int = 1, out: str | None = None, preset: str | None = None) -> dict:
        self._n += 1
        out = out or str(self.dir / f"shot_{self._n:03d}_f{frame}.png")
        extra = [{"op": "scene", "preset": preset}] if preset else []
        return run_ops(self.ops + extra + [{"op": "render_frame", "frame": frame, "out": out}], self.dir)

    def render_animation(self, out: str = "anim.mp4", preset: str | None = None, frame_end: int | None = None) -> dict:
        extra = {"op": "scene"}
        if preset:
            extra["preset"] = preset
        if frame_end:
            extra["frame_end"] = int(frame_end)
        return run_ops(self.ops + [extra, {"op": "render_animation", "out": out}], self.dir)
