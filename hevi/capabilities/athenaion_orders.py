"""B3 parametric classical orders library (clean-room, method only).

Method source: Athenaion's parametric column/order construction
as described in ``hevi-vs-athenaion.md``; see
ATHENAION_ATTRIBUTION.md. All geometry here is newly written
Python that emits plain position/index buffers: a fluted shaft
with entasis, a capital per order, a base, and an entablature
segment with triglyphs. No Athenaion code, mesh, or measurement
is used; every dimension is a caller-supplied parameter with a
documented default that is this module's own choice.

Orders: doric, ionic, corinthian. Each order fixes its own
proportions (shaft height in diameters, flute count, capital
form, entablature height); changing a dimension rebuilds the
geometry, and the footprint rectangle follows the column so a
row of columns can be checked for overlap before rendering.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from hevi.capabilities.athenaion_browser import capture_actions, page_html
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

ORDERS = ("doric", "ionic", "corinthian")

# Proportions are this module's own parameters, not measured claims.
ORDER_PARAMS: dict[str, dict[str, Any]] = {
    "doric": {
        "shaft_height_diameters": 6.0, "flutes": 20, "flute_depth": 0.055,
        "entasis": 0.05, "capital": "echinus", "entablature_diameters": 1.9,
        "has_base": False,
    },
    "ionic": {
        "shaft_height_diameters": 8.0, "flutes": 24, "flute_depth": 0.045,
        "entasis": 0.04, "capital": "volute", "entablature_diameters": 1.7,
        "has_base": True,
    },
    "corinthian": {
        "shaft_height_diameters": 9.0, "flutes": 24, "flute_depth": 0.04,
        "entasis": 0.035, "capital": "acanthus", "entablature_diameters": 1.7,
        "has_base": True,
    },
}


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _box(cx: float, cy: float, cz: float, sx: float, sy: float, sz: float) -> dict[str, Any]:
    """Axis-aligned box centred at (cx, cy, cz), as a mesh dict."""
    hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0
    corners = np.array([
        [cx - hx, cy - hy, cz - hz], [cx + hx, cy - hy, cz - hz],
        [cx + hx, cy + hy, cz - hz], [cx - hx, cy + hy, cz - hz],
        [cx - hx, cy - hy, cz + hz], [cx + hx, cy - hy, cz + hz],
        [cx + hx, cy + hy, cz + hz], [cx - hx, cy + hy, cz + hz],
    ], dtype=float)
    faces = [
        (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
        (2, 6, 7, 3), (0, 3, 7, 4), (1, 5, 6, 2),
    ]
    positions: list[list[float]] = []
    indices: list[int] = []
    for face in faces:
        base = len(positions)
        for idx in face:
            positions.append([float(v) for v in corners[idx]])
        indices.extend([base, base + 1, base + 2, base, base + 2, base + 3])
    return {"positions": positions, "indices": indices}


def _lathe(profile: list[tuple[float, float]], segments: int, y0: float = 0.0) -> dict[str, Any]:
    """Surface of revolution around Y from (radius, y) profile points."""
    positions: list[list[float]] = []
    indices: list[int] = []
    for radius, y in profile:
        for s in range(segments + 1):
            a = 2.0 * math.pi * s / segments
            positions.append([radius * math.cos(a), y0 + y, radius * math.sin(a)])
    ring = segments + 1
    for r in range(len(profile) - 1):
        for s in range(segments):
            a, b = r * ring + s, (r + 1) * ring + s
            indices.extend([a, b, a + 1, a + 1, b, b + 1])
    return {"positions": positions, "indices": indices}


def _merge(meshes: list[dict[str, Any]]) -> dict[str, Any]:
    positions: list[list[float]] = []
    indices: list[int] = []
    for mesh in meshes:
        base = len(positions)
        positions.extend(mesh["positions"])
        indices.extend(i + base for i in mesh["indices"])
    return {"positions": positions, "indices": indices, "triangles": len(indices) // 3}


def shaft_radius(order: str, diameter: float, y: float, shaft_height: float, theta: float) -> float:
    """Entasis profile with flute grooves at angle theta."""
    spec = ORDER_PARAMS[order]
    frac = y / shaft_height if shaft_height > 0 else 0.0
    base_r = diameter / 2.0
    # Entasis: gentle swell peaking near one third of the height.
    bulge = 1.0 + spec["entasis"] * math.exp(-((frac - 0.33) / 0.45) ** 2)
    # Taper: slightly narrower at the top (kept weaker than the swell
    # so the entasis profile still reads as a swell at one third).
    taper = 1.0 - 0.04 * frac
    groove = (0.5 + 0.5 * math.cos(spec["flutes"] * theta)) ** 2
    return base_r * bulge * taper * (1.0 - spec["flute_depth"] * groove)


def build_shaft(order: str, diameter: float, shaft_height: float) -> dict[str, Any]:
    rings, segments = 25, 48
    positions: list[list[float]] = []
    indices: list[int] = []
    for r in range(rings):
        y = shaft_height * r / (rings - 1)
        for s in range(segments + 1):
            theta = 2.0 * math.pi * s / segments
            rad = shaft_radius(order, diameter, y, shaft_height, theta)
            positions.append([rad * math.cos(theta), y, rad * math.sin(theta)])
    ring = segments + 1
    for r in range(rings - 1):
        for s in range(segments):
            a, b = r * ring + s, (r + 1) * ring + s
            indices.extend([a, b, a + 1, a + 1, b, b + 1])
    return {"positions": positions, "indices": indices}


def build_column(order: str, *, diameter: float = 1.0, height_scale: float = 1.0) -> dict[str, Any]:
    """One parametric column. Returns mesh + footprint + dimensions."""
    if order not in ORDERS:
        raise CapabilityError(f"world.athenaion_classical_orders: unknown order {order!r}; known: {list(ORDERS)}")
    if not _is_num(diameter) or float(diameter) <= 0:
        raise CapabilityError("world.athenaion_classical_orders: diameter must be > 0")
    if not _is_num(height_scale) or float(height_scale) <= 0:
        raise CapabilityError("world.athenaion_classical_orders: height_scale must be > 0")
    spec = ORDER_PARAMS[order]
    diameter = float(diameter)
    shaft_h = spec["shaft_height_diameters"] * diameter * float(height_scale)
    parts: list[dict[str, Any]] = []
    y = 0.0
    if spec["has_base"]:
        parts.append(_box(0, 0.06, 0, diameter * 1.3, 0.12, diameter * 1.3))
        parts.append(_lathe([(diameter * 0.62, 0.12), (diameter * 0.55, 0.22), (diameter * 0.52, 0.30)], 32, y0=0.0))
        y = 0.30
    shaft = build_shaft(order, diameter, shaft_h)
    shaft["positions"] = [[x, yy + y, z] for x, yy, z in shaft["positions"]]
    parts.append(shaft)
    cap_y = y + shaft_h
    if spec["capital"] == "echinus":
        parts.append(_lathe(
            [(diameter * 0.44, 0.0), (diameter * 0.58, 0.10), (diameter * 0.62, 0.20)],
            32, y0=cap_y,
        ))
        parts.append(_box(0, cap_y + 0.28, 0, diameter * 1.3, 0.16, diameter * 1.3))
        top_y = cap_y + 0.36
    elif spec["capital"] == "volute":
        parts.append(_box(0, cap_y + 0.10, 0, diameter * 1.15, 0.20, diameter * 0.9))
        for side in (-1.0, 1.0):
            parts.append(_lathe([(diameter * 0.20, 0.0), (diameter * 0.20, 0.06)], 20, y0=cap_y + 0.02))
            scroll = _box(side * diameter * 0.52, cap_y + 0.10, 0, diameter * 0.28, diameter * 0.28, diameter * 0.28)
            parts.append(scroll)
        parts.append(_box(0, cap_y + 0.28, 0, diameter * 1.25, 0.12, diameter * 1.15))
        top_y = cap_y + 0.34
    else:  # acanthus
        parts.append(_lathe(
            [(diameter * 0.46, 0.0), (diameter * 0.52, 0.18), (diameter * 0.48, 0.34)],
            32, y0=cap_y,
        ))
        for k in range(8):
            a = 2.0 * math.pi * k / 8
            leaf = _box(
                math.cos(a) * diameter * 0.48, cap_y + 0.16, math.sin(a) * diameter * 0.48,
                diameter * 0.12, diameter * 0.30, diameter * 0.12,
            )
            parts.append(leaf)
        parts.append(_box(0, cap_y + 0.42, 0, diameter * 1.25, 0.12, diameter * 1.25))
        top_y = cap_y + 0.48
    mesh = _merge(parts)
    half = diameter * 0.75
    return {
        "order": order,
        "diameter": diameter,
        "height_scale": float(height_scale),
        "shaft_height": shaft_h,
        "total_height": top_y,
        "mesh": mesh,
        "triangles": mesh["triangles"],
        "footprint": {"x_min": -half, "x_max": half, "z_min": -half, "z_max": half},
        "capital": spec["capital"],
    }


def build_entablature(order: str, *, diameter: float = 1.0, bays: int = 2) -> dict[str, Any]:
    """Architrave + triglyph frieze + cornice spanning ``bays`` columns."""
    if order not in ORDERS:
        raise CapabilityError(f"world.athenaion_classical_orders: unknown order {order!r}")
    if not isinstance(bays, int) or bays < 1:
        raise CapabilityError("world.athenaion_classical_orders: bays must be a positive integer")
    spec = ORDER_PARAMS[order]
    height = spec["entablature_diameters"] * float(diameter)
    span = bays * 3.0 * float(diameter)
    parts = [
        _box(0, height * 0.18, 0, span, height * 0.36, diameter * 1.1),
        _box(0, height * 0.55, 0, span, height * 0.38, diameter * 1.15),
        _box(0, height * 0.88, 0, span, height * 0.24, diameter * 1.3),
    ]
    # Triglyphs: raised blocks across the frieze band.
    count = max(1, int(span / (diameter * 0.9)))
    for k in range(count):
        x = -span / 2.0 + (k + 0.5) * span / count
        parts.append(_box(x, height * 0.55, diameter * 0.58, diameter * 0.34, height * 0.34, 0.06))
    mesh = _merge(parts)
    return {"order": order, "bays": bays, "height": height, "span": span, "mesh": mesh, "triangles": mesh["triangles"]}


def build_colonnade(order: str, *, count: int = 3, spacing: float = 3.0, diameter: float = 1.0) -> dict[str, Any]:
    """A row of columns; footprints must not overlap."""
    if not isinstance(count, int) or count < 1:
        raise CapabilityError("world.athenaion_classical_orders: count must be a positive integer")
    if not _is_num(spacing) or float(spacing) <= 0:
        raise CapabilityError("world.athenaion_classical_orders: spacing must be > 0")
    column = build_column(order, diameter=diameter)
    footprints = []
    for k in range(count):
        cx = (k - (count - 1) / 2.0) * float(spacing)
        fp = column["footprint"]
        footprints.append({
            "x_min": fp["x_min"] + cx, "x_max": fp["x_max"] + cx,
            "z_min": fp["z_min"], "z_max": fp["z_max"], "center_x": cx,
        })
    overlaps: list[dict[str, Any]] = []
    for i in range(len(footprints)):
        for j in range(i + 1, len(footprints)):
            a, b = footprints[i], footprints[j]
            if a["x_min"] < b["x_max"] and b["x_min"] < a["x_max"] and a["z_min"] < b["z_max"] and b["z_min"] < a["z_max"]:
                overlaps.append({"a": i, "b": j})
    return {
        "order": order, "count": count, "spacing": float(spacing),
        "column": column, "footprints": footprints,
        "footprints_overlap": overlaps,
        "footprints_ok": not overlaps,
    }


def _geometry_js(mesh: dict[str, Any], var: str) -> str:
    # BufferAttribute needs a flat number array; the mesh dicts store
    # [x, y, z] triples, so flatten here (nested arrays become NaN).
    flat = [c for p in mesh["positions"] for c in p]
    return (
        f"const {var} = new THREE.BufferGeometry();\n"
        f"{var}.setAttribute('position', new THREE.Float32BufferAttribute({json.dumps(flat)}, 3));\n"
        f"{var}.setIndex({json.dumps(mesh['indices'])});\n"
        f"{var}.computeVertexNormals();\n"
    )


def build_orders_html(*, width: int, height: int, colonnade: dict[str, Any], entablature: dict[str, Any] | None, view: str = "front") -> str:
    column = colonnade["column"]
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
const mat = new THREE.MeshStandardMaterial({{ color: 0xe8ddc4, roughness: 0.8, metalness: 0.0, side: THREE.DoubleSide }});
const trimMat = new THREE.MeshStandardMaterial({{ color: 0xc8b890, roughness: 0.75, side: THREE.DoubleSide }});
{_geometry_js(column["mesh"], "colGeo")}
const COUNT = {colonnade["count"]}, SPACING = {colonnade["spacing"]!r};
for (let k = 0; k < COUNT; k++) {{
  const m = new THREE.Mesh(colGeo, mat);
  m.position.x = (k - (COUNT - 1) / 2) * SPACING;
  scene.add(m);
}}
"""
    if entablature is not None:
        js += f"""
{_geometry_js(entablature["mesh"], "entGeo")}
const ent = new THREE.Mesh(entGeo, trimMat);
ent.position.y = {column["total_height"]!r};
scene.add(ent);
"""
    js += f"""
const ground = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.MeshStandardMaterial({{ color: 0x8a8272, roughness: 1.0 }}));
ground.rotation.x = -Math.PI / 2;
ground.position.y = -0.01;
scene.add(ground);
const VIEWS = {{
  front: {{ pos: [0, {column["total_height"] * 0.55!r}, 16], tgt: [0, {column["total_height"] * 0.5!r}, 0] }},
  side: {{ pos: [16, {column["total_height"] * 0.55!r}, 0], tgt: [0, {column["total_height"] * 0.5!r}, 0] }},
  top: {{ pos: [6, 20, 6], tgt: [0, {column["total_height"] * 0.4!r}, 0] }}
}};
window.__athenaion = {{
  show(name) {{
    const v = VIEWS[name] || VIEWS.front;
    camera.position.set(v.pos[0], v.pos[1], v.pos[2]);
    camera.lookAt(v.tgt[0], v.tgt[1], v.tgt[2]);
    renderer.render(scene, camera);
    window.__athenaionSettled = name;
    return name;
  }}
}};
window.__athenaionStats = function () {{
  return {{ calls: renderer.info.render.calls, triangles: renderer.info.render.triangles }};
}};
window.__hfSettledFrame = 0;
window.__hf = {{
  getDurationFrames() {{ return 1; }},
  seekFrame(frame) {{ window.__athenaion.show('front'); window.__hfSettledFrame = frame; return {{ frame: frame, settled: true }}; }},
  destroy() {{ renderer.dispose(); }}
}};
window.__athenaion.show('{view}');
window.__hfReady = true;
"""
    return page_html(js)


def render_colonnade(
    *,
    order: str = "doric",
    out_dir: Path,
    width: int = 480,
    height: int = 270,
    diameter: float = 1.0,
    height_scale: float = 1.0,
    count: int = 3,
    with_entablature: bool = True,
) -> dict[str, Any]:
    colonnade = build_colonnade(order, count=count, diameter=diameter)
    if height_scale != 1.0:
        colonnade["column"] = build_column(order, diameter=diameter, height_scale=height_scale)
    if not colonnade["footprints_ok"]:
        raise CapabilityError("world.athenaion_classical_orders: footprints overlap; spacing too small for the diameter")
    entablature = build_entablature(order, diameter=diameter, bays=max(1, count - 1)) if with_entablature else None
    html = build_orders_html(width=width, height=height, colonnade=colonnade, entablature=entablature)
    actions = [
        {"name": view, "evaluate": f"window.__athenaion.show('{view}')",
         "settle": f"window.__athenaionSettled === '{view}'", "screenshot": True}
        for view in ("front", "side", "top")
    ]
    result = capture_actions(html, actions, width=width, height=height)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    views = []
    for shot_rec in result["shots"]:
        path = out_dir / f"{shot_rec['name']}.png"
        path.write_bytes(shot_rec["png_bytes"])
        views.append({"view": shot_rec["name"], "sha256": shot_rec["sha256"], "bytes": shot_rec["bytes"], "file": path.name})
    return {
        "verdict": "pass",
        "order": order,
        "diameter": diameter,
        "height_scale": height_scale,
        "column_triangles": colonnade["column"]["triangles"],
        "total_height": colonnade["column"]["total_height"],
        "entablature_triangles": entablature["triangles"] if entablature else 0,
        "footprints": colonnade["footprints"],
        "footprints_ok": colonnade["footprints_ok"],
        "views": views,
        "stats": result["stats"],
        "ready_ms": result["ready_ms"],
        "three_module": result["three_module"],
        "human_measured": False,
        "external_assets": [],
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = render_colonnade(
        order=str(params.get("order", "doric")),
        out_dir=out_dir,
        width=int(params.get("width", 480)),
        height=int(params.get("height", 270)),
        diameter=float(params.get("diameter", 1.0)),
        height_scale=float(params.get("height_scale", 1.0)),
        count=int(params.get("count", 3)),
        with_entablature=bool(params.get("with_entablature", True)),
    )
    report_path = out_dir / "orders_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    first = out_dir / "front.png"
    return CapabilityResult(
        png=str(first) if first.is_file() else None,
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"], "ok": True,
            "footprints_ok": report["footprints_ok"], "column_triangles": report["column_triangles"]},
    )


def register_athenaion_orders_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="world.athenaion_classical_orders",
        kind="line",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {
                "order": {"type": "string"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "diameter": {"type": "number"},
                "height_scale": {"type": "number"},
                "count": {"type": "integer"},
                "with_entablature": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        cpu_cost_hint=1.0,
        render=_render,
        has_media_output=True,
        description=(
            "B3 parametric classical orders: fluted entasis shafts, "
            "per-order capitals, entablature with triglyphs, footprint "
            "no-overlap check, three-view render. Zero external assets. "
            "See ATHENAION_ATTRIBUTION.md."
        ),
        line="world",
    ))
    return ["world.athenaion_classical_orders"]


register_athenaion_orders_capabilities_once()
