"""Jianying export contract gate (``qa.jianying_export_contract_gate``).

Clean-room discipline gate only, restating the export method in our
own words: motion baked into clean plates, subtitles and audio on
native editable tracks, microsecond-exact segment boundaries, a
one-way conversion, and a machine-fingerprint privacy rule. A plan
that claims a real Jianying draft export must declare all four:
layering, the boundary rule, the one-way notice, and the
do-not-distribute declaration for machine fingerprints. This gate
judges the plan only: it writes no draft file, calls no editor, and
``draft_file`` stays null here. No text, code, or asset from any
outside repository is copied here. See
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

# Canonical boundary rule token: each segment endpoint is rounded
# independently first, and the duration is then subtracted from the
# rounded endpoints. Any other rule token fails the gate.
BOUNDARY_RULE = "round_each_endpoint_then_subtract"


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_jianying_export_contract(plan: Any) -> dict[str, Any]:
    """Validate a Jianying export plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. All four declarations are
    required: layering, boundary rule, one-way notice, and the
    machine-fingerprint rule. ``executed_here`` must be false: this
    gate never produces a draft file.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", "export plan must be a JSON object")
            ],
            "boundary_rule": BOUNDARY_RULE,
        }
    layering = plan.get("layering")
    if not isinstance(layering, dict):
        issues.append(
            _issue(
                "layering_missing",
                "plan must declare a layering block (baked plate + "
                "editable tracks)",
            )
        )
    else:
        if layering.get("baked_plate_clean") is not True:
            issues.append(
                _issue(
                    "baked_plate_not_clean",
                    "the baked plate must be declared clean: no "
                    "subtitles, no sound effects, no background music",
                )
            )
        editable = layering.get("editable_tracks")
        if not isinstance(editable, list) or not editable:
            issues.append(
                _issue(
                    "editable_tracks_missing",
                    "plan must list the editable native tracks "
                    "(subtitles/audio) carried into the editor",
                )
            )
    if plan.get("boundary_rule") != BOUNDARY_RULE:
        issues.append(
            _issue(
                "boundary_rule_wrong",
                "segment boundaries must use the round-each-endpoint-"
                "then-subtract rule",
            )
        )
    if plan.get("one_way_notice_acknowledged") is not True:
        issues.append(
            _issue(
                "one_way_notice_missing",
                "the caller must acknowledge the conversion is "
                "one-way: an opened draft cannot be read back",
            )
        )
    if plan.get("device_fingerprint_not_shared") is not True:
        issues.append(
            _issue(
                "fingerprint_rule_missing",
                "the caller must declare the draft (which carries a "
                "machine fingerprint) will not be distributed to others",
            )
        )
    if plan.get("executed_here") is not False:
        issues.append(
            _issue(
                "executed_here_must_be_false",
                "this gate never produces a draft file; executed_here "
                "must be false",
            )
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "boundary_rule": BOUNDARY_RULE,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_jianying_export_contract(params.get("plan"))
    report_path = out_dir / "jianying_export_contract.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_jianying_export_contract_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.jianying_export_contract_gate",
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
                "Jianying export contract gate: baked-plate layering, "
                "the round-each-endpoint boundary rule, a one-way "
                "conversion notice, and a machine-fingerprint "
                "do-not-distribute declaration are all required; "
                "no draft file is produced here."
            ),
        )
    )
    return ["qa.jianying_export_contract_gate"]


__all__ = [
    "BOUNDARY_RULE",
    "check_jianying_export_contract",
    "register_jianying_export_contract_gate_capabilities_once",
]
