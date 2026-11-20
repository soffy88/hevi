"""Xiaoya persona finetune honesty gate (``qa.xiaoya_persona_finetune_honesty_gate``).

The persona finetune behind this host is real but its weights
are no longer on the server: the training data lives only in
a Drive file, the model registry holds no finetuned model, and
the directory that should hold the weights does not exist.
What survives is the evaluation record. Raw model output
carried tool-call markers on every single held-out reply, so
a cleaning step that strips those markers (and stray
non-Chinese script) is mandatory before anything is spoken,
and the violation rate is only meaningful when measured after
that cleaning: the measured record is 0% after cleaning
against 52% for the uncleaned base model. Until the weights
are rebuilt, the honest stand-in is the base model plus a
persona prompt, and that stand-in must never be claimed to
equal the finetune.

Clean-room restatement of the evaluation record found in the
``live-parity`` branch checkout (see
``DIGITAL_HOST_IMPROVEMENT_ATTRIBUTION.md``). This gate judges
the shape of a finetune declaration only; it never loads a
weight file and never runs a model.
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

# Where the training data may honestly be said to live.
SFT_DATA_LOCATIONS: frozenset[str] = frozenset({"drive", "local"})

# The only honest basis for a violation rate: measured after
# the cleaning step.
VIOLATION_RATE_BASIS = "after_clean_text"

# Measured record, kept as reference data.
MEASURED_VIOLATION_RATE_AFTER_CLEAN = 0.0
MEASURED_BASE_MODEL_VIOLATION_RATE = 0.52


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_xiaoya_persona_finetune_honesty(plan: Any) -> dict[str, Any]:
    """Validate a persona finetune declaration.

    Verdicts are ``pass`` / ``fail`` only, with a ``mode``
    of ``finetune`` or ``substitute`` on a pass. The plan
    fails when it is not an object, when the training data
    location is undeclared or missing, when the weights are
    claimed present without a location, when raw tool-call
    markers are present and the cleaning step was not applied,
    when no violation rate measured after cleaning is
    recorded, when the empty-reply or mixed-script checks are
    missing, when the weights are missing and no honest
    substitute is declared, or when a substitute is ever
    claimed to equal the finetune.
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
    if plan.get("sft_data_location") not in SFT_DATA_LOCATIONS:
        return fail(
            "sft_data_missing",
            "the training data location must be declared as drive "
            "or local; missing data cannot be rebuilt from",
        )
    if plan.get("substitute_claimed_equal") is True:
        return fail(
            "substitute_claimed_equal",
            "a substitute is never claimed to equal the finetune",
        )
    if plan.get("raw_has_tool_call_markers") is True and (
        plan.get("clean_text_applied") is not True
    ):
        return fail(
            "markers_unstripped",
            "raw output carries tool-call markers on every reply; "
            "the cleaning step must be applied before speaking",
        )
    weights_present = plan.get("weights_present")
    if not isinstance(weights_present, bool):
        return fail(
            "weights_presence_undeclared",
            "weights_present must be declared true or false; the "
            "weights are not on the server today",
        )
    if weights_present:
        if (
            not isinstance(plan.get("weights_location"), str)
            or not plan["weights_location"].strip()
        ):
            return fail(
                "weights_location_missing",
                "weights claimed present need a location on the server",
            )
        if plan.get("clean_text_applied") is not True:
            return fail(
                "clean_text_missing",
                "the cleaning step must be applied before any finetuned reply is spoken",
            )
        rate = plan.get("violation_rate_measured")
        if not _is_number(rate) or not 0.0 <= rate <= 1.0:
            return fail(
                "violation_rate_unmeasured",
                "a violation rate between 0 and 1 must be recorded",
            )
        if plan.get("violation_rate_basis") != VIOLATION_RATE_BASIS:
            return fail(
                "violation_rate_basis_raw",
                "the violation rate is only meaningful measured after "
                "cleaning (measured 0% after cleaning, 52% base model)",
            )
        if plan.get("empty_reply_check") is not True:
            return fail(
                "empty_reply_unchecked",
                "the held-out set contained an empty reply; the empty-reply check must be declared",
            )
        if plan.get("mixed_script_check") is not True:
            return fail(
                "mixed_script_unchecked",
                "the held-out set contained stray non-Chinese script; "
                "the mixed-script check must be declared",
            )
        return {
            "verdict": "pass",
            "ok": True,
            "issues": [],
            "executed_here": False,
            "mode": "finetune",
            "finetune_active": True,
        }
    substitute = plan.get("substitute")
    if not isinstance(substitute, dict):
        return fail(
            "weights_missing",
            "the finetune weights are not on the server and no honest "
            "substitute is declared; rebuild or declare the substitute",
        )
    if not isinstance(substitute.get("model"), str) or not substitute["model"].strip():
        return fail(
            "weights_missing",
            "the substitute must name its model (base model plus persona prompt)",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
        "mode": "substitute",
        "finetune_active": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_xiaoya_persona_finetune_honesty(params.get("plan"))
    report_path = out_dir / "xiaoya_persona_finetune_honesty_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_xiaoya_persona_finetune_honesty_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.xiaoya_persona_finetune_honesty_gate",
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
                "xiaoya persona finetune honesty gate: weights "
                "presence declared, markers stripped by cleaning, "
                "violation rate measured after cleaning, substitute "
                "never claimed equal to the finetune."
            ),
        )
    )
    return ["qa.xiaoya_persona_finetune_honesty_gate"]


__all__ = [
    "MEASURED_BASE_MODEL_VIOLATION_RATE",
    "MEASURED_VIOLATION_RATE_AFTER_CLEAN",
    "SFT_DATA_LOCATIONS",
    "VIOLATION_RATE_BASIS",
    "check_xiaoya_persona_finetune_honesty",
    "register_xiaoya_persona_finetune_honesty_gate_capabilities_once",
]
