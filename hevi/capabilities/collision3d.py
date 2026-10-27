"""3D collision checking (``scene3d.collision_check``).

Clean-room implementation of the 3D-collision method a renderer-only
Three.js line is missing: deterministic AABB / sphere overlap and
penetration reporting, plus a linear swept time-of-impact for
translating objects.  No Rapier code, WASM, or API is copied.

Scope, stated honestly in the output:
* AABBs and spheres only, translation only.  No rotation, no oriented
  boxes, no meshes, no rigid-body dynamics, no friction, no impulse:
  this capability REPORTS collisions and penetration, it does not
  simulate a physics world.  Blender-side 3D physics remains the route
  for full rigid-body simulation.
* ``normal`` is the separation direction for the FIRST object in the
  pair (push the first object along it to separate).  For a sphere
  inside an AABB it is the nearest-face outward direction.
* Time-of-impact is a linear slab / quadratic solve over the relative
  velocity within ``max_time``; ``null`` means no impact in that window,
  never a fabricated time.
* CPU only, no keys, no model downloads, deterministic per plan.

Failure contract: an invalid object (unknown kind, non-positive size,
bad vector length, duplicate id, negative max_time) raises
``CapabilityError``.
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


def _vec(value: Any, what: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3 or not all(_is_num(v) for v in value):
        raise CapabilityError(f"scene3d.collision_check: {what} must be a 3-number vector")
    return float(value[0]), float(value[1]), float(value[2])


def _unit(v: tuple[float, float, float]) -> tuple[float, float, float]:
    n = math.sqrt(sum(c * c for c in v))
    if n < _EPS:
        return (1.0, 0.0, 0.0)
    return tuple(c / n for c in v)


class _Obj:
    def __init__(self, spec: dict[str, Any]) -> None:
        if not isinstance(spec, dict):
            raise CapabilityError("scene3d.collision_check: each object must be a JSON object")
        obj_id = spec.get("id")
        if not isinstance(obj_id, str) or not obj_id.strip():
            raise CapabilityError("scene3d.collision_check: object.id must be a non-empty string")
        self.id = obj_id.strip()
        kind = spec.get("kind")
        if kind not in ("aabb", "sphere"):
            raise CapabilityError(
                f"scene3d.collision_check: object {self.id} kind must be 'aabb' or 'sphere'"
            )
        self.kind = kind
        self.center = _vec(spec.get("center", [0.0, 0.0, 0.0]), f"object {self.id} center")
        vel = spec.get("velocity", [0.0, 0.0, 0.0])
        self.velocity = _vec(vel, f"object {self.id} velocity")
        if kind == "aabb":
            size = _vec(spec.get("size"), f"object {self.id} size")
            if any(s <= 0 for s in size):
                raise CapabilityError(f"scene3d.collision_check: object {self.id} size must be > 0")
            self.size = size
            self.radius = 0.0
        else:
            radius = spec.get("radius")
            if not _is_num(radius) or float(radius) <= 0:
                raise CapabilityError(f"scene3d.collision_check: object {self.id} radius must be > 0")
            self.radius = float(radius)
            self.size = (0.0, 0.0, 0.0)

    def aabb_min(self) -> tuple[float, float, float]:
        if self.kind == "aabb":
            return tuple(c - s / 2.0 for c, s in zip(self.center, self.size))
        return tuple(c - self.radius for c in self.center)

    def aabb_max(self) -> tuple[float, float, float]:
        if self.kind == "aabb":
            return tuple(c + s / 2.0 for c, s in zip(self.center, self.size))
        return tuple(c + self.radius for c in self.center)


def _slab_toi(lo: tuple[float, float, float], hi: tuple[float, float, float],
              origin: tuple[float, float, float], vel: tuple[float, float, float],
              max_time: float) -> float | None:
    """Earliest t in [0, max_time] where a point enters the box, else None."""
    t_enter, t_exit = 0.0, max_time
    for axis in range(3):
        if abs(vel[axis]) < _EPS:
            if origin[axis] < lo[axis] or origin[axis] > hi[axis]:
                return None
            continue
        t1 = (lo[axis] - origin[axis]) / vel[axis]
        t2 = (hi[axis] - origin[axis]) / vel[axis]
        if t1 > t2:
            t1, t2 = t2, t1
        t_enter = max(t_enter, t1)
        t_exit = min(t_exit, t2)
        if t_enter > t_exit:
            return None
    if t_exit < 0 or t_enter > max_time:
        return None
    return max(t_enter, 0.0)


def _pair(a: _Obj, b: _Obj, max_time: float) -> dict[str, Any]:
    colliding = False
    penetration = 0.0
    normal: tuple[float, float, float] = (1.0, 0.0, 0.0)
    distance = 0.0
    toi: float | None = None
    rel = tuple(b.velocity[i] - a.velocity[i] for i in range(3))
    if a.kind == "aabb" and b.kind == "aabb":
        amin, amax = a.aabb_min(), a.aabb_max()
        bmin, bmax = b.aabb_min(), b.aabb_max()
        overlaps = []
        separated = False
        for axis in range(3):
            ov = min(amax[axis], bmax[axis]) - max(amin[axis], bmin[axis])
            overlaps.append(ov)
            if ov < -_EPS:
                separated = True
        if not separated:
            colliding = True
            axis = min(range(3), key=lambda i: overlaps[i])
            penetration = max(overlaps[axis], 0.0)
            sign = 1.0 if b.center[axis] >= a.center[axis] else -1.0
            normal = tuple(sign if i == axis else 0.0 for i in range(3))
            distance = 0.0
            toi = 0.0
        else:
            # Gap along the most separated axis, for reporting only.
            distance = max(-ov for ov in overlaps if ov < 0)
            # Swept AABB vs AABB: move b relative to a, slab against a's box
            # expanded by b's half-size.
            half_b = tuple(s / 2.0 for s in b.size)
            lo = tuple(amin[i] - half_b[i] for i in range(3))
            hi = tuple(amax[i] + half_b[i] for i in range(3))
            toi = _slab_toi(lo, hi, b.center, tuple(-v for v in rel), max_time)
    elif a.kind == "sphere" and b.kind == "sphere":
        d = tuple(b.center[i] - a.center[i] for i in range(3))
        dist = math.sqrt(sum(c * c for c in d))
        total_r = a.radius + b.radius
        if dist <= total_r + _EPS:
            colliding = True
            penetration = max(total_r - dist, 0.0)
            normal = _unit(d)
            distance = dist
            toi = 0.0
        else:
            distance = dist
            # Solve |d + rel*t|^2 = total_r^2
            vv = sum(c * c for c in rel)
            if vv > _EPS:
                dv = sum(d[i] * rel[i] for i in range(3))
                disc = dv * dv - vv * (dist * dist - total_r * total_r)
                if disc >= 0:
                    t = (-dv - math.sqrt(disc)) / vv
                    if 0.0 <= t <= max_time:
                        toi = t
    else:
        sphere, box = (a, b) if a.kind == "sphere" else (b, a)
        sphere_is_a = a.kind == "sphere"
        bmin, bmax = box.aabb_min(), box.aabb_max()
        closest = tuple(min(max(sphere.center[i], bmin[i]), bmax[i]) for i in range(3))
        dvec = tuple(sphere.center[i] - closest[i] for i in range(3))
        dist = math.sqrt(sum(c * c for c in dvec))
        inside = all(bmin[i] <= sphere.center[i] <= bmax[i] for i in range(3))
        if inside or dist <= sphere.radius + _EPS:
            colliding = True
            if inside:
                # Nearest face outward direction (for the sphere).
                gaps = []
                for axis in range(3):
                    gaps.append((sphere.center[axis] - bmin[axis], axis, -1.0))
                    gaps.append((bmax[axis] - sphere.center[axis], axis, 1.0))
                gap, axis, sign = min(gaps, key=lambda t: t[0])
                penetration = sphere.radius + gap
                sep = tuple(sign if i == axis else 0.0 for i in range(3))
            else:
                penetration = max(sphere.radius - dist, 0.0)
                sep = _unit(dvec)
            normal = sep if sphere_is_a else tuple(-c for c in sep)
            distance = 0.0 if inside else dist
            toi = 0.0
        else:
            distance = dist
            # Swept sphere centre against the box expanded by radius.
            lo = tuple(bmin[i] - sphere.radius for i in range(3))
            hi = tuple(bmax[i] + sphere.radius for i in range(3))
            rel_sphere = tuple(
                (a.velocity[i] - b.velocity[i]) if sphere_is_a else (b.velocity[i] - a.velocity[i])
                for i in range(3)
            )
            toi = _slab_toi(lo, hi, sphere.center, rel_sphere, max_time)
    return {
        "a": a.id,
        "b": b.id,
        "colliding": colliding,
        "penetration": penetration,
        "normal": list(normal),
        "distance": distance,
        "time_of_impact": toi,
    }


def check_collision3d(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise CapabilityError("scene3d.collision_check: plan must be a JSON object")
    raw = plan.get("objects")
    if not isinstance(raw, list) or not raw:
        raise CapabilityError("scene3d.collision_check: plan.objects must be a non-empty list")
    objects = [_Obj(spec) for spec in raw]
    ids = [o.id for o in objects]
    if len(set(ids)) != len(ids):
        raise CapabilityError("scene3d.collision_check: object ids must be unique")
    max_time = plan.get("max_time", 1.0)
    if not _is_num(max_time) or float(max_time) < 0:
        raise CapabilityError("scene3d.collision_check: plan.max_time must be >= 0")
    max_time = float(max_time)
    pairs = []
    for i in range(len(objects)):
        for j in range(i + 1, len(objects)):
            pairs.append(_pair(objects[i], objects[j], max_time))
    colliding_pairs = [p for p in pairs if p["colliding"]]
    return {
        "capability": "scene3d.collision_check",
        "scope": {
            "kinds": ["aabb", "sphere"],
            "rotation": False,
            "dynamics": False,
            "note": "Reports overlap, penetration and linear time-of-impact only; "
                    "it does not simulate rigid-body motion.",
        },
        "max_time": max_time,
        "pairs": pairs,
        "summary": {
            "object_count": len(objects),
            "pair_count": len(pairs),
            "colliding_pair_count": len(colliding_pairs),
            "colliding_pairs": [[p["a"], p["b"]] for p in colliding_pairs],
        },
    }


def _write_json(out_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _render_collision3d(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = check_collision3d(params.get("plan"))
    report = _write_json(Path(out_dir), "collision3d.json", result)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={
            "report_json": str(report),
            "pair_count": result["summary"]["pair_count"],
            "colliding_pair_count": result["summary"]["colliding_pair_count"],
            "colliding_pairs": result["summary"]["colliding_pairs"],
        },
    )


def register_collision3d_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="scene3d.collision_check",
        kind="line",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {"plan": {"type": "object"}},
            "required": ["plan"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render_collision3d,
        has_media_output=False,
        description=(
            "Deterministic 3D collision checking (clean-room): AABB / "
            "sphere overlap, penetration and separation normal, plus "
            "linear time-of-impact for translating objects. Reports only; "
            "no rigid-body dynamics, no rotation, no mesh collision."
        ),
        line="scene3d",
    ))
    return ["scene3d.collision_check"]


register_collision3d_capabilities_once()
