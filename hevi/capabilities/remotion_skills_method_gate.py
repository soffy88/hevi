"""Remotion Skills method gate (``qa.remotion_skills_method_gate``).

Clean-room method gate only. The method notes are restated in our
own words from the public method material in the official Remotion
skills repository (``remotion-dev/skills``; license undeclared, so
the intake is pinned to one commit, recorded below, and no SKILL
text is copied here). A plan that claims to follow that method must
declare its compositions with consistent frame/time arithmetic,
declare its caption handling, and must never claim a verified
render without naming real render evidence. This gate judges the
plan only and renders nothing: the Remotion container render path
is a separate case and is recorded here as unverified (the
container render previously failed with EACCES; see the smoke
capability ``video.remotion_bridge_smoke``). See
OPEN_SKILLS_ATTRIBUTION.md.
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

# Pinned intake: remotion-dev/skills, main branch HEAD as observed
# 2026-11-04 (commit message "Update template", 2026-11-02). The
# repository declares no license and publishes no release, so the
# commit pin is the version record; method only, no text copied.
PINNED_SKILLS_COMMIT = "c7cb2fdcacd134fb2ccb9b7a44f9ffa44e467271"
PINNED_SKILLS_DATE = "2026-11-02"


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_remotion_skills_method(plan: Any) -> dict[str, Any]:
    """Validate a Remotion composition plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. Compositions must carry
    consistent frame/time arithmetic, caption handling must be
    declared, and a verified-render claim needs named evidence.
    Nothing here is verified as rendered by this gate.
    """
    issues: list[dict[str, Any]] = []
    comps_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", "composition plan must be a JSON object")
            ],
            "compositions": [],
            "pinned_commit": PINNED_SKILLS_COMMIT,
            "render_verified_by_this_gate": False,
        }
    if plan.get("follows_remotion_skills") is True:
        if plan.get("skills_commit") != PINNED_SKILLS_COMMIT:
            issues.append(
                _issue(
                    "skills_commit_mismatch",
                    "plans following the Remotion Skills method must cite "
                    f"the pinned commit {PINNED_SKILLS_COMMIT}",
                )
            )
    captions_required = plan.get("captions_required") is True
    comps = plan.get("compositions")
    if not isinstance(comps, list) or not comps:
        issues.append(
            _issue(
                "compositions_missing",
                "plan must declare a non-empty compositions list",
            )
        )
        comps = comps if isinstance(comps, list) else []
    for index, comp in enumerate(comps):
        label = f"compositions[{index}]"
        entry: dict[str, Any] = {"index": index, "ok": True, "issues": []}
        if not isinstance(comp, dict):
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:not_object", "each composition must be an object")
            )
            comps_out.append(entry)
            continue
        comp_id = comp.get("id")
        entry["id"] = comp_id
        if not isinstance(comp_id, str) or not comp_id:
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:id_missing", "each composition must declare an id")
            )
        fps = comp.get("fps")
        if not isinstance(fps, (int, float)) or isinstance(fps, bool) or fps <= 0:
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:fps_invalid", "fps must be a positive number")
            )
        for field in ("width", "height", "durationInFrames"):
            value = comp.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:{field}_invalid",
                        f"{field} must be a positive integer",
                    )
                )
        seconds = comp.get("duration_seconds")
        if seconds is not None:
            if (
                not isinstance(seconds, (int, float))
                or isinstance(seconds, bool)
                or seconds <= 0
            ):
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:duration_seconds_invalid",
                        "duration_seconds must be a positive number",
                    )
                )
            elif (
                isinstance(fps, (int, float))
                and not isinstance(fps, bool)
                and isinstance(comp.get("durationInFrames"), int)
                and comp["durationInFrames"] != round(seconds * fps)
            ):
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:frame_time_mismatch",
                        "durationInFrames must equal "
                        "round(duration_seconds * fps)",
                    )
                )
        captions_declared = comp.get("captions_declared")
        if not isinstance(captions_declared, bool):
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:captions_declaration_missing",
                    "each composition must declare captions_declared "
                    "as a boolean",
                )
            )
        elif captions_required and captions_declared is not True:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:captions_undeclared",
                    "captions are required but this composition does "
                    "not declare them",
                )
            )
        render_verified = comp.get("render_verified")
        if not isinstance(render_verified, bool):
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:render_verified_undeclared",
                    "each composition must declare render_verified "
                    "as a boolean",
                )
            )
        elif render_verified is True:
            evidence = comp.get("render_evidence")
            if not isinstance(evidence, str) or not evidence:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:render_claim_without_evidence",
                        "a verified-render claim must name real render "
                        "evidence; this gate never verifies a render",
                    )
                )
        if entry["issues"]:
            entry["ok"] = False
        comps_out.append(entry)
        issues.extend(entry["issues"])
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "compositions": comps_out,
        "pinned_commit": PINNED_SKILLS_COMMIT,
        "render_verified_by_this_gate": False,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_remotion_skills_method(params.get("plan"))
    report_path = out_dir / "remotion_skills_method.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_remotion_skills_method_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.remotion_skills_method_gate",
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
                "Remotion Skills method gate: compositions must carry "
                "consistent frame/time arithmetic, declare caption "
                "handling, cite the pinned skills commit when claiming "
                "the method, and never claim a verified render without "
                "named evidence; rendering itself is unverified here."
            ),
        )
    )
    return ["qa.remotion_skills_method_gate"]


__all__ = [
    "PINNED_SKILLS_COMMIT",
    "PINNED_SKILLS_DATE",
    "check_remotion_skills_method",
    "register_remotion_skills_method_gate_capabilities_once",
]
