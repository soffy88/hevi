"""MCP server (stdio, newline-delimited JSON-RPC 2.0) exposing Blender tools.

Run:  python -m hevi.blendercmd.mcp_server --workdir /tmp/blender_session
Claude/Codex config: {"command": "<venv>/bin/python", "args": ["-m", "hevi.blendercmd.mcp_server"]}"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from typing import Any

from .obase_runner import run_ops
from .omodul_session import BlenderSession

PROTOCOL = "2024-11-05"
V3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}


def _t(name, desc, props, req=()):
    return {"name": name, "description": desc,
            "inputSchema": {"type": "object", "properties": props, "required": list(req)}}


TOOLS = [
    _t("blender_reset", "Clear the scene; optionally build a clay stage (ground, key+fill light, camera).",
       {"clay_stage": {"type": "boolean"}, "preset": {"type": "string", "enum": ["eevee", "cycles_fast", "cycles", "workbench"]},
        "resolution": {"type": "array", "items": {"type": "integer"}}, "fps": {"type": "integer"}, "frames": {"type": "integer"}}),
    _t("blender_add_object", "Add sphere/cube/cylinder/cone/plane/torus/text or import a local model (.obj/.glb/.gltf/.fbx/.stl/.ply).",
       {"type": {"type": "string"}, "name": {"type": "string"}, "location": V3, "rotation": V3, "scale": V3,
        "radius": {"type": "number"}, "text": {"type": "string"}, "path": {"type": "string"}}, ("type", "name")),
    _t("blender_set_material", "Matte clay material (Principled, roughness~0.9) with a hex colour.",
       {"target": {"type": "string"}, "color": {"type": "string"}, "roughness": {"type": "number"}}, ("target", "color")),
    _t("blender_add_light", "Add/replace a light (AREA/SUN/POINT/SPOT).",
       {"name": {"type": "string"}, "type": {"type": "string"}, "location": V3, "target": V3, "rotation": V3,
        "energy": {"type": "number"}, "size": {"type": "number"}, "color": {"type": "string"}}, ("name",)),
    _t("blender_set_camera", "Place camera; optional target to look at, lens mm, and frame to keyframe a camera move.",
       {"location": V3, "target": V3, "lens": {"type": "number"}, "frame": {"type": "integer"}}),
    _t("blender_keyframe", "Keyframe location/rotation(deg)/scale of an object (or 'Camera') at frame N.",
       {"target": {"type": "string"}, "frame": {"type": "integer"}, "location": V3, "rotation": V3, "scale": V3,
        "interpolation": {"type": "string", "enum": ["BEZIER", "LINEAR", "CONSTANT"]}}, ("target", "frame")),
    _t("blender_scene_settings", "Engine preset / resolution / fps / frame range / background colour.",
       {"preset": {"type": "string"}, "resolution": {"type": "array", "items": {"type": "integer"}}, "fps": {"type": "integer"},
        "frame_start": {"type": "integer"}, "frame_end": {"type": "integer"}, "background": {"type": "string"}, "samples": {"type": "integer"}}),
    _t("blender_delete", "Delete an object from the scene.", {"target": {"type": "string"}}, ("target",)),
    _t("blender_get_scene", "Return the current scene op list and summary.", {}),
    _t("blender_render_frame", "Render one frame to PNG; returns path (and the image) so you can look and revise.",
       {"frame": {"type": "integer"}, "preset": {"type": "string"}, "include_image": {"type": "boolean"}}),
    _t("blender_render_animation", "Render the frame range to MP4 (or a PNG dir if out has no .mp4).",
       {"out": {"type": "string"}, "preset": {"type": "string"}, "frame_end": {"type": "integer"}}),
    _t("blender_run_ops", "Run a raw JSON op list in a fresh Blender (stateless).", {"ops": {"type": "array"}}, ("ops",)),
]
_OPMAP = {"blender_add_object": "add", "blender_set_material": "material", "blender_add_light": "light",
          "blender_set_camera": "camera", "blender_keyframe": "keyframe", "blender_scene_settings": "scene",
          "blender_delete": "delete"}


class Server:
    def __init__(self, workdir: str):
        self.s = BlenderSession(workdir)

    def call(self, name: str, a: dict) -> list[dict]:
        if name in _OPMAP:
            r: Any = self.s.add({"op": _OPMAP[name], **a})
        elif name == "blender_reset":
            kw = {k: a[k] for k in ("preset", "resolution", "fps", "frames") if k in a}
            r = self.s.reset(a.get("clay_stage", True), **kw)
        elif name == "blender_get_scene":
            r = {"summary": self.s.summary(), "ops": self.s.ops}
        elif name == "blender_render_frame":
            r = self.s.render_frame(int(a.get("frame", 1)), preset=a.get("preset"))
            out = [{"type": "text", "text": json.dumps(_slim(r), ensure_ascii=False)}]
            png = next((o["path"] for o in r.get("outputs", []) if o["kind"] == "frame"), None)
            if png and a.get("include_image", True) and os.path.exists(png):
                out.append({"type": "image", "mimeType": "image/png", "data": base64.b64encode(open(png, "rb").read()).decode()})
            return out
        elif name == "blender_render_animation":
            r = self.s.render_animation(a.get("out", "anim.mp4"), a.get("preset"), a.get("frame_end"))
        elif name == "blender_run_ops":
            r = run_ops(a["ops"], str(self.s.dir))
        else:
            raise KeyError(f"unknown tool {name}")
        return [{"type": "text", "text": json.dumps(_slim(r), ensure_ascii=False)}]

    def handle(self, msg: dict) -> dict | None:
        mid, m = msg.get("id"), msg.get("method")
        if mid is None:  # notification
            return None
        try:
            if m == "initialize":
                res = {"protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
                       "capabilities": {"tools": {"listChanged": False}},
                       "serverInfo": {"name": "hevi-blender", "version": "0.1.0"}}
            elif m == "ping":
                res = {}
            elif m == "tools/list":
                res = {"tools": TOOLS}
            elif m == "tools/call":
                p = msg.get("params", {})
                try:
                    res = {"content": self.call(p["name"], p.get("arguments") or {}), "isError": False}
                except Exception as e:  # tool errors are results, not protocol errors
                    res = {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {m}"}}
            return {"jsonrpc": "2.0", "id": mid, "result": res}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}


def _slim(r: Any) -> Any:
    if isinstance(r, dict) and "error" in r and isinstance(r["error"], dict):
        r = {**r, "error": {k: v for k, v in r["error"].items() if k != "trace"} | {"trace_tail": r["error"].get("trace", "")[-400:]}}
    return r


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default=os.environ.get("HEVI_BLENDER_SESSION", "/tmp/hevi_blender_session"))
    srv = Server(ap.parse_args(argv).workdir)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            out = srv.handle(msg)
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
