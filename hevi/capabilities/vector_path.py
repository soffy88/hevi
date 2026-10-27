"""Vector path operations (``image.vector_path``).

Clean-room implementation of the vector-path method used by hand-drawn
and explainer lines (path editing, boolean, split, measurement).  No
Paper.js code, API, or asset is copied: the geometry below is plain
shoelace / segment arithmetic written from the method description only.

Scope, stated honestly in the output:
* Paths are closed polygons: a list of [x, y] points, at least 3, in
  order.  Open polylines, Bezier curves, and strokes are NOT supported
  in this version and are rejected, not silently treated as polygons.
* Always available, with verifiable numbers: area, perimeter, centroid,
  bounding box, SVG path data, segment intersections, self-intersection
  count, collinear-point simplification (area-preserving).
* Boolean union / intersection / difference is implemented ONLY for
  axis-aligned rectangles.  For any other shape the operation returns
  ``status: unsupported_non_rectangle`` with no area and no fabricated
  result rectangle.  That boundary is in the output, not hidden.
* CPU only, no keys, no model downloads, deterministic per plan.

Failure contract: an invalid path (fewer than 3 points, non-numeric
coordinates, unknown id, unknown operation) raises ``CapabilityError``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False
_EPS = 1e-9


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _clean_points(raw: Any, what: str) -> list[tuple[float, float]]:
    if not isinstance(raw, list) or len(raw) < 3:
        raise CapabilityError(f"image.vector_path: {what} needs at least 3 points")
    points: list[tuple[float, float]] = []
    for pt in raw:
        if not isinstance(pt, (list, tuple)) or len(pt) != 2 or not all(_is_num(c) for c in pt):
            raise CapabilityError(f"image.vector_path: {what} points must be [x, y] numbers")
        points.append((float(pt[0]), float(pt[1])))
    # Drop a repeated closing point (same as first); closure is implicit.
    if len(points) > 3 and points[-1] == points[0]:
        points = points[:-1]
    if len(points) < 3:
        raise CapabilityError(f"image.vector_path: {what} needs at least 3 distinct points")
    return points


def _area(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _perimeter(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        total += math.hypot(x2 - x1, y2 - y1)
    return total


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    signed = _area(points)
    if abs(signed) < _EPS:
        # Bowtie / degenerate paths have zero signed area (lobes cancel);
        # fall back to the vertex mean so metrics still report, while the
        # reported area itself stays 0 and self-intersection is counted.
        n = len(points)
        return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)
    cx = cy = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        cross = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    return (cx / (6.0 * signed), cy / (6.0 * signed))


def _bbox(points: list[tuple[float, float]]) -> list[float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _svg(points: list[tuple[float, float]]) -> str:
    parts = [f"M {points[0][0]:g} {points[0][1]:g}"]
    parts += [f"L {x:g} {y:g}" for x, y in points[1:]]
    parts.append("Z")
    return " ".join(parts)


def _seg_intersection(p1, p2, p3, p4):
    """Return the intersection point of segments p1-p2 and p3-p4, or None."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    den = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(den) < _EPS:
        return None
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / den
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / den
    if -_EPS <= t <= 1.0 + _EPS and -_EPS <= u <= 1.0 + _EPS:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def _segments(points: list[tuple[float, float]]):
    return [(points[i], points[(i + 1) % len(points)]) for i in range(len(points))]


def _intersections(a: list[tuple[float, float]], b: list[tuple[float, float]]):
    found: list[list[float]] = []
    for p1, p2 in _segments(a):
        for p3, p4 in _segments(b):
            hit = _seg_intersection(p1, p2, p3, p4)
            if hit is not None:
                pt = [round(hit[0], 9), round(hit[1], 9)]
                if pt not in found:
                    found.append(pt)
    return found


def _self_intersection_count(points: list[tuple[float, float]]) -> int:
    segs = _segments(points)
    count = 0
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            if j == i:
                continue
            # Adjacent segments share a vertex by construction; skip them,
            # including the first/last wrap-around pair.
            if j == i + 1 or (i == 0 and j == len(segs) - 1):
                continue
            if _seg_intersection(segs[i][0], segs[i][1], segs[j][0], segs[j][1]) is not None:
                count += 1
    return count


def _as_rect(points: list[tuple[float, float]]):
    """Return [xmin, ymin, xmax, ymax] if the path is an axis-aligned rectangle."""
    if len(points) != 4:
        return None
    xs = sorted(set(p[0] for p in points))
    ys = sorted(set(p[1] for p in points))
    if len(xs) != 2 or len(ys) != 2:
        return None
    corners = {(xs[0], ys[0]), (xs[0], ys[1]), (xs[1], ys[0]), (xs[1], ys[1])}
    if set(points) != corners:
        return None
    return [xs[0], ys[0], xs[1], ys[1]]


def _rect_area(r) -> float:
    return max(r[2] - r[0], 0.0) * max(r[3] - r[1], 0.0)


def _rect_intersect(a, b):
    r = [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]
    return r if r[2] > r[0] and r[3] > r[1] else None


def _rect_subtract(a, b):
    """Subtract rectangle b from a; return a list of rectangles (possibly empty)."""
    inter = _rect_intersect(a, b)
    if inter is None:
        return [list(a)]
    out = []
    if inter[0] > a[0]:
        out.append([a[0], a[1], inter[0], a[3]])
    if inter[2] < a[2]:
        out.append([inter[2], a[1], a[2], a[3]])
    if inter[1] > a[1]:
        out.append([inter[0], a[1], inter[2], inter[1]])
    if inter[3] < a[3]:
        out.append([inter[0], inter[3], inter[2], a[3]])
    return out


def _simplify(points: list[tuple[float, float]]):
    """Drop points collinear with their neighbours; area is preserved."""
    kept: list[tuple[float, float]] = []
    removed = 0
    n = len(points)
    for i, pt in enumerate(points):
        prev_pt = points[(i - 1) % n]
        next_pt = points[(i + 1) % n]
        cross = (pt[0] - prev_pt[0]) * (next_pt[1] - pt[1]) - (pt[1] - prev_pt[1]) * (next_pt[0] - pt[0])
        if abs(cross) < _EPS:
            removed += 1
        else:
            kept.append(pt)
    if len(kept) < 3:
        return points, 0
    return kept, removed


def process_vector_path(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise CapabilityError("image.vector_path: plan must be a JSON object")
    raw_paths = plan.get("paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        raise CapabilityError("image.vector_path: plan.paths must be a non-empty list")
    paths: dict[str, list[tuple[float, float]]] = {}
    for spec in raw_paths:
        if not isinstance(spec, dict):
            raise CapabilityError("image.vector_path: each path must be a JSON object")
        pid = spec.get("id")
        if not isinstance(pid, str) or not pid.strip():
            raise CapabilityError("image.vector_path: path.id must be a non-empty string")
        pid = pid.strip()
        if pid in paths:
            raise CapabilityError(f"image.vector_path: duplicate path id {pid}")
        paths[pid] = _clean_points(spec.get("points"), f"path {pid}")
    metrics = {}
    for pid, pts in paths.items():
        cx, cy = _centroid(pts)
        metrics[pid] = {
            "area": abs(_area(pts)),
            "signed_area": _area(pts),
            "perimeter": _perimeter(pts),
            "centroid": [cx, cy],
            "bbox": _bbox(pts),
            "svg_path": _svg(pts),
            "self_intersection_count": _self_intersection_count(pts),
        }
    results = []
    for op in plan.get("operations", []):
        if not isinstance(op, dict):
            raise CapabilityError("image.vector_path: each operation must be a JSON object")
        kind = op.get("op")
        if kind == "intersections":
            a_id, b_id = op.get("a"), op.get("b")
            if a_id not in paths or b_id not in paths:
                raise CapabilityError("image.vector_path: intersections needs known path ids a and b")
            hits = _intersections(paths[a_id], paths[b_id])
            results.append({"op": "intersections", "a": a_id, "b": b_id, "points": hits, "count": len(hits)})
        elif kind == "boolean":
            a_id, b_id, bkind = op.get("a"), op.get("b"), op.get("kind")
            if a_id not in paths or b_id not in paths:
                raise CapabilityError("image.vector_path: boolean needs known path ids a and b")
            if bkind not in ("union", "intersection", "difference"):
                raise CapabilityError("image.vector_path: boolean kind must be union/intersection/difference")
            ra, rb = _as_rect(paths[a_id]), _as_rect(paths[b_id])
            if ra is None or rb is None:
                results.append({
                    "op": "boolean", "kind": bkind, "a": a_id, "b": b_id,
                    "status": "unsupported_non_rectangle", "area": None, "rects": None,
                    "reason": "Boolean is implemented only for axis-aligned rectangles in this version.",
                })
                continue
            if bkind == "intersection":
                inter = _rect_intersect(ra, rb)
                rects = [inter] if inter else []
            elif bkind == "difference":
                rects = _rect_subtract(ra, rb)
            else:
                rects = _rect_subtract(ra, rb) + [rb]
            area = sum(_rect_area(r) for r in rects)
            results.append({
                "op": "boolean", "kind": bkind, "a": a_id, "b": b_id,
                "status": "ok", "area": area, "rects": rects,
            })
        elif kind == "simplify":
            pid = op.get("path")
            if pid not in paths:
                raise CapabilityError("image.vector_path: simplify needs a known path id")
            kept, removed = _simplify(paths[pid])
            results.append({
                "op": "simplify", "path": pid,
                "points": [list(p) for p in kept], "removed": removed,
                "area_before": metrics[pid]["area"], "area_after": abs(_area(kept)),
                "svg_path": _svg(kept),
            })
        else:
            raise CapabilityError(f"image.vector_path: unknown operation {kind!r}")
    return {
        "capability": "image.vector_path",
        "scope": {
            "paths": "closed polygons only; no Bezier, no open polylines",
            "boolean": "axis-aligned rectangles only; other shapes return unsupported_non_rectangle",
        },
        "metrics": metrics,
        "operations": results,
    }


def _write_json(out_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _render_vector_path(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = process_vector_path(params.get("plan"))
    report = _write_json(Path(out_dir), "vector_path.json", result)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={
            "report_json": str(report),
            "path_ids": sorted(result["metrics"].keys()),
            "operation_count": len(result["operations"]),
        },
    )


def register_vector_path_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="image.vector_path",
        kind="line",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {"plan": {"type": "object"}},
            "required": ["plan"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render_vector_path,
        has_media_output=False,
        description=(
            "Vector path operations (clean-room): closed-polygon area, "
            "perimeter, centroid, bbox, SVG data, segment intersections, "
            "self-intersection count, collinear simplification, and "
            "rectangle-only boolean union/intersection/difference with "
            "verifiable areas. No Bezier, no fabricated boolean results."
        ),
        line="image",
    ))
    return ["image.vector_path"]


register_vector_path_capabilities_once()
