"""M2 房间背景抽卡 — orchestrator.

Builds the procedural room model, renders manga line-art + halftone frames via
the shared CPU SwiftShader renderer, encodes a video + still PNG, and exports a
GLB.  Deterministic by seed.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..common import write_json, sha256_file, RenderSize
from ..common.renderer import FrameRenderer, encode_video, make_contact_sheet, ffprobe
from . import RoomSpec, generate_primitives
from .template import build_html


def _camera_for_variation(spec: RoomSpec) -> dict:
    # Slight orbit for video so the room reveals depth (still deterministic).
    return {"radius": 9.0, "height": 3.2, "azimuth": 0.7, "orbit": 0.25}


def build_model(spec: RoomSpec) -> dict:
    model = generate_primitives(spec)
    model["camera"] = _camera_for_variation(spec)
    return model


def render_room(spec: RoomSpec, out_dir: str | Path, *, fps: int = 24,
                duration_s: float = 4.0, long_edge: int | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if long_edge is None:
        long_edge = spec.long_edge
    model = build_model(spec)
    write_json(out / "room_model.json", model)

    rs = RenderSize.for_aspect("16:9", long_edge)
    width, height = rs.width, rs.height
    if "9:16" in spec.to_dict().get("aspect", ""):
        width, height = RenderSize.for_aspect("9:16", long_edge)
    html = build_html(model, width, height, fps, duration_s)

    fr = FrameRenderer(html, out, width, height, duration_s, fps)
    frames = fr.render_frames()
    mp4 = encode_video(fr.frames_dir, out / f"room_{spec.kind}.mp4", fps=fps)
    still = frames[0]
    still_png = out / "room_still.png"
    still_png.write_bytes(still.read_bytes())

    # 透明纸面线稿: dark ink retained, white paper converted to transparent
    trans_png = out / "room_transparent_lineart.png"
    _make_transparent_lineart(still_png, trans_png)

    cs = make_contact_sheet(frames, out / "room_contact_sheet.png", cols=5)

    # GLB export (glTF binary) — pure-python, dependency-free serialization.
    glb_path = _write_glb(model, out / f"room_{spec.kind}.glb")

    probe = ffprobe(mp4)
    report = {
        "kind": spec.kind,
        "seed": spec.seed,
        "size": {"width": width, "height": height},
        "duration_s": duration_s,
        "frame_count": len(frames),
        "ffprobe": probe,
        "sha256": {
            "mp4": sha256_file(mp4),
            "still": sha256_file(still_png),
            "transparent_lineart": sha256_file(trans_png),
            "glb": sha256_file(glb_path),
        },
        "glb": str(glb_path),
        "transparent_lineart": str(trans_png),
        "contact_sheet": str(cs),
    }
    write_json(out / "qc_report.json", report)
    return {
        "model": str(out / "room_model.json"),
        "mp4": str(mp4),
        "still": str(still_png),
        "transparent_lineart": str(trans_png),
        "glb": str(glb_path),
        "report": report,
    }


def _make_transparent_lineart(in_path: Path, out_path: Path) -> Path:
    from PIL import Image

    im = Image.open(in_path).convert("RGBA")
    data = im.getdata()
    new_data = []
    for item in data:
        # lightness: dark is ink (opaque), light is paper (transparent)
        b = int(0.299 * item[0] + 0.587 * item[1] + 0.114 * item[2])
        alpha = max(0, min(255, 255 - b))
        new_data.append((17, 17, 17, alpha))
    im.putdata(new_data)
    im.save(out_path, "PNG")
    return out_path


def _write_glb(model: dict, path: Path) -> Path:
    """Serialize the room primitives to a minimal binary glTF (GLB).

    Geometry: floor tiles + furniture boxes/cylinders + walls.  CPU-only,
    no external libs.  Coordinates match the Three.js scene so the GLB can be
    re-rendered with the same camera.
    """
    import struct

    # gather mesh nodes
    nodes: list[dict] = []
    meshes: list[dict] = []
    accessors: list[dict] = []
    buffer_views: list[dict] = []
    bin_blob = bytearray()

    def add_box(sx, sy, sz):
        # unit cube scaled -> vertices
        hx, hy, hz = sx / 2, sy / 2, sz / 2
        verts = [
            [-hx,-hy,-hz],[hx,-hy,-hz],[hx,hy,-hz],[-hx,hy,-hz],
            [-hx,-hy,hz],[hx,-hy,hz],[hx,hy,hz],[-hx,hy,hz],
        ]
        idx = [0,1,2,0,2,3, 4,5,6,4,6,7, 0,1,5,0,5,4,
               1,2,6,1,6,5, 2,3,7,2,7,6, 3,0,4,3,4,7]
        return verts, idx

    def add_cyl(r, h, seg=16):
        verts = []
        idx = []
        hy = h / 2
        for i in range(seg):
            a = 2 * 3.14159 * i / seg
            verts.append([r*math.cos(a), -hy, r*math.sin(a)])
            verts.append([r*math.cos(a), hy, r*math.sin(a)])
        for i in range(seg):
            i0 = i*2; i1 = (i*2+2) % (seg*2); i2=(i*2+3)%(seg*2); i3=(i*2+1)%(seg*2)
            idx += [i0, i1, i2, i0, i2, i3]
        return verts, idx

    def push_mesh(verts, idx, pos):
        # world transform: translate
        vbytes = bytearray()
        for v in verts:
            vbytes += struct.pack("<3f", v[0]+pos[0], v[1]+pos[1], v[2]+pos[2])
        ibytes = bytearray()
        for i in idx:
            ibytes += struct.pack("<H", i)
        # accessor for positions
        base = len(bin_blob)
        voff = base
        bin_blob.extend(vbytes)
        ioff = len(bin_blob)
        bin_blob.extend(ibytes)
        buffer_views.append({"buffer":0,"byteOffset":voff,"byteLength":len(vbytes),"target":34962})
        v_acc = len(accessors)
        accessors.append({"bufferView":len(buffer_views)-1,"componentType":5126,"count":len(verts),"type":"VEC3"})
        buffer_views.append({"buffer":0,"byteOffset":ioff,"byteLength":len(ibytes),"target":34963})
        i_acc = len(accessors)
        accessors.append({"bufferView":len(buffer_views)-1,"componentType":5123,"count":len(idx),"type":"SCALAR"})
        mesh_idx = len(meshes)
        meshes.append({"primitives":[{"attributes":{"POSITION":v_acc},"indices":i_acc}]})
        node_idx = len(nodes)
        nodes.append({"mesh":mesh_idx, "translation":[0,0,0]})

    import math
    for t in model.get("floor", []):
        v, i = add_box(t["size"][0], t["size"][1], t["size"][2])
        push_mesh(v, i, t["pos"])
    for p in model.get("furniture", []):
        if p["kind"] == "box":
            v, i = add_box(*p["size"])
        else:
            v, i = add_cyl(p["radius"], p["height"])
        push_mesh(v, i, p["pos"])
    # walls
    half = model["walls"]["half"]; hgt = model["walls"]["height"]
    v, i = add_box(half*2, hgt, 0.2); push_mesh(v, i, [0, hgt/2, -half])
    v, i = add_box(0.2, hgt, half*2); push_mesh(v, i, [-half, hgt/2, 0])
    v, i = add_box(0.2, hgt, half*2); push_mesh(v, i, [half, hgt/2, 0])

    gltf = {
        "asset": {"version": "2.0", "generator": "hevi-manga roomgacha"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(bin_blob)}],
    }
    # JSON chunk must be 4-byte aligned
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(json_bytes) % 4 != 0:
        json_bytes += b" "
    bin_bytes = bytes(bin_blob)
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    out = bytearray()
    out += b"glTF"
    out += struct.pack("<I", 2)  # version
    out += struct.pack("<I", total)
    out += struct.pack("<I", len(json_bytes))
    out += b"JSON"
    out += json_bytes
    out += struct.pack("<I", len(bin_bytes))
    out += b"BIN\x00"
    out += bin_bytes
    path.write_bytes(bytes(out))
    return path
