"""One-shot film honesty gate (``qa.one_shot_film_honesty_gate``).

Clean-room method gate only. The "one prompt, one finished
film" shape is a standing honesty case: the front of the
pipeline (design, gates, contracts) is in place, while the
execution steps (generation, rendering, narration) still
need keys and graphics hardware. A pipeline status report
must declare all seven stages with an honest per-stage
state, and must never carry a connectedness claim: any
"ready", "connected", or end-to-end-verified claim fails,
and this gate's own report always records the film as not
connected. A well-formed declaration passes the gate; the
gate never certifies that a film was produced end to end.
See FIFTEEN_TOOLS_ATTRIBUTION.md.
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

# The seven pipeline stages of the one-shot shape, in order.
STAGES = (
    "picture",
    "three_d",
    "narration",
    "subtitles",
    "music",
    "final_cut",
    "platform_versions",
)

# Honest per-stage states. "open" means the stage runs here
# and needs named evidence; the other three mean the stage is
# not runnable end to end from this report.
STAGE_STATUSES = ("open", "contract_only", "blocked_key_gpu", "design_only")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_one_shot_film_status(status: Any) -> dict[str, Any]:
    """Validate a one-shot pipeline status report; never raises.

    Verdicts are ``pass`` / ``fail`` only. All seven stages
    must be declared with a recognized state, open stages need
    evidence, and no connectedness claim may appear. The
    report always records the shape as not connected.
    """
    issues: list[dict[str, Any]] = []
    stages_out: dict[str, Any] = {}
    if not isinstance(status, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue(
                    "status_not_object",
                    "pipeline status must be a JSON object",
                )
            ],
            "stages": {},
            "one_shot_film_connected": False,
            "verified_end_to_end": False,
        }
    stages = status.get("stages")
    if not isinstance(stages, dict):
        issues.append(
            _issue("stages_missing", "status must declare a stages object")
        )
        stages = {}
    for stage in STAGES:
        entry = stages.get(stage)
        if not isinstance(entry, dict):
            issues.append(
                _issue(
                    "stage_missing",
                    f"stage {stage!r} must be declared as an object",
                )
            )
            stages_out[stage] = {"state": None, "ok": False}
            continue
        state = entry.get("state")
        stage_ok = True
        if state not in STAGE_STATUSES:
            issues.append(
                _issue(
                    "stage_status_unknown",
                    f"stage {stage!r} state must be one of "
                    + ", ".join(STAGE_STATUSES),
                )
            )
            stage_ok = False
        elif state == "open":
            evidence = entry.get("evidence")
            if not isinstance(evidence, str) or not evidence:
                issues.append(
                    _issue(
                        "open_stage_needs_evidence",
                        f"stage {stage!r} declared open must name "
                        "real evidence",
                    )
                )
                stage_ok = False
        stages_out[stage] = {"state": state, "ok": stage_ok}
    if status.get("claims_one_shot_ready") is True:
        issues.append(
            _issue(
                "one_shot_not_connected",
                "the one-shot shape is not connected; a ready claim "
                "fails",
            )
        )
    overall = status.get("overall")
    if isinstance(overall, str) and overall in ("ready", "connected", "done"):
        issues.append(
            _issue(
                "one_shot_not_connected",
                "the one-shot shape is not connected; an overall "
                f"{overall!r} claim fails",
            )
        )
    if status.get("end_to_end_verified") is True:
        issues.append(
            _issue(
                "end_to_end_not_verified_here",
                "no end-to-end run is verified by this gate",
            )
        )
    declared_open = all(
        entry.get("state") == "open" for entry in stages_out.values()
    )
    blocked = [
        stage
        for stage, entry in stages_out.items()
        if entry.get("state") in ("blocked_key_gpu", "contract_only", "design_only")
    ]
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "stages": stages_out,
        "overall": "declared_open_unverified" if declared_open else "not_connected",
        "blocked_or_contract_stages": blocked,
        "one_shot_film_connected": False,
        "verified_end_to_end": False,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_one_shot_film_status(params.get("status"))
    report_path = out_dir / "one_shot_film_status.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_one_shot_film_honesty_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.one_shot_film_honesty_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "object"},
                },
                "required": ["status"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "One-shot film honesty gate: all seven pipeline "
                "stages must be declared with honest states, open "
                "stages need evidence, and no ready/connected or "
                "end-to-end-verified claim may appear."
            ),
        )
    )
    return ["qa.one_shot_film_honesty_gate"]


__all__ = [
    "STAGES",
    "STAGE_STATUSES",
    "check_one_shot_film_status",
    "register_one_shot_film_honesty_gate_capabilities_once",
]
