"""Talkback model selection gate (``qa.talkback_model_select_gate``).

Talkback video is driven by third-party models, and the right
model depends on the job: everyday talkback takes the cheap
daily driver, a single unbroken take needs the long-take
model, and a quality piece takes the quality model. Whichever
model is chosen, the run starts with a low-resolution sample
(480p) to confirm motion and framing before any high-resolution
render burns budget. The selection basis must be written down:
no model is picked because it is fashionable.

Clean-room restatement of the selection guidance described in
the Renoise talkback review (see
``DIGITAL_HOST_IMPROVEMENT_ATTRIBUTION.md``). This gate judges
the shape of a model selection only; it never calls a model
and never spends a credit.
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

# One model per job. Names are the public model names as the
# review states them; no key, account, or call is attached.
USE_CASE_MODEL: dict[str, str] = {
    "daily": "wan3.0",
    "single_take": "omnihuman2.0",
    "quality": "seedance2.5",
}

# The low-resolution sample every run must start with.
SAMPLE_RESOLUTION = "480p"


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_talkback_model_select(plan: Any) -> dict[str, Any]:
    """Validate a talkback model selection.

    Verdicts are ``pass`` / ``fail`` only. The plan fails when
    it is not an object, when its use case is unknown, when its
    model does not match its use case, when it skips the
    low-resolution sample, when the sample is not 480p, or when
    no selection basis is written down.
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
    use_case = plan.get("use_case")
    if use_case not in USE_CASE_MODEL:
        return fail(
            "unknown_use_case",
            "use_case must be daily, single_take, or quality",
        )
    if plan.get("model") != USE_CASE_MODEL[use_case]:
        return fail(
            "model_mismatch",
            f"use case {use_case!r} takes {USE_CASE_MODEL[use_case]!r}, not {plan.get('model')!r}",
        )
    if plan.get("low_res_sample_first") is not True:
        return fail(
            "no_low_res_sample",
            "every run must start with a low-resolution sample before any high-resolution render",
        )
    if plan.get("sample_resolution") != SAMPLE_RESOLUTION:
        return fail(
            "sample_resolution_wrong",
            "the low-resolution sample must be 480p",
        )
    basis = plan.get("selection_basis")
    if not isinstance(basis, str) or not basis.strip():
        return fail(
            "selection_basis_missing",
            "the selection basis must be written down",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
        "model": USE_CASE_MODEL[use_case],
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_talkback_model_select(params.get("plan"))
    report_path = out_dir / "talkback_model_select_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_talkback_model_select_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.talkback_model_select_gate",
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
                "talkback model selection gate: one model per use "
                "case, low-resolution 480p sample first, selection "
                "basis written down."
            ),
        )
    )
    return ["qa.talkback_model_select_gate"]


__all__ = [
    "SAMPLE_RESOLUTION",
    "USE_CASE_MODEL",
    "check_talkback_model_select",
    "register_talkback_model_select_gate_capabilities_once",
]
