"""Map honesty gate (``qa.map_honesty_gate``).

Discipline gate only. A map-route plan must say honestly what
kind of map it is. A schematic map (a decorative, procedurally
drawn city with invented place names) must declare itself
schematic and must never claim a real-map route source or real
place positions. A real map must name a real route source and
carry real coordinates for every stop. Times and distances on
a schematic map must be declared estimated, never measured.
Hevi already has a real-map route capability driven by true
map data; this gate keeps schematic decoration from being
presented as that real thing. This gate judges the plan only
and renders nothing. See ANIMATION_SKILLS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

REAL_SOURCES = ("osm", "amap", "gps")
SCHEMATIC_SOURCES = ("procedural", "decorative")


def _issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def check_map_honesty(plan: Any) -> dict[str, Any]:
    """Check a map-route plan for geographic honesty.

    Returns a report dict with ``verdict`` pass/fail, ``ok``,
    and ``issues``. Schematic maps claiming real sources,
    real maps without coordinates, and undeclared estimates
    all fail.
    """
    issues: list[dict[str, str]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be a JSON object")],
        }
    map_kind = plan.get("map_kind")
    if map_kind not in ("schematic", "real"):
        issues.append(
            _issue(
                "map_kind_unknown",
                "plan must declare map_kind 'schematic' or 'real'",
            )
        )
        map_kind = None
    route_source = plan.get("route_source")
    if not isinstance(route_source, str) or not route_source:
        issues.append(
            _issue("route_source_missing", "plan must declare a route_source")
        )
    elif map_kind == "schematic" and route_source in REAL_SOURCES:
        issues.append(
            _issue(
                "schematic_claims_real_source",
                "a schematic map must never claim a real-map "
                "route source",
            )
        )
    elif map_kind == "real" and route_source not in REAL_SOURCES:
        issues.append(
            _issue(
                "real_map_needs_real_source",
                "a real map must name a real route source",
            )
        )
    if map_kind == "schematic" and plan.get("schematic_declared") is not True:
        issues.append(
            _issue(
                "schematic_undeclared",
                "a schematic map must declare itself schematic",
            )
        )
    stops = plan.get("stops")
    if not isinstance(stops, list) or not stops:
        issues.append(
            _issue("stops_missing", "plan must declare a non-empty stops list")
        )
        stops = stops if isinstance(stops, list) else []
    for index, stop in enumerate(stops):
        label = f"stops[{index}]"
        if not isinstance(stop, dict):
            issues.append(
                _issue(f"{label}:not_object", "each stop must be an object")
            )
            continue
        if not isinstance(stop.get("name"), str) or not stop.get("name"):
            issues.append(
                _issue(f"{label}:name_missing", "each stop must name a place")
            )
        if map_kind == "real":
            lat = stop.get("lat")
            lon = stop.get("lon")
            if (
                isinstance(lat, bool)
                or not isinstance(lat, (int, float))
                or isinstance(lon, bool)
                or not isinstance(lon, (int, float))
            ):
                issues.append(
                    _issue(
                        f"{label}:coordinates_missing",
                        "a real map stop must carry lat/lon",
                    )
                )
        if map_kind == "schematic" and stop.get("real_place") is True:
            issues.append(
                _issue(
                    f"{label}:schematic_label_claims_real",
                    "a schematic label must never claim to be a "
                    "real place",
                )
            )
    if plan.get("eta_minutes") is not None or plan.get("distance_km") is not None:
        if map_kind == "schematic" and plan.get("eta_basis") != "estimated":
            issues.append(
                _issue(
                    "schematic_eta_undeclared",
                    "times and distances on a schematic map must "
                    "be declared estimated",
                )
            )
        if map_kind == "real" and plan.get("eta_basis") not in ("measured", "estimated"):
            issues.append(
                _issue(
                    "eta_basis_missing",
                    "a real map must declare its time/distance basis",
                )
            )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_map_honesty(params.get("plan"))
    report_path = out_dir / "map_honesty.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_map_honesty_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.map_honesty_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Map honesty gate: schematic maps must declare "
                "themselves schematic and never claim real sources "
                "or real places; real maps need a real route "
                "source and coordinates per stop."
            ),
        )
    )
    return ["qa.map_honesty_gate"]


__all__ = [
    "check_map_honesty",
    "register_map_honesty_gate_capabilities_once",
]
