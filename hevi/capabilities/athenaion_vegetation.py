"""B5 vegetation scatter (clean-room, method only).

Method source: Athenaion's vegetation discipline as described
in ``hevi-vs-athenaion.md`` -- code-drawn atlas, instanced
scatter, footprint avoidance, distance LOD; see
ATHENAION_ATTRIBUTION.md. The atlas drawing, the scatter
planner and the LOD split here are newly written; no Athenaion
image, texture, or self-reported count is used. The planned
count is a caller parameter and the placed count is measured
from the planner output -- the two must agree exactly.

Scatter planning is pure Python with a seeded RNG: grid cells
with jitter, rejected when the cell centre falls inside an
expanded footprint rectangle. Rendering is two instanced draws
in the page: near trees are low-poly geometry (trunk + foliage
cone), far trees are atlas billboards, split by distance to
the viewpoint. A close-up view of one near tree is captured
separately so interpenetration can be checked visually.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

from hevi.capabilities.athenaion_browser import capture_actions, page_html
from hevi.capabilities.athenaion_world import height_at
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def plan_scatter(
    *,
    count: int,
    seed: int = 0,
    region: tuple[float, float, float, float] = (-40.0, 40.0, -40.0, 40.0),
    footprints: list[dict[str, Any]] | None = None,
    margin: float = 1.5,
    spacing: float = 2.2,
) -> dict[str, Any]:
    """Grid-jitter scatter with footprint avoidance. Placed == planned."""
    if not isinstance(count, int) or count < 1:
        raise CapabilityError("world.athenaion_vegetation_scatter: count must be a positive integer")
    if not _is_num(spacing) or float(spacing) <= 0:
        raise CapabilityError("world.athenaion_vegetation_scatter: spacing must be > 0")
    rng = random.Random(seed)
    x0, x1, z0, z1 = (float(v) for v in region)
    footprints = footprints or []
    cells_x = max(1, int((x1 - x0) / float(spacing)))
    cells_z = max(1, int((z1 - z0) / float(spacing)))
    cells = [(ix, iz) for ix in range(cells_x) for iz in range(cells_z)]
    rng.shuffle(cells)
    placed: list[dict[str, Any]] = []
    rejected = 0
    for ix, iz in cells:
        if len(placed) >= count:
            break
        x = x0 + (ix + 0.5) * float(spacing) + (rng.random() - 0.5) * float(spacing) * 0.7
        z = z0 + (iz + 0.5) * float(spacing) + (rng.random() - 0.5) * float(spacing) * 0.7
        inside = False
        for fp in footprints:
            if (
                float(fp["x_min"]) - margin <= x <= float(fp["x_max"]) + margin
                and float(fp["z_min"]) - margin <= z <= float(fp["z_max"]) + margin
            ):
                inside = True
                break
        if inside:
            rejected += 1
            continue
        placed.append({
            "x": round(x, 3), "z": round(z, 3),
            "h": round(height_at(x, z), 3),
            "scale": round(0.7 + rng.random() * 0.7, 3),
            "rotation": round(rng.random() * math.pi * 2, 3),
            "variant": rng.randrange(4),
        })
    if len(placed) != count:
        raise CapabilityError(
            f"world.athenaion_vegetation_scatter: placed {len(placed)} != planned {count}; "
            f"region/footprints leave too few cells (rejected {rejected})"
        )
    return {
        "planned": count,
        "placed": len(placed),
        "rejected_by_footprints": rejected,
        "seed": seed,
        "region": [x0, x1, z0, z1],
        "footprints": footprints,
        "trees": placed,
    }


def split_lod(plan: dict[str, Any], viewpoint: tuple[float, float, float], *, near_distance: float = 25.0) -> dict[str, Any]:
    """Split placed trees into near (geometry) and far (billboard) sets."""
    vx, _, vz = (float(v) for v in viewpoint)
    near: list[dict[str, Any]] = []
    far: list[dict[str, Any]] = []
    for tree in plan["trees"]:
        dist = math.hypot(tree["x"] - vx, tree["z"] - vz)
        (near if dist <= near_distance else far).append({**tree, "distance": round(dist, 2)})
    return {"near": near, "far": far, "near_count": len(near), "far_count": len(far),
            "total": len(near) + len(far), "near_distance": float(near_distance)}


def build_vegetation_html(
    *,
    width: int,
    height: int,
    plan: dict[str, Any],
    lod: dict[str, Any],
    viewpoint: tuple[float, float, float],
    seed: int = 0,
) -> str:
    js = f"""
import * as THREE from 'three';
const W = {width}, H = {height};
const PLAN = {json.dumps(plan)};
const LOD = {json.dumps(lod)};
const VIEW = {json.dumps([float(v) for v in viewpoint])};
function fnv(label) {{ let h = 2166136261; for (let i = 0; i < label.length; i++) {{ h ^= label.charCodeAt(i); h = Math.imul(h, 16777619); }} return h >>> 0; }}
function mulberry32(seed) {{ let s = seed >>> 0; return function () {{ s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }}; }}
const renderer = new THREE.WebGLRenderer({{ antialias: false, preserveDrawingBuffer: true }});
renderer.setPixelRatio(1);
renderer.setSize(W, H, false);
document.getElementById('stage').appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x87a8c8);
const camera = new THREE.PerspectiveCamera(42, W / H, 0.1, 400);
const sun = new THREE.DirectionalLight(0xffe8c0, 2.2);
sun.position.set(30, 50, 20);
scene.add(sun);
scene.add(new THREE.HemisphereLight(0xbfd4e8, 0x6a5a44, 0.7));
const ground = new THREE.Mesh(new THREE.PlaneGeometry(100, 100), new THREE.MeshStandardMaterial({{ color: 0x5d7a3a, roughness: 1.0 }}));
ground.rotation.x = -Math.PI / 2;
scene.add(ground);
// Near trees: instanced trunk + foliage geometry (2 draw calls).
const dummy = new THREE.Object3D();
function fillInstanced(mesh, items, yBase, yScale) {{
  items.forEach((t, i) => {{
    dummy.position.set(t.x, t.h + yBase * t.scale, t.z);
    dummy.rotation.set(0, t.rotation, 0);
    dummy.scale.set(t.scale, t.scale * yScale, t.scale);
    dummy.updateMatrix();
    mesh.setMatrixAt(i, dummy.matrix);
  }});
  mesh.instanceMatrix.needsUpdate = true;
}}
const trunkGeo = new THREE.CylinderGeometry(0.18, 0.26, 1.6, 6);
const trunkMat = new THREE.MeshStandardMaterial({{ color: 0x5a4632, roughness: 0.95 }});
const trunks = new THREE.InstancedMesh(trunkGeo, trunkMat, LOD.near.length);
fillInstanced(trunks, LOD.near, 0.8, 1.0);
scene.add(trunks);
const foliageGeo = new THREE.ConeGeometry(1.15, 3.6, 8);
const foliageMat = new THREE.MeshStandardMaterial({{ color: 0x2f5230, roughness: 0.85 }});
const foliage = new THREE.InstancedMesh(foliageGeo, foliageMat, LOD.near.length);
fillInstanced(foliage, LOD.near, 3.2, 1.0);
scene.add(foliage);
// Code-drawn atlas: one 128x128 canvas per tree variant, seeded.
function makeAtlasTexture(variant) {{
  const c = document.createElement('canvas');
  c.width = 128; c.height = 128;
  const g = c.getContext('2d');
  const r2 = mulberry32((fnv('atlas') ^ (variant * 7919) ^ 12345) >>> 0);
  g.fillStyle = '#5a4632';
  g.fillRect(60, 84, 8, 34);
  const hue = 105 + variant * 8;
  for (let i = 0; i < 60; i++) {{
    const a = r2() * Math.PI * 2, r = r2() * 30;
    const px = 64 + Math.cos(a) * r, py = 52 + Math.sin(a) * r * 0.85;
    g.fillStyle = 'hsl(' + hue + ',' + (38 + r2() * 22) + '%,' + (26 + r2() * 18) + '%)';
    g.beginPath();
    g.arc(px, py, 2 + r2() * 5, 0, Math.PI * 2);
    g.fill();
  }}
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}}
// Far trees: one instanced billboard draw per atlas variant.
const billGeo = new THREE.PlaneGeometry(2.6, 3.6);
for (let v = 0; v < 4; v++) {{
  const items = LOD.far.filter((t) => t.variant === v);
  if (items.length === 0) continue;
  const billMat = new THREE.MeshBasicMaterial({{ map: makeAtlasTexture(v), transparent: true, alphaTest: 0.05, side: THREE.DoubleSide }});
  const bills = new THREE.InstancedMesh(billGeo, billMat, items.length);
  items.forEach((t, i) => {{
    dummy.position.set(t.x, t.h + 1.8 * t.scale, t.z);
    dummy.rotation.set(0, Math.atan2(VIEW[0] - t.x, VIEW[2] - t.z), 0);
    dummy.scale.set(t.scale, t.scale, t.scale);
    dummy.updateMatrix();
    bills.setMatrixAt(i, dummy.matrix);
  }});
  bills.instanceMatrix.needsUpdate = true;
  scene.add(bills);
}}
// Footprint markers: flat red outlines so avoidance is visible.
const fpMat = new THREE.MeshBasicMaterial({{ color: 0xc03028 }});
(PLAN.footprints || []).forEach((fp) => {{
  const w = fp.x_max - fp.x_min, d = fp.z_max - fp.z_min;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), fpMat);
  m.rotation.x = -Math.PI / 2;
  m.position.set((fp.x_min + fp.x_max) / 2, 0.15, (fp.z_min + fp.z_max) / 2);
  scene.add(m);
}});
function showOverview() {{
  camera.position.set(VIEW[0], VIEW[1], VIEW[2]);
  camera.lookAt(0, 2, 0);
  renderer.render(scene, camera);
  window.__athenaionSettled = 'overview';
}}
function showCloseup() {{
  const t = LOD.near[0];
  camera.position.set(t.x + 4.5, t.h + 3.2, t.z + 4.5);
  camera.lookAt(t.x, t.h + 2.0, t.z);
  renderer.render(scene, camera);
  window.__athenaionSettled = 'closeup';
}}
window.__athenaion = {{ show(name) {{ if (name === 'closeup') showCloseup(); else showOverview(); return name; }} }};
window.__athenaionStats = function () {{
  return {{ calls: renderer.info.render.calls, triangles: renderer.info.render.triangles,
    near_count: LOD.near.length, far_count: LOD.far.length }};
}};
window.__hfSettledFrame = 0;
window.__hf = {{
  getDurationFrames() {{ return 1; }},
  seekFrame(frame) {{ window.__athenaion.show('overview'); window.__hfSettledFrame = frame; return {{ frame: frame, settled: true }}; }},
  destroy() {{ renderer.dispose(); }}
}};
showOverview();
window.__hfReady = true;
"""
    return page_html(js)


def render_vegetation(
    *,
    out_dir: Path,
    width: int = 480,
    height: int = 270,
    count: int = 1200,
    seed: int = 0,
    footprints: list[dict[str, Any]] | None = None,
    viewpoint: tuple[float, float, float] = (28.0, 18.0, 34.0),
) -> dict[str, Any]:
    plan = plan_scatter(count=count, seed=seed, footprints=footprints)
    lod = split_lod(plan, viewpoint)
    if lod["total"] != plan["placed"] or plan["placed"] != plan["planned"]:
        raise CapabilityError("world.athenaion_vegetation_scatter: scatter count mismatch")
    if not lod["near"]:
        raise CapabilityError("world.athenaion_vegetation_scatter: no near trees for the close-up view; move the viewpoint")
    html = build_vegetation_html(width=width, height=height, plan=plan, lod=lod, viewpoint=viewpoint, seed=seed)
    actions = [
        {"name": view, "evaluate": f"window.__athenaion.show('{view}')",
         "settle": f"window.__athenaionSettled === '{view}'", "screenshot": True}
        for view in ("overview", "closeup")
    ]
    result = capture_actions(html, actions, width=width, height=height)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    views = []
    for shot_rec in result["shots"]:
        path = out_dir / f"{shot_rec['name']}.png"
        path.write_bytes(shot_rec["png_bytes"])
        views.append({"view": shot_rec["name"], "sha256": shot_rec["sha256"], "bytes": shot_rec["bytes"], "file": path.name})
    stats = result["stats"]
    return {
        "verdict": "pass",
        "planned": plan["planned"],
        "placed": plan["placed"],
        "rejected_by_footprints": plan["rejected_by_footprints"],
        "near_count": lod["near_count"],
        "far_count": lod["far_count"],
        "lod_total": lod["total"],
        "counts_match": lod["total"] == plan["placed"] == plan["planned"],
        "views": views,
        "draw_calls": stats.get("calls"),
        "triangles": stats.get("triangles"),
        "stats": stats,
        "ready_ms": result["ready_ms"],
        "three_module": result["three_module"],
        "closeup_tree": lod["near"][0],
        "human_measured": False,
        "external_assets": [],
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = render_vegetation(
        out_dir=out_dir,
        width=int(params.get("width", 480)),
        height=int(params.get("height", 270)),
        count=int(params.get("count", 1200)),
        seed=int(params.get("seed", seed)),
        footprints=params.get("footprints"),
    )
    report_path = out_dir / "vegetation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    first = out_dir / "overview.png"
    return CapabilityResult(
        png=str(first) if first.is_file() else None,
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"], "ok": True,
            "planned": report["planned"], "placed": report["placed"],
            "draw_calls": report["draw_calls"], "triangles": report["triangles"]},
    )


def register_athenaion_vegetation_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="world.athenaion_vegetation_scatter",
        kind="line",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "count": {"type": "integer"},
                "seed": {"type": "integer"},
                "footprints": {"type": "array"},
            },
            "additionalProperties": False,
        },
        cpu_cost_hint=1.0,
        render=_render,
        has_media_output=True,
        description=(
            "B5 vegetation scatter: code-drawn atlas, instanced "
            "scatter with footprint avoidance, distance LOD, "
            "planned == placed count check, overview + close-up. "
            "Zero external assets. See ATHENAION_ATTRIBUTION.md."
        ),
        line="world",
    ))
    return ["world.athenaion_vegetation_scatter"]


register_athenaion_vegetation_capabilities_once()
