"""Recorded talkback film gate (``qa.talkback_film_gate``).

A recorded talkback film is built in five steps, in order:
fix the persona, pick the on-screen frames, generate the
talkback, cut it, then polish the result. Every step must be
verifiable on its own: the persona is written down, the
frames are chosen, the talkback audio exists, the cut is
checkable, and the polish is visible. A single misread
sentence is fixed by re-recording that sentence alone, never
by rebuilding the whole film.

Clean-room restatement of the method described in the Renoise
talkback review (see ``DIGITAL_HOST_IMPROVEMENT_ATTRIBUTION.md``).
This gate judges the shape of a film plan only; it never
generates audio, never renders a frame, and never starts a
stream.
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

# The five steps, in order.
STEPS: tuple[str, ...] = ("persona", "frames", "talkback", "edit", "polish")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_talkback_film(plan: Any) -> dict[str, Any]:
    """Validate a recorded talkback film plan.

    Verdicts are ``pass`` / ``fail`` only. The plan fails when
    it is not an object, when any of the five steps is missing,
    when the steps run out of order, when any step is not
    verifiable on its own, or when a single fix rebuilds the
    whole film.
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
    steps = plan.get("steps")
    if not isinstance(steps, dict):
        return fail("steps_missing", "a five-step declaration is required")
    for step in STEPS:
        if steps.get(step) is not True:
            return fail(
                "step_missing",
                f"step {step!r} is missing from the film plan",
            )
    if plan.get("step_order") != list(STEPS):
        return fail(
            "step_order_wrong",
            "the steps must run persona, frames, talkback, edit, polish, in that order",
        )
    if plan.get("each_step_verifiable") is not True:
        return fail(
            "step_not_verifiable",
            "every step must be verifiable on its own",
        )
    if plan.get("single_sentence_fix_rebuilds") is True:
        return fail(
            "single_fix_rebuilds_timeline",
            "a single fix must never rebuild the whole film",
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
    report = check_talkback_film(params.get("plan"))
    report_path = out_dir / "talkback_film_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_talkback_film_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.talkback_film_gate",
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
                "recorded talkback film gate: five steps in order, "
                "every step verifiable on its own, one misread "
                "sentence fixed alone, never a full rebuild."
            ),
        )
    )
    return ["qa.talkback_film_gate"]


__all__ = [
    "STEPS",
    "check_talkback_film",
    "register_talkback_film_gate_capabilities_once",
]
