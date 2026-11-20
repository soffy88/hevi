"""Hybrid render mode gate (``qa.hybrid_render_mode_gate``).

Three render modes, one choice rule, one palette. The mode
follows the theme: a theme that asks for 3D and for overlay
labels is hybrid; 3D alone is three; overlay labels alone
is svg; a theme that asks for neither defaults to three.
Hybrid wins whenever both kinds of work are present; the
mode declaration must equal the mode the rule derives, or
the plan fails.

Vector colours follow the Atlas convention, which governs
here and is not re-invented: force is the Atlas ``red``
palette, velocity is the Atlas ``blue`` palette. Every
declared vector colour must name an Atlas palette
(paper/base/dark/ink/red/blue/board); a hex code or a
palette Atlas never defined (there is no Atlas ``green``)
is refused. See ``AETHERVIZ_G4_G5_ATTRIBUTION.md`` for the
verification note on the acceleration colour.

This gate judges mode and colour declarations only; it
renders nothing and never copies text or code from any
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

MODES: tuple[str, ...] = ("three", "svg", "hybrid")

# Keywords that ask for 3D work (English and Chinese).
THREE_KEYWORDS: tuple[str, ...] = (
    "3d",
    "three",
    "立体",
    "旋转",
    "透视",
    "模型",
    "相机",
    "camera",
    "orbit",
    "场景",
    "scene",
    "mesh",
    "网格",
    "视角",
    "渲染",
    "render",
)

# Keywords that ask for overlay labels (English and Chinese).
OVERLAY_KEYWORDS: tuple[str, ...] = (
    "标注",
    "label",
    "标签",
    "箭头",
    "矢量",
    "vector",
    "overlay",
    "覆盖",
    "svg",
    "注释",
    "annotation",
)

# Atlas palette names (physics.atlas_figure PALETTE keys). Atlas
# defines no green palette.
ATLAS_PALETTES: tuple[str, ...] = (
    "paper",
    "base",
    "dark",
    "ink",
    "red",
    "blue",
    "board",
)

# Canonical Atlas role-to-palette mapping.
ROLE_PALETTE: dict[str, str] = {
    "force": "red",
    "velocity": "blue",
}


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def derive_mode(theme: str) -> str:
    """Derive the render mode from a theme string.

    Both 3D and overlay keywords present means hybrid; 3D
    alone means three; overlay alone means svg; neither
    defaults to three.
    """
    lowered = theme.lower()
    has_three = any(kw in lowered for kw in THREE_KEYWORDS)
    has_overlay = any(kw in lowered for kw in OVERLAY_KEYWORDS)
    if has_three and has_overlay:
        return "hybrid"
    if has_overlay:
        return "svg"
    return "three"


def check_hybrid_render_mode(plan: Any) -> dict[str, Any]:
    """Validate one hybrid render mode declaration.

    ``plan`` carries ``theme`` (string), ``mode`` (one of
    ``three`` / ``svg`` / ``hybrid``), and optional
    ``vector_colors`` (``{role: atlas_palette_name}``). The
    declared mode must equal the mode derived from the theme;
    every vector colour must name an Atlas palette, and the
    force/velocity roles must use their canonical Atlas
    palettes. Returns a report; never raises.
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
    theme = plan.get("theme")
    if not isinstance(theme, str):
        return fail(
            "theme_undefined",
            "theme must be a string describing the figure",
        )
    mode = plan.get("mode")
    if mode not in MODES:
        return fail(
            "mode_unknown",
            f"mode must be one of {list(MODES)}",
        )
    expected = derive_mode(theme)
    if mode != expected:
        return fail(
            "mode_mismatch",
            f"theme {theme!r} derives mode {expected!r}, not {mode!r}",
        )
    vector_colors = plan.get("vector_colors")
    if vector_colors is not None:
        if not isinstance(vector_colors, dict):
            return fail(
                "vector_colors_invalid",
                "vector_colors must be an object of role to palette name",
            )
        for role, palette in vector_colors.items():
            if palette not in ATLAS_PALETTES:
                return fail(
                    "color_not_atlas_palette",
                    f"vector {role!r} uses {palette!r}, which is not an "
                    f"Atlas palette {list(ATLAS_PALETTES)}; Atlas defines "
                    "no green palette and no hex colours",
                )
            if role in ROLE_PALETTE and palette != ROLE_PALETTE[role]:
                return fail(
                    "color_role_mismatch",
                    f"vector {role!r} must use the Atlas palette "
                    f"{ROLE_PALETTE[role]!r}, not {palette!r}",
                )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
        "mode": mode,
        "derived_mode": expected,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_hybrid_render_mode(params.get("plan"))
    report_path = out_dir / "hybrid_render_mode_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_hybrid_render_mode_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.hybrid_render_mode_gate",
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
                "hybrid render mode gate: three/svg/hybrid chosen "
                "from the theme, hybrid winning when both 3D and "
                "overlay work are present; vector colours must name "
                "Atlas palettes, force red and velocity blue."
            ),
        )
    )
    return ["qa.hybrid_render_mode_gate"]


__all__ = [
    "ATLAS_PALETTES",
    "MODES",
    "OVERLAY_KEYWORDS",
    "ROLE_PALETTE",
    "THREE_KEYWORDS",
    "check_hybrid_render_mode",
    "derive_mode",
    "register_hybrid_render_mode_gate_capabilities_once",
]
