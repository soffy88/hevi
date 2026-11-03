"""Panel contrast gate (``qa.panel_contrast_gate``).

Clean-room rewrite of the panel-layout method in
``hevi-vs-oyasumi-gamedev.md`` item 1 (from the oyasumi-gamedev.com
manga-research series, restated in the report's own words): a page
of panels is read in order, with pauses, and with importance. The
strength of a large panel comes from its contrast with its
neighbours -- size and stillness/noise against the panels around
it -- not from its absolute area. In vertical scrolling, the
gutter (the white gap between panels) itself carries time: a short
gap reads as an everyday pause, a long one as suspense or a scene
change.

This gate judges a panel plan -- records supplied by the caller --
not pixels. It checks:

1. Every panel declares an importance tier. Undeclared tiers fail.
2. Importance must actually differ across the page: a page where
   every panel carries the same tier has no contrast to judge and
   fails.
3. The most important panel must state its contrast basis against
   its neighbours (how it differs in size, stillness, or both).
   Without a stated basis the standout is undeclared and fails.
4. A break technique (diagonal panel, overlap, or similar) must
   carry at least two reading-order cues; a single cue leaves the
   reader to guess and fails.
5. Gutter pauses: a declared ``gutter_after_s`` is checked for
   sanity (a non-negative number). A plan that declares no gutter
   at all is ``not_checked`` for the pause sub-check -- the pause
   was never stated, so it is never counted as passed.

No threshold in this module comes from the source site: tier
names, size classes and pause lengths are all caller-declared.
This module judges plans only. It never generates, never calls a
model, never touches a budget.
"""

from __future__ import annotations

import json
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

TIERS = ("high", "medium", "low")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.panel_contrast_gate: {detail}"}
    issue.update(extra)
    return issue


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_panel_contrast(plan: Any) -> dict[str, Any]:
    """Judge one panel plan. Returns ``ok`` / ``verdict`` / ``issues``.

    ``plan`` is an object with ``panels``: a list of objects with
    ``id``, ``importance`` (``high`` / ``medium`` / ``low``),
    ``size_class`` (caller-declared, e.g. ``large`` / ``small``),
    optional ``contrast_basis`` (how this panel differs from its
    neighbours), optional ``break_technique`` with ``order_cues``
    (a list of at least two cues), and optional ``gutter_after_s``
    (seconds of pause after this panel).
    """
    issues: list[dict[str, Any]] = []
    gutter_declared = False
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("plan_not_object", "panel plan must be an object")],
            "panel_count": 0,
        }
    panels = plan.get("panels")
    if not isinstance(panels, list) or not panels:
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("panels_missing", "plan must list at least one panel")],
            "panel_count": 0,
        }
    seen_ids: set[str] = set()
    tiers: list[str] = []
    for index, panel in enumerate(panels):
        where = f"panel {index}"
        if not isinstance(panel, dict):
            issues.append(_issue("panel_not_object", f"{where} must be an object"))
            continue
        panel_id = panel.get("id")
        if not isinstance(panel_id, str) or not panel_id.strip():
            issues.append(_issue("panel_id_missing", f"{where} must declare an id"))
        elif panel_id in seen_ids:
            issues.append(_issue("panel_id_duplicate", f"duplicate panel id {panel_id!r}"))
        else:
            seen_ids.add(panel_id)
        importance = panel.get("importance")
        if importance not in TIERS:
            issues.append(
                _issue(
                    "importance_undeclared",
                    f"{where} ({panel_id!r}) must declare importance "
                    f"high/medium/low, got {importance!r}",
                    panel_id=panel_id,
                )
            )
        else:
            tiers.append(importance)
        gutter = panel.get("gutter_after_s")
        if gutter is not None:
            gutter_declared = True
            if not _is_number(gutter) or gutter < 0:
                issues.append(
                    _issue(
                        "gutter_invalid",
                        f"{where} gutter_after_s must be a non-negative number, "
                        f"got {gutter!r}",
                        panel_id=panel_id,
                    )
                )
        technique = panel.get("break_technique")
        if technique is not None:
            cues = panel.get("order_cues")
            if not isinstance(cues, list) or len(cues) < 2:
                issues.append(
                    _issue(
                        "break_needs_two_cues",
                        f"{where} break technique {technique!r} must carry at "
                        "least two reading-order cues",
                        panel_id=panel_id,
                    )
                )
    if tiers and len(set(tiers)) == 1:
        issues.append(
            _issue(
                "no_contrast",
                "every panel carries the same importance tier "
                f"({tiers[0]!r}); a page with no importance difference "
                "has no panel contrast to judge",
            )
        )
    if "high" in tiers:
        standout = [p for p in panels if isinstance(p, dict) and p.get("importance") == "high"]
        for panel in standout:
            basis = panel.get("contrast_basis")
            if not isinstance(basis, str) or not basis.strip():
                issues.append(
                    _issue(
                        "contrast_basis_missing",
                        "the most important panel must state its contrast "
                        "basis against its neighbours (size, stillness, "
                        "or both)",
                        panel_id=panel.get("id"),
                    )
                )
    if issues:
        verdict = "fail"
    elif not gutter_declared:
        verdict = "not_checked"
        issues.append(
            _issue(
                "gutter_pause_undeclared",
                "no panel declares a gutter pause; the pause sub-check "
                "is not_checked, never counted as passed",
            )
        )
    else:
        verdict = "pass"
    return {
        "ok": verdict == "pass",
        "verdict": verdict,
        "issues": issues,
        "panel_count": len(panels),
        "gutter_pause_declared": gutter_declared,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_panel_contrast(params.get("plan"))
    report_path = out_dir / "panel_contrast_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_panel_contrast_gate_capabilities_once() -> list[str]:
    """Register ``qa.panel_contrast_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.panel_contrast_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {"plan": {"type": "object"}},
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Panel contrast gate: every panel declares an importance "
                "tier, tiers must differ across the page, the most "
                "important panel states its contrast basis against its "
                "neighbours, break techniques carry at least two "
                "reading-order cues, and undeclared gutter pauses are "
                "not_checked, never passed. Judges plans only."
            ),
            line="qa",
        )
    )
    return ["qa.panel_contrast_gate"]


register_panel_contrast_gate_capabilities_once()
