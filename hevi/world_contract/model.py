"""Core data helpers for the spatial world contract (``hevi.world_contract``).

A *world contract* is a single JSON document that fixes, in metres, every
spatial fact a procedural world is built from: world bounds, zones,
landmarks, exclusion / height rules, interface formulas shared by two
neighbouring zones, named camera anchors, the ground-height provider, the
global lighting timeline and the shot-local time convention.  Zone builders
may only *read* the contract; this module is the reading side (formula
evaluation + geometry), ``validate.py`` is the enforcement side.

Formula representation (the one canonical choice, see
``docs/rules/world_contract.md``):

* ``piecewise_linear`` — ``points`` is a list of ``[x, y]`` pairs sorted by
  ``x``; evaluation is linear interpolation between neighbours and clamping
  outside the sampled range.  Preferred for measured / hand-tuned profiles
  (e.g. trunk radius vs height) because every point is directly auditable.
* ``polynomial`` — ``coeffs`` are ascending-power coefficients
  (``coeffs[i]`` multiplies ``x**i``), evaluated with Horner's rule.  For
  smooth analytic profiles (e.g. bridge-deck sag vs span fraction).

Both forms are pure functions of one variable, so two zones meeting at an
interface can evaluate the *same* formula object and must agree.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "ContractError",
    "load_json",
    "evaluate_formula",
    "point_in_rect",
    "point_in_region",
    "point_in_bounds",
    "rect_of_zone",
]


class ContractError(ValueError):
    """Raised when a contract / manifest document is malformed."""


def load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"file not found: {p}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON in {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError(f"{p}: top level must be a JSON object")
    return data


def evaluate_formula(formula: dict[str, Any], x: float) -> float:
    """Evaluate an interface formula at ``x`` (see module docstring)."""
    kind = formula.get("kind")
    if kind == "piecewise_linear":
        points = formula.get("points") or []
        if len(points) < 2:
            raise ContractError(
                f"formula {formula.get('id')!r}: piecewise_linear needs >= 2 points"
            )
        pts = sorted((float(px), float(py)) for px, py in points)
        if x <= pts[0][0]:
            return pts[0][1]
        if x >= pts[-1][0]:
            return pts[-1][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= x <= x1:
                if x1 == x0:
                    return y1
                t = (x - x0) / (x1 - x0)
                return y0 + t * (y1 - y0)
        return pts[-1][1]  # unreachable, kept for safety
    if kind == "polynomial":
        coeffs = formula.get("coeffs") or []
        if not coeffs:
            raise ContractError(
                f"formula {formula.get('id')!r}: polynomial needs non-empty coeffs"
            )
        result = 0.0
        for c in reversed([float(c) for c in coeffs]):
            result = result * x + c
        return result
    raise ContractError(f"formula {formula.get('id')!r}: unknown kind {kind!r}")


def point_in_rect(x: float, z: float, rect: dict[str, Any]) -> bool:
    return (
        float(rect["x_min"]) <= x <= float(rect["x_max"])
        and float(rect["z_min"]) <= z <= float(rect["z_max"])
    )


def point_in_region(x: float, z: float, region: dict[str, Any]) -> bool:
    """A region is either a rect (x_min/x_max/z_min/z_max) or a circle
    (cx/cz/radius), both in metres on the ground (XZ) plane."""
    if "radius" in region:
        dx = x - float(region["cx"])
        dz = z - float(region["cz"])
        r = float(region["radius"])
        return dx * dx + dz * dz <= r * r
    return point_in_rect(x, z, region)


def point_in_bounds(x: float, z: float, bounds: dict[str, Any]) -> bool:
    return point_in_rect(x, z, bounds)


def rect_of_zone(zone: dict[str, Any]) -> dict[str, Any]:
    b = zone["bounds"]
    return {
        "x_min": b["x_min"],
        "x_max": b["x_max"],
        "z_min": b["z_min"],
        "z_max": b["z_max"],
    }
