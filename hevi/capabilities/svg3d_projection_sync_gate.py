"""3D-to-screen projection sync gate (``qa.svg3d_projection_sync_gate``).

Pure-function check: a world point, a combined view-projection
camera matrix, and a viewport decide exactly one screen pixel.
The mapping is the standard NDC-to-screen mapping, restated
from first principles (see ``AETHERVIZ_G4_G5_ATTRIBUTION.md``):

    clip = M @ [x, y, z, 1];  w = clip[3];  ndc = clip[:3] / w
    sx = (ndc.x * 0.5 + 0.5) * width
    sy = (0.5 - ndc.y * 0.5) * height

A point behind the camera (w <= 0) is refused: its projection
would mirror to the opposite side of the screen. A point
outside the view frustum (|ndc| > 1 on any axis) is refused:
a label anchored to an invisible point cannot be shown.
Device pixel ratio must be declared; screen pixels here are
CSS pixels, and the host multiplies by DPR when sizing the
renderer backing store. A resize declaration re-projects the
same point under the new viewport and must agree.

This gate judges projection declarations only; it never
renders, never touches Three.js (the host supplies the
combined matrix), and never copies text or code from any
outside repository.
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

_TOLERANCE_PX_DEFAULT = 0.5


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_vec3(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 3 and all(_is_number(v) for v in value)


def _is_mat4(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(
            isinstance(row, list) and len(row) == 4 and all(_is_number(v) for v in row)
            for row in value
        )
    )


def _project(
    point: list[float], matrix: list[list[float]]
) -> tuple[float, float, float, float] | None:
    """Apply a 4x4 row-major matrix; return (ndc.x, ndc.y, ndc.z, w).

    Returns ``None`` when the point is behind the camera (w <= 0).
    """
    x, y, z = point
    clip = [matrix[i][0] * x + matrix[i][1] * y + matrix[i][2] * z + matrix[i][3] for i in range(4)]
    w = clip[3]
    if w <= 0:
        return None
    return (clip[0] / w, clip[1] / w, clip[2] / w, w)


def _to_screen(ndc: tuple[float, float, float, float], width: float, height: float) -> list[float]:
    return [
        (ndc[0] * 0.5 + 0.5) * width,
        (0.5 - ndc[1] * 0.5) * height,
    ]


def check_svg3d_projection_sync(plan: Any) -> dict[str, Any]:
    """Validate one 3D-to-screen projection declaration.

    ``plan`` carries ``point`` ([x, y, z]), ``view_projection``
    (4x4 row-major combined view-projection matrix), ``viewport``
    (``{width, height}``), ``dpr`` (declared device pixel ratio),
    ``screen`` (declared [sx, sy] in CSS pixels), optional
    ``tolerance_px`` (default 0.5), and optional ``resize``
    (``{viewport, screen}``: the same point re-projected under a
    new viewport). Returns a report; never raises.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(plan, dict):
        return fail("plan_not_object", "plan must be a JSON object")
    point = plan.get("point")
    if not _is_vec3(point):
        return fail(
            "point_undefined",
            "point must be a list of three numbers [x, y, z]",
        )
    matrix = plan.get("view_projection")
    if not _is_mat4(matrix):
        return fail(
            "matrix_undefined",
            "view_projection must be a 4x4 matrix of numbers",
        )
    viewport = plan.get("viewport")
    if (
        not isinstance(viewport, dict)
        or not _is_number(viewport.get("width"))
        or not _is_number(viewport.get("height"))
        or viewport["width"] <= 0
        or viewport["height"] <= 0
    ):
        return fail(
            "viewport_undefined",
            "viewport must carry positive width and height",
        )
    dpr = plan.get("dpr")
    if not _is_number(dpr) or dpr <= 0:
        return fail(
            "dpr_undeclared",
            "dpr (device pixel ratio) must be declared as a positive number",
        )
    screen = plan.get("screen")
    if not isinstance(screen, list) or len(screen) != 2 or not all(_is_number(v) for v in screen):
        return fail(
            "screen_undeclared",
            "screen must be a declared [sx, sy] pixel pair",
        )
    tolerance = plan.get("tolerance_px", _TOLERANCE_PX_DEFAULT)
    if not _is_number(tolerance) or tolerance < 0:
        return fail(
            "tolerance_invalid",
            "tolerance_px must be a non-negative number",
        )
    projected = _project(point, matrix)
    if projected is None:
        return fail(
            "behind_camera",
            "the point is behind the camera (w <= 0); its projection "
            "would mirror to the opposite side of the screen",
        )
    if any(abs(v) > 1 for v in projected[:3]):
        return fail(
            "out_of_frustum",
            "the point is outside the view frustum (|ndc| > 1); a "
            "label anchored to an invisible point cannot be shown",
        )
    computed = _to_screen(projected, viewport["width"], viewport["height"])
    if abs(computed[0] - screen[0]) > tolerance or abs(computed[1] - screen[1]) > tolerance:
        return fail(
            "screen_mismatch",
            f"declared screen {screen} does not match recomputed "
            f"screen {[round(v, 3) for v in computed]}",
        )
    resize = plan.get("resize")
    if resize is not None:
        if not isinstance(resize, dict):
            return fail(
                "resize_invalid",
                "resize must be an object with viewport and screen",
            )
        r_viewport = resize.get("viewport")
        r_screen = resize.get("screen")
        if (
            not isinstance(r_viewport, dict)
            or not _is_number(r_viewport.get("width"))
            or not _is_number(r_viewport.get("height"))
            or r_viewport["width"] <= 0
            or r_viewport["height"] <= 0
            or not isinstance(r_screen, list)
            or len(r_screen) != 2
            or not all(_is_number(v) for v in r_screen)
        ):
            return fail(
                "resize_invalid",
                "resize must carry a positive viewport and a [sx, sy] screen pair",
            )
        r_computed = _to_screen(projected, r_viewport["width"], r_viewport["height"])
        if (
            abs(r_computed[0] - r_screen[0]) > tolerance
            or abs(r_computed[1] - r_screen[1]) > tolerance
        ):
            return fail(
                "resize_mismatch",
                f"after resize, declared screen {r_screen} does not "
                f"match recomputed screen {[round(v, 3) for v in r_computed]}",
            )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
        "ndc": [round(v, 6) for v in projected[:3]],
        "screen": [round(v, 3) for v in computed],
        "dpr": dpr,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_svg3d_projection_sync(params.get("plan"))
    report_path = out_dir / "svg3d_projection_sync_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_svg3d_projection_sync_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.svg3d_projection_sync_gate",
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
                "3D-to-screen projection sync gate: world point plus "
                "camera matrix plus viewport recomputed to one screen "
                "pixel; behind-camera points refused, DPR declared, "
                "resize re-projection must agree."
            ),
        )
    )
    return ["qa.svg3d_projection_sync_gate"]


__all__ = [
    "check_svg3d_projection_sync",
    "register_svg3d_projection_sync_gate_capabilities_once",
]
