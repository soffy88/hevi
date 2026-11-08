"""Shotcraft theme vocabulary gate (``qa.shotcraft_theme_vocabulary``).

Clean-room discipline gate only. Theme names come from a closed
vocabulary of nine presets, restated here as display names only; no
palette value table, scene markup, or demo asset from any outside
repository is copied here. The palette precedence order is recorded
as an explicit caller-supplied list and checked against the
canonical order (schema default, then preset default, then project
palette, then explicit per-clip edit). The Ink Press preset keeps
its original raster look and cannot be recoloured: any palette
override or recolour request aimed at Ink Press fails. Legacy preset
identifiers from earlier bright experiments are accepted only when
explicitly declared as legacy aliases, and the mapping is recorded
as caller-declared, not asserted here. See
VIDEO_SHOTCRAFT_ATTRIBUTION.md.
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

THEME_PRESETS: tuple[str, ...] = (
    "Ink Press",
    "Modern Light",
    "Midnight",
    "Sage",
    "Coral",
    "Iris",
    "Deep Ocean",
    "Obsidian Violet",
    "Vintage Kraft",
)

# Legacy identifiers kept for saved-project compatibility. The
# upstream note lists them in the same breath as the three
# replacement presets, but the per-identifier mapping is not
# asserted here: callers must declare the alias explicitly and the
# report records it as caller-declared.
LEGACY_ALIASES: tuple[str, ...] = (
    "solar-pop",
    "coral-burst",
    "color-play",
)

PALETTE_PRECEDENCE: tuple[str, ...] = (
    "schema_default",
    "preset_default",
    "project_palette",
    "explicit_clip_edit",
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_shotcraft_theme(plan: Any) -> dict[str, Any]:
    """Validate a theme plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. The theme must be one of
    the nine closed presets (or an explicitly declared legacy alias);
    a caller-supplied palette precedence list must match the
    canonical order; Ink Press must never be recoloured.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", "theme plan must be a JSON object")
            ],
            "presets": list(THEME_PRESETS),
        }
    theme = plan.get("theme")
    legacy_alias = plan.get("legacy_alias") is True
    if theme in THEME_PRESETS:
        pass
    elif theme in LEGACY_ALIASES and legacy_alias:
        pass
    elif theme in LEGACY_ALIASES:
        issues.append(
            _issue(
                "legacy_alias_undeclared",
                f"{theme!r} is a legacy identifier and must be "
                "explicitly declared as a legacy alias",
            )
        )
    else:
        issues.append(
            _issue(
                "theme_unknown",
                f"theme must be one of the nine presets: {list(THEME_PRESETS)}",
            )
        )
    precedence = plan.get("palette_precedence")
    if precedence is not None:
        if list(precedence) != list(PALETTE_PRECEDENCE):
            issues.append(
                _issue(
                    "palette_precedence_wrong",
                    "palette precedence must be schema default, then "
                    "preset default, then project palette, then "
                    "explicit per-clip edit",
                )
            )
    override = plan.get("palette_override")
    if theme == "Ink Press":
        if override:
            issues.append(
                _issue(
                    "ink_press_not_recolorable",
                    "Ink Press keeps its original look and cannot be "
                    "recoloured; select another preset to recolour",
                )
            )
        if plan.get("recolor_ink_press") is True:
            issues.append(
                _issue(
                    "ink_press_not_recolorable",
                    "Ink Press keeps its original look and cannot be "
                    "recoloured; select another preset to recolour",
                )
            )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "presets": list(THEME_PRESETS),
        "legacy_alias_declared": legacy_alias,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_shotcraft_theme(params.get("plan"))
    report_path = out_dir / "shotcraft_theme.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_shotcraft_theme_vocabulary_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.shotcraft_theme_vocabulary",
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
                "Shotcraft theme vocabulary gate: nine closed presets, "
                "canonical palette precedence, legacy aliases only "
                "when explicitly declared, and Ink Press never "
                "recoloured."
            ),
        )
    )
    return ["qa.shotcraft_theme_vocabulary"]


__all__ = [
    "THEME_PRESETS",
    "LEGACY_ALIASES",
    "PALETTE_PRECEDENCE",
    "check_shotcraft_theme",
    "register_shotcraft_theme_vocabulary_capabilities_once",
]
