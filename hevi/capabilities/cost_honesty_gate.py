"""Cost honesty gate (``qa.cost_honesty_gate``).

Discipline gate only. A cost figure is only as good as its
provenance: a measured cost needs an itemised breakdown that
adds up plus evidence, and a figure taken from a project's
own write-up must be labelled self-reported with its source
named -- never presented as measured. Figures without a
basis, a breakdown that does not add up, or a self-reported
figure worded as verified all fail. This gate judges the
claim only and spends nothing. See HYPIT_ATTRIBUTION.md.
Method restated in our own words; no upstream cost figure
is reproduced here.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_TOLERANCE = 0.01


def _issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_cost_honesty(claim: Any) -> dict[str, Any]:
    """Check a cost claim for provenance and arithmetic honesty.

    Returns a report dict with ``verdict`` pass/fail, ``ok``,
    and ``issues``. Missing basis, a measured claim without a
    breakdown or evidence, a breakdown that does not sum to
    the total, and a self-reported figure claimed as verified
    all fail.
    """
    issues: list[dict[str, str]] = []
    if not isinstance(claim, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("claim_not_object", "claim must be a JSON object")],
        }
    amount = claim.get("amount")
    if not _is_number(amount) or amount < 0:
        issues.append(_issue("amount_invalid", "claim must declare a non-negative numeric amount"))
        amount = None
    if not isinstance(claim.get("currency"), str) or not claim["currency"].strip():
        issues.append(_issue("currency_missing", "claim must declare a currency"))
    basis = claim.get("basis")
    if basis not in ("measured", "self_reported", "estimate"):
        issues.append(
            _issue(
                "basis_missing",
                "claim must declare a basis: measured, self_reported, or estimate",
            )
        )
    if claim.get("verified") is True and basis != "measured":
        issues.append(
            _issue(
                "verified_without_measurement",
                "only a measured claim may be worded as verified",
            )
        )
    if basis == "measured":
        breakdown = claim.get("breakdown")
        if not isinstance(breakdown, list) or not breakdown:
            issues.append(
                _issue(
                    "breakdown_missing",
                    "a measured claim needs an itemised breakdown",
                )
            )
        elif amount is not None:
            total = 0.0
            breakdown_valid = True
            for index, entry in enumerate(breakdown):
                if not isinstance(entry, dict) or not _is_number(entry.get("amount")):
                    breakdown_valid = False
                    issues.append(
                        _issue(
                            f"breakdown[{index}]:amount_invalid",
                            "every breakdown entry needs a numeric amount",
                        )
                    )
                else:
                    total += entry["amount"]
            if breakdown_valid and abs(total - amount) > _TOLERANCE:
                issues.append(
                    _issue(
                        "breakdown_mismatch",
                        "breakdown amounts must sum to the claimed total",
                    )
                )
        if (
            not isinstance(claim.get("measured_evidence"), str)
            or not claim["measured_evidence"].strip()
        ):
            issues.append(
                _issue(
                    "measured_evidence_missing",
                    "a measured claim needs named evidence (bill, log, or receipt)",
                )
            )
    if basis == "self_reported":
        if not isinstance(claim.get("source"), str) or not claim["source"].strip():
            issues.append(
                _issue(
                    "source_missing",
                    "a self-reported figure must name the reporting source",
                )
            )
        if claim.get("verified") is True:
            issues.append(
                _issue(
                    "self_reported_claimed_verified",
                    "a self-reported figure must not be worded as verified",
                )
            )
    if basis == "estimate" and claim.get("verified") is True:
        issues.append(
            _issue(
                "estimate_claimed_verified",
                "an estimate must not be worded as verified",
            )
        )
    if amount is not None and math.isnan(amount):
        issues.append(_issue("amount_invalid", "amount must not be NaN"))
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_cost_honesty(params.get("claim"))
    report_path = out_dir / "cost_honesty.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_cost_honesty_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.cost_honesty_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "claim": {"type": "object"},
                },
                "required": ["claim"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Cost honesty gate (discipline only): measured costs "
                "need a breakdown that adds up plus evidence; "
                "self-reported figures must be labelled as such."
            ),
        )
    )
    return ["qa.cost_honesty_gate"]


__all__ = [
    "check_cost_honesty",
    "register_cost_honesty_gate_capabilities_once",
]
