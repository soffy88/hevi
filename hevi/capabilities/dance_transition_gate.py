"""Dance transition gate (``qa.dance_transition_gate``).

Clean-room restatement of the dance MV methodology (see
``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``): a cut is a
decision, not an effect. Each boundary between segments
carries exactly one main mechanism from a closed
vocabulary of eleven — matching on action, shape,
direction, a real foreground wipe, a whip pan, a focus
pull, a real reflection, a rotation phase, a hard cut
on the beat, a soft dissolve, or a flash — with a
visible hook the edit can actually land on. The climax
uses one main mechanism too, and the ending is designed,
not left to freeze. Dissolves and flashes are used
sparingly, never as the default. This gate judges the
edit record only. It cuts nothing, renders nothing, and
spends nothing: ``executed_here`` is always false.
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

# Eleven mechanisms, counted out one by one. The list is
# closed: a boundary names one of these, never a twelfth.
TRANSITIONS: frozenset[str] = frozenset(
    {
        "match_on_action",
        "shape_match",
        "direction_match",
        "foreground_wipe",
        "whip_pan",
        "focus_match",
        "reflection_match",
        "rotation_phase_match",
        "hard_cut_on_beat",
        "soft_dissolve",
        "flash",
    }
)
MAX_DISSOLVES = 2
MAX_FLASHES = 2


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_dance_transitions(edit: Any) -> dict[str, Any]:
    """Validate the transition plan of one dance MV.

    Verdicts are ``pass`` / ``fail`` only. The plan fails
    when a boundary is missing, names an unknown mechanism
    or more than one mechanism, or carries no hook; when
    the climax or the ending is undesigned; or when soft
    dissolves or flashes are used past their sparing limit.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(edit, dict):
        return fail("edit_not_object", "transition plan must be a JSON object")
    boundaries = edit.get("boundaries")
    if not isinstance(boundaries, list) or not boundaries:
        return fail(
            "boundaries_missing",
            "transition plan must carry at least one boundary",
        )
    mechanisms: list[str] = []
    for position, boundary in enumerate(boundaries):
        if not isinstance(boundary, dict):
            return fail(
                "boundary_not_object",
                f"boundary {position} must be an object",
            )
        if (
            not isinstance(boundary.get("from_segment"), str)
            or not boundary["from_segment"].strip()
        ):
            return fail(
                "boundary_from_missing",
                f"boundary {position} must name where it cuts from",
            )
        if not isinstance(boundary.get("to_segment"), str) or not boundary["to_segment"].strip():
            return fail(
                "boundary_to_missing",
                f"boundary {position} must name where it cuts to",
            )
        mechanism = boundary.get("mechanism")
        if isinstance(mechanism, list):
            return fail(
                "mechanism_not_single",
                f"boundary {position} names more than one mechanism; "
                "each boundary carries exactly one",
            )
        if mechanism not in TRANSITIONS:
            return fail(
                "mechanism_unknown",
                f"boundary {position} names unknown mechanism "
                f"{mechanism!r}; use the closed vocabulary",
            )
        mechanisms.append(mechanism)
        if not isinstance(boundary.get("hook"), str) or not boundary["hook"].strip():
            return fail(
                "hook_missing",
                f"boundary {position} must state its visible hook",
            )
    climax = edit.get("climax")
    if not isinstance(climax, dict):
        return fail("climax_missing", "transition plan must design its climax")
    if climax.get("mechanism") not in TRANSITIONS:
        return fail(
            "climax_mechanism_unknown",
            "climax must name one mechanism from the closed vocabulary",
        )
    mechanisms.append(climax["mechanism"])
    if not isinstance(climax.get("trigger"), str) or not climax["trigger"].strip():
        return fail(
            "climax_trigger_missing",
            "climax must state what in the music triggers it",
        )
    ending = edit.get("ending")
    if not isinstance(ending, dict):
        return fail("ending_missing", "transition plan must design its ending")
    if not isinstance(ending.get("design"), str) or not ending["design"].strip():
        return fail(
            "ending_design_missing",
            "ending must state how the film closes",
        )
    if mechanisms.count("soft_dissolve") > MAX_DISSOLVES:
        return fail(
            "dissolve_overused",
            f"soft dissolves appear {mechanisms.count('soft_dissolve')} "
            f"times; the limit is {MAX_DISSOLVES}",
        )
    if mechanisms.count("flash") > MAX_FLASHES:
        return fail(
            "flash_overused",
            f"flashes appear {mechanisms.count('flash')} times; the limit is {MAX_FLASHES}",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_dance_transitions(params.get("edit"))
    report_path = out_dir / "dance_transition_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_dance_transition_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.dance_transition_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "edit": {"type": "object"},
                },
                "required": ["edit"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Dance transition gate: eleven mechanisms in a "
                "closed vocabulary, one per boundary with a visible "
                "hook, a designed climax and ending, dissolves and "
                "flashes used sparingly."
            ),
        )
    )
    return ["qa.dance_transition_gate"]


__all__ = [
    "MAX_DISSOLVES",
    "MAX_FLASHES",
    "TRANSITIONS",
    "check_dance_transitions",
    "register_dance_transition_gate_capabilities_once",
]
