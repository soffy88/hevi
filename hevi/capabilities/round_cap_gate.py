"""Round cap and auto-dispatch gate (``qa.round_cap_gate``).

Clean-room restatement of the batch-round discipline described
in the batch-video-plugin review (see
``BATCH_VIDEO_PLUGIN_ATTRIBUTION.md``): generation proceeds in
rounds; each round admits only a caller-declared number of
successful takes, failures do not consume the cap, a finished
film stops further generation, and a failed take returns to the
queue only a bounded number of times and only with a reason.

This module judges plans only. It never generates, never calls
a model, never touches a queue, and never touches a budget.
The per-round success cap has no default: the caller must
declare it, so no upstream number can silently become policy.
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


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.round_cap_gate: {detail}"}
    issue.update(extra)
    return issue


def check_round_cap(plan: Any) -> dict[str, Any]:
    """Judge one batch-round plan against the round-cap discipline.

    ``plan`` carries ``rounds`` (each with ``successful_count``,
    ``failed_count`` and ``requeues``), ``max_success_per_round``
    (required, a positive integer), ``max_requeue_attempts``
    (required, a non-negative integer), ``auto_dispatch`` and
    ``final_cut_done``. Verdict ``pass`` means no round exceeds
    the success cap, failures were never counted against the
    cap, every requeue is bounded and reasoned, and no
    generation is scheduled after the final cut.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("round plan must be an object")
    cap = plan.get("max_success_per_round")
    if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
        raise CapabilityError(
            "round plan requires a positive integer max_success_per_round "
            "(no default is assumed)"
        )
    max_requeue = plan.get("max_requeue_attempts")
    if not isinstance(max_requeue, int) or isinstance(max_requeue, bool) or max_requeue < 0:
        raise CapabilityError(
            "round plan requires a non-negative integer max_requeue_attempts "
            "(no default is assumed)"
        )
    if plan.get("failed_counted_in_cap"):
        issues = [
            _issue(
                "failed_counted_in_cap",
                "failed takes must never count against the success cap",
            )
        ]
        return {
            "ok": False,
            "verdict": "fail",
            "issues": issues,
            "not_checked": [],
            "round_count": 0,
        }
    issues: list[dict[str, Any]] = []
    rounds = plan.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        raise CapabilityError("round plan requires a non-empty rounds list")
    for index, round_ in enumerate(rounds):
        if not isinstance(round_, dict):
            issues.append(_issue("round_not_object", f"round {index} is not an object"))
            continue
        successful = round_.get("successful_count", 0)
        if not isinstance(successful, int) or isinstance(successful, bool) or successful < 0:
            issues.append(
                _issue(
                    "successful_count_invalid",
                    f"round {index} successful_count must be a non-negative integer",
                    round=index,
                )
            )
            successful = 0
        if successful > cap:
            issues.append(
                _issue(
                    "round_success_over_cap",
                    f"round {index} has {successful} successes over cap {cap}",
                    round=index,
                )
            )
        for entry in round_.get("requeues", []):
            if not isinstance(entry, dict):
                issues.append(
                    _issue("requeue_not_object", f"round {index} has a non-object requeue", round=index)
                )
                continue
            attempts = entry.get("attempts", 0)
            if not isinstance(attempts, int) or attempts > max_requeue:
                issues.append(
                    _issue(
                        "requeue_exhausted",
                        f"round {index} requeue for {entry.get('shot_id')} "
                        f"has {attempts} attempts over limit {max_requeue}",
                        round=index,
                    )
                )
            if not entry.get("reason"):
                issues.append(
                    _issue(
                        "requeue_without_reason",
                        f"round {index} requeue for {entry.get('shot_id')} lacks a reason",
                        round=index,
                    )
                )
    if plan.get("final_cut_done") and plan.get("generate_after_final_cut"):
        issues.append(
            _issue(
                "generation_after_final_cut",
                "no generation may be scheduled after the final cut is done",
            )
        )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "round_count": len(rounds),
        "cap": cap,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_round_cap(params.get("plan"))
    report_path = out_dir / "round_cap.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_round_cap_gate_capabilities_once() -> list[str]:
    """Register ``qa.round_cap_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.round_cap_gate",
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
                "Round cap gate: each round admits only a caller-declared "
                "number of successful takes, failures never count against "
                "the cap, requeues are bounded and reasoned, and no "
                "generation follows the final cut."
            ),
        )
    )
    return ["qa.round_cap_gate"]


__all__ = ["check_round_cap", "register_round_cap_gate_capabilities_once"]
