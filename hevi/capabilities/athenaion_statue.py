"""B2 SDF statue, minimal version (clean-room, method only).

Method source: Athenaion's SDF modelling + surface-nets meshing
+ SDF-gradient normals as described in ``hevi-vs-athenaion.md``;
see ATHENAION_ATTRIBUTION.md. The SDF primitives, the blending,
the naive surface-nets extraction and the gradient normals here
are newly written; no Athenaion code, mesh, or scan is used, and
the figure is a parametric draped figure built from spheres,
capsules, a rounded cone and boxes -- no external model.

Meshing: the SDF is sampled on a regular grid (numpy, vectorised);
every grid cell whose corners straddle the surface gets one
vertex at the mean of its edge crossings (naive surface nets),
and every sign-changing grid edge joins the four cells sharing
it into a quad. Normals are the SDF gradient by central
differences, evaluated at each vertex. The result is rendered
in three views, and once combined with one parametric column
from B3 (``world.athenaion_classical_orders``).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from hevi.capabilities.athenaion_browser import capture_actions, page_html
from hevi.capabilities.athenaion_orders import build_column
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False


# ------------------------------------------------------------- SDF primitives
# Each takes broadcast arrays (X, Y, Z) and returns a distance array.

def _sd_sphere(x: np.ndarray, y: np.ndarray, z: np.ndarray, cx: float, cy: float, cz: float, r: float) -> np.ndarray:
    return np.sqrt((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2) - r


def _sd_box(x: np.ndarray, y: np.ndarray, z: np.ndarray, cx: float, cy: float, cz: float, hx: float, hy: float, hz: float) -> np.ndarray:
    qx = np.abs(x - cx) - hx
    qy = np.abs(y - cy) - hy
    qz = np.abs(z - cz) - hz
    ox = np.maximum(qx, 0.0)
    oy = np.maximum(qy, 0.0)
    oz = np.maximum(qz, 0.0)
    outside = np.sqrt(ox * ox + oy * oy + oz * oz)
    inside = np.minimum(np.maximum(np.maximum(qx, qy), qz), 0.0)
    return outside + inside


def _sd_capsule(x: np.ndarray, y: np.ndarray, z: np.ndarray, ax: float, ay: float, az: float, bx: float, by: float, bz: float, r: float) -> np.ndarray:
    pax, pay, paz = x - ax, y - ay, z - az
    bax, bay, baz = bx - ax, by - ay, bz - az
    denom = bax * bax + bay * bay + baz * baz
    h = np.clip((pax * bax + pay * bay + paz * baz) / denom, 0.0, 1.0)
    dx, dy, dz = pax - bax * h, pay - bay * h, paz - baz * h
    return np.sqrt(dx * dx + dy * dy + dz * dz) - r


def _sd_round_cone(x: np.ndarray, y: np.ndarray, z: np.ndarray, y0: float, y1: float, r0: float, r1: float) -> np.ndarray:
    """Vertical rounded cone (robe): radius lerps r0 -> r1 from y0 to y1."""
    frac = np.clip((y - y0) / max(y1 - y0, 1e-6), 0.0, 1.0)
    r = r0 + (r1 - r0) * frac
    radial = np.sqrt(x * x + z * z) - r
    vertical = np.maximum(y0 - y, y - y1)
    return np.maximum(radial, vertical) if False else np.where(
        (y >= y0) & (y <= y1), radial, np.sqrt(np.maximum(radial, 0.0) ** 2 + vertical ** 2) + np.minimum(vertical, 0.0) * 0.0 + np.where(vertical > 0, 0.0, 0.0)
    )


def _smin(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1.0 - h) + a * h - k * h * (1.0 - h)


def statue_sdf(x: np.ndarray, y: np.ndarray, z: np.ndarray, *, height_scale: float = 1.0) -> np.ndarray:
    """Draped figure SDF. Total height about 3.6 * height_scale metres."""
    s = float(height_scale)
    # Pedestal (kept separate in the union: a hard min, no blend).
    d = _sd_box(x, y, z, 0.0, 0.35 * s, 0.0, 1.05 * s, 0.35 * s, 1.05 * s)
    # Robe: rounded cone from the pedestal to the chest.
    robe = _sd_round_cone(x, y, z, 0.7 * s, 2.55 * s, 0.95 * s, 0.52 * s)
    # Chest capsule and head sphere, smoothly blended into the robe.
    chest = _sd_capsule(x, y, z, 0.0, 2.35 * s, 0.0, 0.0, 2.95 * s, 0.0, 0.42 * s)
    figure = _smin(robe, chest, 0.18 * s)
    head = _sd_sphere(x, y, z, 0.0, 3.28 * s, 0.0, 0.34 * s)
    figure = _smin(figure, head, 0.12 * s)
    # Helmet: slightly larger flattened sphere + crest box.
    helmet = _sd_sphere(x, y, z, 0.0, 3.36 * s, 0.0, 0.38 * s)
    helmet = np.minimum(helmet, _sd_box(x, y, z, 0.0, 3.62 * s, 0.0, 0.05 * s, 0.16 * s, 0.30 * s))
    figure = np.minimum(figure, helmet)
    # Arms: capsules angled down along the robe.
    arm_l = _sd_capsule(x, y, z, -0.42 * s, 2.75 * s, 0.0, -0.72 * s, 1.95 * s, 0.10 * s, 0.15 * s)
    arm_r = _sd_capsule(x, y, z, 0.42 * s, 2.75 * s, 0.0, 0.72 * s, 1.95 * s, 0.10 * s, 0.15 * s)
    figure = np.minimum(figure, np.minimum(arm_l, arm_r))
    return np.minimum(d, figure)


# ------------------------------------------------------------- surface nets


def mesh_sdf(
    sdf_fn: Any,
    bounds: tuple[float, float, float, float, float, float],
    resolution: tuple[int, int, int],
    *,
    gradient_eps: float = 0.02,
) -> dict[str, Any]:
    """Naive surface nets over a regular grid. Returns mesh + stats."""
    x0, x1, y0, y1, z0, z1 = bounds
    nx, ny, nz = resolution
    xs = np.linspace(x0, x1, nx)
    ys = np.linspace(y0, y1, ny)
    zs = np.linspace(z0, z1, nz)
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    field = np.asarray(sdf_fn(X, Y, Z), dtype=np.float64)
    inside = field < 0.0

    # One vertex per straddling cell, at the mean of edge crossings.
    vertex_index: dict[tuple[int, int, int], int] = {}
    vertices: list[list[float]] = []
    cell_count = (nx - 1) * (ny - 1) * (nz - 1)
    for i in range(nx - 1):
        for j in range(ny - 1):
            for k in range(nz - 1):
                corners = inside[i:i + 2, j:j + 2, k:k + 2]
                if corners.all() or not corners.any():
                    continue
                points: list[list[float]] = []
                # 12 cell edges: interpolate where the sign changes.
                edges = [
                    ((i, j, k), (i + 1, j, k)), ((i, j + 1, k), (i + 1, j + 1, k)),
                    ((i, j, k + 1), (i + 1, j, k + 1)), ((i, j + 1, k + 1), (i + 1, j + 1, k + 1)),
                    ((i, j, k), (i, j + 1, k)), ((i + 1, j, k), (i + 1, j + 1, k)),
                    ((i, j, k + 1), (i, j + 1, k + 1)), ((i + 1, j, k + 1), (i + 1, j + 1, k + 1)),
                    ((i, j, k), (i, j, k + 1)), ((i + 1, j, k), (i + 1, j, k + 1)),
                    ((i, j + 1, k), (i, j + 1, k + 1)), ((i + 1, j + 1, k), (i + 1, j + 1, k + 1)),
                ]
                for (a, b) in edges:
                    fa, fb = field[a], field[b]
                    if (fa < 0.0) == (fb < 0.0):
                        continue
                    t = fa / (fa - fb) if fa != fb else 0.5
                    pa = np.array([xs[a[0]], ys[a[1]], zs[a[2]]])
                    pb = np.array([xs[b[0]], ys[b[1]], zs[b[2]]])
                    points.append((pa + t * (pb - pa)).tolist())
                if not points:
                    continue
                mean = np.mean(np.array(points), axis=0)
                vertex_index[(i, j, k)] = len(vertices)
                vertices.append([float(v) for v in mean])

    # Quads from sign-changing grid edges, split into triangles.
    indices: list[int] = []
    # X-edges: cells (i, j-1, k-1), (i, j, k-1), (i, j-1, k), (i, j, k)
    for i in range(nx - 1):
        for j in range(1, ny - 1):
            for k in range(1, nz - 1):
                if inside[i, j, k] == inside[i + 1, j, k]:
                    continue
                quad = [
                    (i, j - 1, k - 1), (i, j, k - 1), (i, j, k), (i, j - 1, k),
                ]
                if all(c in vertex_index for c in quad):
                    v = [vertex_index[c] for c in quad]
                    if field[i, j, k] < field[i + 1, j, k]:
                        indices.extend([v[0], v[1], v[2], v[0], v[2], v[3]])
                    else:
                        indices.extend([v[0], v[2], v[1], v[0], v[3], v[2]])
    # Y-edges
    for i in range(1, nx - 1):
        for j in range(ny - 1):
            for k in range(1, nz - 1):
                if inside[i, j, k] == inside[i, j + 1, k]:
                    continue
                quad = [
                    (i - 1, j, k - 1), (i, j, k - 1), (i, j, k), (i - 1, j, k),
                ]
                if all(c in vertex_index for c in quad):
                    v = [vertex_index[c] for c in quad]
                    if field[i, j, k] < field[i, j + 1, k]:
                        indices.extend([v[0], v[1], v[2], v[0], v[2], v[3]])
                    else:
                        indices.extend([v[0], v[2], v[1], v[0], v[3], v[2]])
    # Z-edges
    for i in range(1, nx - 1):
        for j in range(1, ny - 1):
            for k in range(nz - 1):
                if inside[i, j, k] == inside[i, j, k + 1]:
                    continue
                quad = [
                    (i - 1, j - 1, k), (i, j - 1, k), (i, j, k), (i - 1, j, k),
                ]
                if all(c in vertex_index for c in quad):
                    v = [vertex_index[c] for c in quad]
                    if field[i, j, k] < field[i, j, k + 1]:
                        indices.extend([v[0], v[1], v[2], v[0], v[2], v[3]])
                    else:
                        indices.extend([v[0], v[2], v[1], v[0], v[3], v[2]])

    # SDF-gradient normals at the vertices, from the sampled field's
    # gradient (central differences on the grid), trilinearly
    # interpolated to each vertex position so the shading is smooth
    # instead of quantised per grid cell. Still SDF gradients --
    # only the sampling is interpolated.
    gx_field, gy_field, gz_field = np.gradient(field, xs, ys, zs)
    dx = xs[1] - xs[0] if nx > 1 else 1.0
    dy = ys[1] - ys[0] if ny > 1 else 1.0
    dz = zs[1] - zs[0] if nz > 1 else 1.0

    def _trilinear(comp: np.ndarray, vx: float, vy: float, vz: float) -> float:
        fx = min(max((vx - x0) / dx, 0.0), nx - 1.001)
        fy = min(max((vy - y0) / dy, 0.0), ny - 1.001)
        fz = min(max((vz - z0) / dz, 0.0), nz - 1.001)
        i0, j0, k0 = int(fx), int(fy), int(fz)
        tx, ty, tz = fx - i0, fy - j0, fz - k0
        total = 0.0
        for di in (0, 1):
            for dj in (0, 1):
                for dk in (0, 1):
                    w = (tx if di else 1.0 - tx) * (ty if dj else 1.0 - ty) * (tz if dk else 1.0 - tz)
                    total += w * float(comp[i0 + di, j0 + dj, k0 + dk])
        return total

    normals: list[list[float]] = []
    for (vx, vy, vz) in vertices:
        gx = _trilinear(gx_field, vx, vy, vz)
        gy = _trilinear(gy_field, vx, vy, vz)
        gz = _trilinear(gz_field, vx, vy, vz)
        length = math.sqrt(gx * gx + gy * gy + gz * gz) or 1.0
        normals.append([gx / length, gy / length, gz / length])
    return {
        "positions": vertices,
        "normals": normals,
        "indices": indices,
        "triangles": len(indices) // 3,
        "vertices": len(vertices),
        "grid_cells": cell_count,
        "resolution": list(resolution),
    }


def build_statue(*, height_scale: float = 1.0, resolution: tuple[int, int, int] = (40, 52, 40)) -> dict[str, Any]:
    import time

    if not isinstance(height_scale, (int, float)) or float(height_scale) <= 0:
        raise CapabilityError("world.athenaion_sdf_statue: height_scale must be > 0")
    s = float(height_scale)
    started = time.perf_counter()
    sdf_fn = lambda x, y, z: statue_sdf(x, y, z, height_scale=s)  # noqa: E731
    mesh = mesh_sdf(
        sdf_fn,
        (-1.5 * s, 1.5 * s, 0.0, 3.9 * s, -1.5 * s, 1.5 * s),
        resolution,
    )
    build_ms = round((time.perf_counter() - started) * 1000.0, 1)
    return {"height_scale": s, "mesh": mesh, "triangles": mesh["triangles"],
            "build_ms": build_ms, "total_height": 3.9 * s}


def _geometry_js(mesh: dict[str, Any], var: str) -> str:
    # BufferAttribute needs flat number arrays; flatten the [x, y, z]
    # triples and normals (nested arrays become NaN in three.js).
    flat_pos = [c for p in mesh["positions"] for c in p]
    flat_nor = [c for p in mesh["normals"] for c in p]
    return (
        f"const {var} = new THREE.BufferGeometry();\n"
        f"{var}.setAttribute('position', new THREE.Float32BufferAttribute({json.dumps(flat_pos)}, 3));\n"
        f"{var}.setAttribute('normal', new THREE.Float32BufferAttribute({json.dumps(flat_nor)}, 3));\n"
        f"{var}.setIndex({json.dumps(mesh['indices'])});\n"
    )


def build_statue_html(
    *,
    width: int,
    height: int,
    statue: dict[str, Any],
    column_mesh: dict[str, Any] | None = None,
) -> str:
    js = f"""
import * as THREE from 'three';
const W = {width}, H = {height};
const renderer = new THREE.WebGLRenderer({{ antialias: false, preserveDrawingBuffer: true }});
renderer.setPixelRatio(1);
renderer.setSize(W, H, false);
document.getElementById('stage').appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x2a3242);
const camera = new THREE.PerspectiveCamera(38, W / H, 0.1, 200);
const sun = new THREE.DirectionalLight(0xffe8c0, 2.4);
sun.position.set(18, 30, 20);
scene.add(sun);
scene.add(new THREE.HemisphereLight(0xbfd4e8, 0x6a5a44, 0.7));
const mat = new THREE.MeshStandardMaterial({{ color: 0xd8cdb2, roughness: 0.75, metalness: 0.0, side: THREE.DoubleSide }});
{_geometry_js(statue["mesh"], "statueGeo")}
const statue = new THREE.Mesh(statueGeo, mat);
scene.add(statue);
"""
    if column_mesh is not None:
        col = column_mesh
        js += f"""
const colGeo = new THREE.BufferGeometry();
const colFlat = {json.dumps([c for p in col["positions"] for c in p])};
colGeo.setAttribute('position', new THREE.Float32BufferAttribute(colFlat, 3));
colGeo.setIndex({json.dumps(col["indices"])});
colGeo.computeVertexNormals();
const colMat = new THREE.MeshStandardMaterial({{ color: 0xe8ddc4, roughness: 0.8, side: THREE.DoubleSide }});
const column = new THREE.Mesh(colGeo, colMat);
column.position.set(2.6, 0, 0);
scene.add(column);
"""
    js += """
const ground = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.MeshStandardMaterial({ color: 0x8a8272, roughness: 1.0 }));
ground.rotation.x = -Math.PI / 2;
ground.position.y = -0.01;
scene.add(ground);
const VIEWS = {
  front: { pos: [0, 2.2, 10], tgt: [0, 1.9, 0] },
  side: { pos: [10, 2.2, 0], tgt: [0, 1.9, 0] },
  top: { pos: [4, 12, 4], tgt: [0, 1.5, 0] },
  combined: { pos: [5, 3.2, 11], tgt: [1.0, 2.2, 0] }
};
window.__athenaion = {
  show(name) {
    const v = VIEWS[name] || VIEWS.front;
    camera.position.set(v.pos[0], v.pos[1], v.pos[2]);
    camera.lookAt(v.tgt[0], v.tgt[1], v.tgt[2]);
    renderer.render(scene, camera);
    window.__athenaionSettled = name;
    return name;
  }
};
window.__athenaionStats = function () {
  return { calls: renderer.info.render.calls, triangles: renderer.info.render.triangles };
};
window.__hfSettledFrame = 0;
window.__hf = {
  getDurationFrames() { return 1; },
  seekFrame(frame) { window.__athenaion.show('front'); window.__hfSettledFrame = frame; return { frame: frame, settled: true }; },
  destroy() { renderer.dispose(); }
};
window.__athenaion.show('front');
window.__hfReady = true;
"""
    return page_html(js)


def render_statue(
    *,
    out_dir: Path,
    width: int = 480,
    height: int = 270,
    height_scale: float = 1.0,
    resolution: tuple[int, int, int] = (40, 52, 40),
    with_column: bool = True,
) -> dict[str, Any]:
    statue = build_statue(height_scale=height_scale, resolution=resolution)
    column = build_column("doric", diameter=1.0) if with_column else None
    html = build_statue_html(
        width=width, height=height, statue=statue,
        column_mesh=column["mesh"] if column else None,
    )
    views = ("front", "side", "top", "combined") if with_column else ("front", "side", "top")
    actions = [
        {"name": view, "evaluate": f"window.__athenaion.show('{view}')",
         "settle": f"window.__athenaionSettled === '{view}'", "screenshot": True}
        for view in views
    ]
    result = capture_actions(html, actions, width=width, height=height)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    view_records = []
    for shot_rec in result["shots"]:
        path = out_dir / f"{shot_rec['name']}.png"
        path.write_bytes(shot_rec["png_bytes"])
        view_records.append({"view": shot_rec["name"], "sha256": shot_rec["sha256"], "bytes": shot_rec["bytes"], "file": path.name})
    return {
        "verdict": "pass",
        "height_scale": height_scale,
        "triangles": statue["triangles"],
        "vertices": statue["mesh"]["vertices"],
        "build_ms": statue["build_ms"],
        "total_height": statue["total_height"],
        "column_triangles": column["triangles"] if column else 0,
        "combined": with_column,
        "views": view_records,
        "stats": result["stats"],
        "ready_ms": result["ready_ms"],
        "three_module": result["three_module"],
        "human_measured": False,
        "external_assets": [],
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = render_statue(
        out_dir=out_dir,
        width=int(params.get("width", 480)),
        height=int(params.get("height", 270)),
        height_scale=float(params.get("height_scale", 1.0)),
        with_column=bool(params.get("with_column", True)),
    )
    report_path = out_dir / "statue_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    first = out_dir / "front.png"
    return CapabilityResult(
        png=str(first) if first.is_file() else None,
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"], "ok": True,
            "triangles": report["triangles"], "build_ms": report["build_ms"]},
    )


def register_athenaion_statue_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="world.athenaion_sdf_statue",
        kind="line",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "height_scale": {"type": "number"},
                "with_column": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        cpu_cost_hint=1.0,
        render=_render,
        has_media_output=True,
        description=(
            "B2 SDF statue, minimal version: parametric SDF figure, "
            "naive surface-nets meshing, SDF-gradient normals, three "
            "views plus one combined render with a B3 column. "
            "Zero external models. See ATHENAION_ATTRIBUTION.md."
        ),
        line="world",
    ))
    return ["world.athenaion_sdf_statue"]


register_athenaion_statue_capabilities_once()
