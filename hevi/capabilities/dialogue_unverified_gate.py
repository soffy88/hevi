"""Dialogue unverified-labelling gate (``qa.dialogue_unverified_gate``).

Clean-room restatement of the dialogue-check discipline
described in the batch-video-plugin review (see
``BATCH_VIDEO_PLUGIN_ATTRIBUTION.md``): when no transcript or
listening evidence is present, a dialogue check must be
labelled ``not_checked`` -- never written up as verified.
A plan that claims verified dialogue without listening
evidence fails.

This module judges plans only. It never transcribes audio,
never runs a speech model, and never touches a budget.
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

_EVIDENCED_METHODS = ("asr", "manual_listenback")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.dialogue_unverified_gate: {detail}"}
    issue.update(extra)
    return issue


def check_dialogue_verification(plan: Any) -> dict[str, Any]:
    """Judge one plan's dialogue checks against the labelling rule.

    ``plan`` carries ``shots`` (each optionally with ``dialogue``
    lines and a ``dialogue_check`` of ``method`` and
    ``evidence``) and ``dialogue_verification_status``. Every
    shot with dialogue but without an evidenced check method is
    listed in ``not_checked_shots``. Verdict ``pass`` means no
    shot claims verified dialogue without evidence, and the
    plan-level status never claims ``verified`` while any shot
    is unchecked. A plan with no dialogue at all passes with
    ``dialogue_absent``.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("dialogue plan must be an object")
    shots = plan.get("shots")
    if not isinstance(shots, list):
        raise CapabilityError("dialogue plan requires a shots list")
    issues: list[dict[str, Any]] = []
    not_checked: list[str] = []
    dialogue_shots = 0
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            issues.append(_issue("shot_not_object", f"shot {index} is not an object"))
            continue
        shot_id = shot.get("id", f"shot-{index}")
        dialogue = shot.get("dialogue", [])
        if not dialogue:
            continue
        dialogue_shots += 1
        check = shot.get("dialogue_check")
        evidenced = (
            isinstance(check, dict)
            and check.get("method") in _EVIDENCED_METHODS
            and bool(check.get("evidence"))
        )
        if not evidenced:
            not_checked.append(str(shot_id))
            if isinstance(check, dict) and check.get("claimed") == "verified":
                issues.append(
                    _issue(
                        "dialogue_claimed_verified_without_evidence",
                        f"shot {shot_id} claims verified dialogue without "
                        "listening evidence",
                        shot=shot_id,
                    )
                )
    status = plan.get("dialogue_verification_status")
    if not_checked and status == "verified":
        issues.append(
            _issue(
                "status_claims_verified_with_unchecked_shots",
                f"plan claims verified dialogue while {len(not_checked)} "
                "shot(s) are unchecked",
            )
        )
    if not_checked and status not in ("not_checked", "unverified", None):
        issues.append(
            _issue(
                "status_mislabelled",
                "plan-level dialogue status must be not_checked or "
                "unverified while shots are unchecked",
            )
        )
    if dialogue_shots == 0:
        return {
            "ok": True,
            "verdict": "pass",
            "issues": [],
            "not_checked": [],
            "not_checked_shots": [],
            "dialogue_absent": True,
        }
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "not_checked_shots": not_checked,
        "dialogue_absent": False,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_dialogue_verification(params.get("plan"))
    report_path = out_dir / "dialogue_unverified.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_dialogue_unverified_gate_capabilities_once() -> list[str]:
    """Register ``qa.dialogue_unverified_gate`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.dialogue_unverified_gate",
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
            description=(
                "Dialogue labelling gate: without transcript or "
                "listening evidence a dialogue check must be labelled "
                "not_checked, never verified."
            ),
        )
    )
    return ["qa.dialogue_unverified_gate"]


__all__ = [
    "check_dialogue_verification",
    "register_dialogue_unverified_gate_capabilities_once",
]
