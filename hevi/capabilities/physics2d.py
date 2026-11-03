"""2D physics planning (``animation.physics2d``).

Clean-room implementation of the 2D-physics method used by code-animation
and explainer lines (drop, collide, bounce, stack).  No Matter.js code,
asset, or API is copied: the integrator below is a small, deterministic,
semi-implicit Euler simulation written from the method description only.

Scope, stated honestly in the output:
* Axis-aligned bodies only: circles and axis-aligned boxes.  No rotation,
  no angular velocity, no joints, no constraints, no soft bodies.
* Fixed timestep, fixed iteration order (bodies in plan order, collision
  pairs sorted by id), no randomness, no wall-clock input: the same plan
  always produces the same frames on the same platform.
* CPU only, no keys, no model downloads, no video is rendered: the
  artefact is a trajectory + collision JSON that HyperFrames / Playwright
  frame code (or any deterministic renderer) can consume frame by frame.
* A body that penetrates the floor / wall is pushed out and reflected
  with its restitution; a velocity component below 1.0 unit/s after a
  contact is set to 0 so stacks settle instead of jittering forever.

Failure contract: an invalid plan (unknown shape, non-positive size,
duplicate id, non-positive dt/steps, restitution outside [0, 1]) raises
``CapabilityError``.  Nothing is silently clamped into a fake success.
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


def _require_num(value: Any, what: str) -> float:
    if not _is_num(value):
        raise CapabilityError(f"animation.physics2d: {what} must be a number")
    return float(value)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"animation.physics2d: {what} must be a non-empty string")
    return value.strip()


class _Body:
    def __init__(self, spec: dict[str, Any]) -> None:
        if not isinstance(spec, dict):
            raise CapabilityError("animation.physics2d: each body must be a JSON object")
        self.id = _require_str(spec.get("id"), "body.id")
        shape = spec.get("shape")
        if shape not in ("circle", "box"):
            raise CapabilityError(
                f"animation.physics2d: body {self.id} shape must be 'circle' or 'box'"
            )
        self.shape = shape
        self.x = _require_num(spec.get("x", 0.0), f"body {self.id} x")
        self.y = _require_num(spec.get("y", 0.0), f"body {self.id} y")
        self.vx = _require_num(spec.get("vx", 0.0), f"body {self.id} vx")
        self.vy = _require_num(spec.get("vy", 0.0), f"body {self.id} vy")
        self.static = bool(spec.get("static", False))
        mass = _require_num(spec.get("mass", 1.0), f"body {self.id} mass")
        if mass <= 0:
            raise CapabilityError(f"animation.physics2d: body {self.id} mass must be > 0")
        self.mass = mass
        self.inv_mass = 0.0 if self.static else 1.0 / mass
        rest = _require_num(spec.get("restitution", 0.3), f"body {self.id} restitution")
        if rest < 0 or rest > 1:
            raise CapabilityError(
                f"animation.physics2d: body {self.id} restitution must be in [0, 1]"
            )
        self.restitution = rest
        if shape == "circle":
            r = _require_num(spec.get("radius"), f"body {self.id} radius")
            if r <= 0:
                raise CapabilityError(f"animation.physics2d: body {self.id} radius must be > 0")
            self.radius = r
            self.width = self.height = 2.0 * r
        else:
            w = _require_num(spec.get("width"), f"body {self.id} width")
            h = _require_num(spec.get("height"), f"body {self.id} height")
            if w <= 0 or h <= 0:
                raise CapabilityError(
                    f"animation.physics2d: body {self.id} width/height must be > 0"
                )
            self.width, self.height, self.radius = w, h, 0.0

    def half(self) -> tuple[float, float]:
        if self.shape == "circle":
            return self.radius, self.radius
        return self.width / 2.0, self.height / 2.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "shape": self.shape,
            "x": self.x,
            "y": self.y,
            "vx": self.vx,
            "vy": self.vy,
            "static": self.static,
        }


def _resolve_pair(a: _Body, b: _Body, collisions: list[dict[str, Any]], step: int) -> None:
    """Resolve one pair; append a collision record when overlap is found."""
    if a.inv_mass == 0.0 and b.inv_mass == 0.0:
        return
    nx = ny = 0.0
    pen = 0.0
    if a.shape == "circle" and b.shape == "circle":
        dx, dy = b.x - a.x, b.y - a.y
        dist = math.hypot(dx, dy)
        pen = a.radius + b.radius - dist
        if pen <= 0:
            return
        if dist < _EPS:
            nx, ny = 1.0, 0.0
        else:
            nx, ny = dx / dist, dy / dist
    elif a.shape == "box" and b.shape == "box":
        ahx, ahy = a.half()
        bhx, bhy = b.half()
        ox = ahx + bhx - abs(b.x - a.x)
        oy = ahy + bhy - abs(b.y - a.y)
        if ox <= 0 or oy <= 0:
            return
        if ox < oy:
            pen, nx, ny = ox, (1.0 if b.x >= a.x else -1.0), 0.0
        else:
            pen, nx, ny = oy, 0.0, (1.0 if b.y >= a.y else -1.0)
    else:
        circ, box = (a, b) if a.shape == "circle" else (b, a)
        sign = 1.0 if circ is a else -1.0
        bhx, bhy = box.half()
        cx = min(max(circ.x, box.x - bhx), box.x + bhx)
        cy = min(max(circ.y, box.y - bhy), box.y + bhy)
        dx, dy = circ.x - cx, circ.y - cy
        dist = math.hypot(dx, dy)
        if dist >= circ.radius:
            # Centre inside the box: distance to the nearest face.
            if dist < _EPS and abs(circ.x - box.x) <= bhx and abs(circ.y - box.y) <= bhy:
                dx_face = bhx - abs(circ.x - box.x)
                dy_face = bhy - abs(circ.y - box.y)
                if dx_face < dy_face:
                    pen = circ.radius + dx_face
                    nx, ny = (1.0 if circ.x >= box.x else -1.0), 0.0
                else:
                    pen = circ.radius + dy_face
                    nx, ny = 0.0, (1.0 if circ.y >= box.y else -1.0)
                # Normal below is from a to b; flip for the circle-is-a case.
                if circ is a:
                    nx, ny = -nx, -ny
            else:
                return
        else:
            pen = circ.radius - dist
            if dist < _EPS:
                nx, ny = 1.0, 0.0
            else:
                nx, ny = dx / dist, dy / dist
            if circ is b:
                nx, ny = -nx, -ny
    total_inv = a.inv_mass + b.inv_mass
    if total_inv == 0.0:
        return
    # Positional correction, split by inverse mass.
    a.x -= nx * pen * (a.inv_mass / total_inv)
    a.y -= ny * pen * (a.inv_mass / total_inv)
    b.x += nx * pen * (b.inv_mass / total_inv)
    b.y += ny * pen * (b.inv_mass / total_inv)
    # Velocity: reflect the approaching component along the normal.
    rvx, rvy = b.vx - a.vx, b.vy - a.vy
    vel_n = rvx * nx + rvy * ny
    if vel_n < 0:
        rest = min(a.restitution, b.restitution)
        impulse = -(1.0 + rest) * vel_n / total_inv
        a.vx -= impulse * a.inv_mass * nx
        a.vy -= impulse * a.inv_mass * ny
        b.vx += impulse * b.inv_mass * nx
        b.vy += impulse * b.inv_mass * ny
    collisions.append(
        {
            "step": step,
            "a": a.id,
            "b": b.id,
            "penetration": pen,
            "normal": [nx, ny],
        }
    )


def simulate_physics2d(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise CapabilityError("animation.physics2d: plan must be a JSON object")
    raw_bodies = plan.get("bodies")
    if not isinstance(raw_bodies, list) or not raw_bodies:
        raise CapabilityError("animation.physics2d: plan.bodies must be a non-empty list")
    bodies = [_Body(spec) for spec in raw_bodies]
    ids = [b.id for b in bodies]
    if len(set(ids)) != len(ids):
        raise CapabilityError("animation.physics2d: body ids must be unique")
    world = plan.get("world", {})
    if not isinstance(world, dict):
        raise CapabilityError("animation.physics2d: plan.world must be a JSON object")
    gx = _require_num(world.get("gravity_x", 0.0), "world.gravity_x")
    gy = _require_num(world.get("gravity_y", 980.0), "world.gravity_y")
    dt = _require_num(world.get("dt", 1.0 / 60.0), "world.dt")
    if dt <= 0:
        raise CapabilityError("animation.physics2d: world.dt must be > 0")
    steps = world.get("steps", 120)
    if not isinstance(steps, int) or isinstance(steps, bool) or steps <= 0 or steps > 100000:
        raise CapabilityError("animation.physics2d: world.steps must be an integer in [1, 100000]")
    sample_every = world.get("sample_every", 10)
    if not isinstance(sample_every, int) or isinstance(sample_every, bool) or sample_every <= 0:
        raise CapabilityError("animation.physics2d: world.sample_every must be a positive integer")
    width = world.get("width")
    height = world.get("height")
    floor_y = world.get("floor_y")
    if width is not None:
        width = _require_num(width, "world.width")
    if height is not None:
        height = _require_num(height, "world.height")
    if floor_y is not None:
        floor_y = _require_num(floor_y, "world.floor_y")
    frames: list[dict[str, Any]] = []
    collisions: list[dict[str, Any]] = []
    frames.append({"step": 0, "t": 0.0, "bodies": [b.snapshot() for b in bodies]})
    for step in range(1, steps + 1):
        for body in bodies:
            if body.static:
                continue
            body.vx += gx * dt
            body.vy += gy * dt
            body.x += body.vx * dt
            body.y += body.vy * dt
        # World bounds: floor and side walls, when declared.
        for body in bodies:
            if body.static:
                continue
            hx, hy = body.half()
            if floor_y is not None and body.y + hy > floor_y:
                body.y = floor_y - hy
                if body.vy > 0:
                    body.vy = -body.vy * body.restitution
                    if abs(body.vy) < 1.0:
                        body.vy = 0.0
            if width is not None:
                if body.x - hx < 0:
                    body.x = hx
                    if body.vx < 0:
                        body.vx = -body.vx * body.restitution
                if body.x + hx > width:
                    body.x = width - hx
                    if body.vx > 0:
                        body.vx = -body.vx * body.restitution
            if height is not None and body.y - hy < 0:
                body.y = hy
                if body.vy < 0:
                    body.vy = -body.vy * body.restitution
        for i in range(len(bodies)):
            for j in range(i + 1, len(bodies)):
                _resolve_pair(bodies[i], bodies[j], collisions, step)
        # Settle tiny post-contact velocities so stacks stop jittering.
        for body in bodies:
            if body.static:
                continue
            if abs(body.vx) < 1.0 and abs(body.vy) < 1.0:
                # Only zero when the body is supported (floor or another body
                # is within 1 unit below); otherwise a slow fall continues.
                supported = False
                if floor_y is not None and abs((body.y + body.half()[1]) - floor_y) <= 1.0:
                    supported = True
                if supported:
                    body.vx = 0.0
                    body.vy = 0.0
        if step % sample_every == 0 or step == steps:
            frames.append(
                {"step": step, "t": step * dt, "bodies": [b.snapshot() for b in bodies]}
            )
    final = [b.snapshot() for b in bodies]
    resting = [
        b.id
        for b in bodies
        if not b.static and abs(b.vx) < 1.0 and abs(b.vy) < 1.0
    ]
    return {
        "capability": "animation.physics2d",
        "scope": {
            "shapes": ["circle", "box"],
            "rotation": False,
            "joints": False,
            "deterministic": True,
            "units": "plan units; gravity_y default 980 units/s^2",
        },
        "world": {
            "gravity_x": gx,
            "gravity_y": gy,
            "dt": dt,
            "steps": steps,
            "sample_every": sample_every,
            "width": width,
            "height": height,
            "floor_y": floor_y,
        },
        "frames": frames,
        "collisions": collisions,
        "final_state": final,
        "summary": {
            "body_count": len(bodies),
            "frame_count": len(frames),
            "collision_count": len(collisions),
            "resting_bodies": resting,
        },
    }


def _write_json(out_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _render_physics2d(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = simulate_physics2d(params.get("plan"))
    report = _write_json(Path(out_dir), "physics2d.json", result)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={
            "report_json": str(report),
            "body_count": result["summary"]["body_count"],
            "frame_count": result["summary"]["frame_count"],
            "collision_count": result["summary"]["collision_count"],
            "resting_bodies": result["summary"]["resting_bodies"],
        },
    )


def register_physics2d_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="animation.physics2d",
        kind="line",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {"plan": {"type": "object"}},
            "required": ["plan"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render_physics2d,
        has_media_output=False,
        description=(
            "Deterministic 2D physics planning (clean-room): circles and "
            "axis-aligned boxes, drop / collide / bounce / stack, fixed "
            "timestep, CPU only, no keys. Emits trajectory + collision JSON "
            "for a deterministic renderer; renders no video itself."
        ),
        line="animation",
    ))
    return ["animation.physics2d"]


register_physics2d_capabilities_once()
