"""H3 configuration equivalence protocol (``qa.h3_config_equivalence_protocol``).

Clean-room protocol design for the open question behind the
pixelaigc single-segment H3 workflow (see
``PIXELAIGC_H3_WORKFLOW_ATTRIBUTION.md``): whether the
registered fl2va INT8 + NVFP4 AWQ + ckpt850 configuration
produces results equivalent to hevi's installed FastH3
configuration (omniref INT8 + INT8 encoder). Frame counts
sharing a grid do not answer that question; only a controlled
double run with blind comparison does. This module issues the
protocol and the ledger format only. It never executes a run,
never presets a conclusion, and never writes a default for
wall time or peak memory: measured fields stay
``"to_be_measured"`` until a run record supplies them with a
run identifier.

Status vocabulary: ``not_run`` (protocol issued, no run),
``run_recorded`` (a run record with evidence is attached),
``inconclusive`` (run recorded but the threshold was not met
or the comparison was compromised). No other status may claim
equivalence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.h3_config_registration import CONFIG_ID, INSTALLED_CONFIG_ID
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

RATERS_REQUIRED = 5
DIMENSIONS = ("identity", "costume", "background", "motion", "audio_sync")
LEDGER_FIELDS = (
    "run_id",
    "config_a",
    "config_b",
    "prompt_sha256",
    "seed",
    "frames",
    "rater_count",
    "blind",
    "dimension_scores",
    "threshold_met",
    "wall_time_s",
    "peak_vram_mib",
    "status",
)


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.h3_config_equivalence_protocol: {detail}"}
    issue.update(extra)
    return issue


def equivalence_protocol() -> dict[str, Any]:
    """The double-run blind-comparison protocol (not executed)."""
    return {
        "config_a": INSTALLED_CONFIG_ID,
        "config_b": CONFIG_ID,
        "shared": {
            "prompt_sha256": "to_be_supplied",
            "seed": "to_be_supplied",
            "frames": "to_be_supplied",
            "note": (
                "Both configurations run the same prompt text, "
                "the same seed, and the same frame count; only "
                "the configuration differs."
            ),
        },
        "comparison": {
            "raters": RATERS_REQUIRED,
            "blind": True,
            "dimensions": list(DIMENSIONS),
            "threshold": (
                "Equivalence requires at least 4 of 5 raters "
                "reporting no material difference on the identity "
                "dimension, with all five dimensions recorded for "
                "every rater; anything less is inconclusive, never "
                "a pass by default."
            ),
        },
        "ledger_fields": list(LEDGER_FIELDS),
        "measured_fields": {
            "wall_time_s": "to_be_measured",
            "peak_vram_mib": "to_be_measured",
            "note": (
                "No speed or memory value is preset here; a run "
                "record must supply measured values with its run id."
            ),
        },
        "status": "not_run",
    }


def check_equivalence_protocol(protocol: Any) -> dict[str, Any]:
    """Judge one equivalence protocol record for completeness.

    A record that claims a run without evidence, presets
    measured values, uses fewer than five raters, is not
    blind, or omits the threshold fails. Returns ``ok`` /
    ``issues`` / ``protocol``.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(protocol, dict):
        return {
            "ok": False,
            "issues": [_issue("protocol_not_object", "protocol must be an object")],
            "protocol": None,
        }
    comparison = protocol.get("comparison")
    if not isinstance(comparison, dict):
        issues.append(_issue("comparison_undeclared", "comparison block is required"))
    else:
        if comparison.get("raters", 0) < RATERS_REQUIRED:
            issues.append(
                _issue(
                    "too_few_raters",
                    f"blind comparison requires {RATERS_REQUIRED} raters, "
                    f"got {comparison.get('raters')!r}",
                )
            )
        if comparison.get("blind") is not True:
            issues.append(
                _issue("comparison_not_blind", "comparison must be blind")
            )
        if not comparison.get("threshold"):
            issues.append(
                _issue("threshold_undeclared", "a decision threshold is required")
            )
        dimensions = comparison.get("dimensions") or []
        missing = [d for d in DIMENSIONS if d not in dimensions]
        if missing:
            issues.append(
                _issue(
                    "dimensions_missing",
                    f"comparison dimensions missing: {missing}",
                    missing=missing,
                )
            )
    measured = protocol.get("measured_fields") or {}
    for field in ("wall_time_s", "peak_vram_mib"):
        value = measured.get(field)
        if isinstance(value, (int, float)) and not protocol.get("run_id"):
            issues.append(
                _issue(
                    "measured_value_without_run",
                    f"{field} has a numeric value but no run_id supplies "
                    "it; measured fields stay to_be_measured until a run",
                    field=field,
                )
            )
    status = protocol.get("status")
    if status not in ("not_run", "run_recorded", "inconclusive"):
        issues.append(
            _issue(
                "status_unknown",
                f"status must be not_run, run_recorded, or inconclusive, "
                f"got {status!r}; no status may claim equivalence",
            )
        )
    if status == "run_recorded" and not protocol.get("run_id"):
        issues.append(
            _issue(
                "run_record_without_id",
                "run_recorded status requires a run_id with evidence",
            )
        )
    if protocol.get("equivalent") is True and status != "run_recorded":
        issues.append(
            _issue(
                "equivalence_claim_without_run",
                "equivalence may only follow a recorded run that met "
                "the threshold; a protocol alone proves nothing",
            )
        )
    return {"ok": not issues, "issues": issues, "protocol": protocol}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    protocol = params.get("protocol") or equivalence_protocol()
    report = check_equivalence_protocol(protocol)
    report_path = out_dir / "h3_config_equivalence_protocol.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "verdict": "pass" if report["ok"] else "fail"},
    )


def register_h3_config_equivalence_protocol_capabilities_once() -> list[str]:
    """Register ``qa.h3_config_equivalence_protocol`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.h3_config_equivalence_protocol",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "protocol": {"type": "object"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "H3 configuration equivalence protocol: a double-run "
                "blind-comparison protocol (5 raters, 5 dimensions, "
                "4-of-5 identity threshold) plus ledger format for "
                "settling whether two H3 weight configurations are "
                "equivalent. Protocol only; never executed here, no "
                "conclusion preset, no speed/memory defaults."
            ),
            line="qa",
        )
    )
    return ["qa.h3_config_equivalence_protocol"]


register_h3_config_equivalence_protocol_capabilities_once()
