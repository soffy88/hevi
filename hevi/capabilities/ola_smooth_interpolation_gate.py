"""Ola smooth interpolation gate (``qa.ola_smooth_interpolation_gate``).

Clean-room restatement of the franciscop/ola method (see
``ANIMATION_STUDIO_18_ATTRIBUTION.md``); no upstream code
appears here. Ola smooths a live numeric value toward its
target instead of jumping: each stream declares its
smoothing rate and its convergence condition, and any jump
larger than the declared maximum must itself be declared.
A stream with no rate, no convergence condition, or an
undeclared jump fails this gate. Un-smoothed jumps are
never allowed through silently.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_ola_smooth_interpolation(plan: Any) -> dict[str, Any]:
    """Validate an Ola-style smooth interpolation plan.

    Verdicts are ``pass`` / ``fail`` only. A plan fails when
    it is not an object, when the stream list is empty, when
    a stream lacks a name, a positive smoothing rate, a
    positive settle time, or a positive maximum jump, or when
    a sampled value jumps by more than the declared maximum
    without the jump being declared.
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
        return fail("plan_not_object", "interpolation plan must be a JSON object")
    if "streams" not in plan:
        return fail("plan_field_missing", "interpolation plan must carry 'streams'")
    streams = plan["streams"]
    if not isinstance(streams, list) or not streams:
        return fail("streams_empty", "interpolation plan needs at least one stream")
    for stream in streams:
        if not isinstance(stream, dict):
            return fail("stream_not_object", "each stream must be an object")
        name = stream.get("name")
        if not isinstance(name, str) or not name:
            return fail("stream_name_missing", "each stream needs a non-empty name")
        rate = stream.get("rate")
        if not isinstance(rate, (int, float)) or rate <= 0:
            return fail(
                "rate_not_positive",
                f"stream {name!r} needs a positive smoothing rate",
            )
        settle = stream.get("settle_seconds")
        if not isinstance(settle, (int, float)) or settle <= 0:
            return fail(
                "settle_not_positive",
                f"stream {name!r} needs a positive settle_seconds convergence condition",
            )
        max_jump = stream.get("max_jump")
        if not isinstance(max_jump, (int, float)) or max_jump <= 0:
            return fail(
                "max_jump_not_positive",
                f"stream {name!r} needs a positive max_jump",
            )
        samples = stream.get("samples")
        if samples is None:
            continue
        if not isinstance(samples, list) or not all(isinstance(v, (int, float)) for v in samples):
            return fail(
                "samples_not_numbers",
                f"stream {name!r} samples must be a list of numbers",
            )
        declared_jump = stream.get("declared_jump") is True
        for prev, cur in pairwise(samples):
            if abs(float(cur) - float(prev)) > float(max_jump) and not declared_jump:
                return fail(
                    "jump_without_declaration",
                    f"stream {name!r} jumps by more than max_jump "
                    f"({max_jump}) without a declared jump; declare the "
                    "jump or smooth the value",
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
    report = check_ola_smooth_interpolation(params.get("plan"))
    report_path = out_dir / "ola_smooth_interpolation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_ola_smooth_interpolation_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.ola_smooth_interpolation_gate",
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
                "Ola smooth interpolation gate: every stream declares a "
                "positive smoothing rate and a convergence condition, and "
                "any jump over the declared maximum must itself be declared."
            ),
        )
    )
    return ["qa.ola_smooth_interpolation_gate"]


__all__ = [
    "check_ola_smooth_interpolation",
    "register_ola_smooth_interpolation_gate_capabilities_once",
]
