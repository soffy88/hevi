"""Paid generation cost gate (``qa.paid_generation_cost_gate``).

No paid call without a declared budget. Before any paid
generation call the plan must declare the model, the
``max_tokens`` bound, the number of calls, the estimated
cost in USD, and a budget that covers the estimate. The
cost model is the public Claude Sonnet 4.6 price: output
$15 per million tokens, input $3 per million tokens. The
single-film ceiling is $0.50: two calls at most 16,000
output tokens each cost at most 32,000 x $15 per million =
$0.48 output, plus a few cents of input. A realistic film
(8,000-12,000 output tokens per call) runs about
$0.25-0.40. An estimate below the recomputed floor is
understated and fails; an estimate above the cap fails.

The HyperFrames CLI version must be pinned: an undeclared
version fails. The Anthropic key is a new paid dependency
that is not connected here: while ``anthropic_key_connected``
is false, every call fails. This gate never calls any API,
never spends anything, and never copies text or code from
any outside repository. See ``AETHERVIZ_G4_G5_ATTRIBUTION.md``.
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

# Public Claude Sonnet 4.6 prices, USD per million tokens.
OUTPUT_PRICE_PER_MTOK = 15.0
INPUT_PRICE_PER_MTOK = 3.0
# Single-film cost ceiling in USD (two calls, 16k output tokens each).
COST_CAP_USD = 0.50
# Realistic per-film range, USD (8k-12k output tokens per call).
COST_REALISTIC_LOW_USD = 0.25
COST_REALISTIC_HIGH_USD = 0.40


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _recomputed_cost_usd(calls: int, output_tokens: int, input_tokens: int) -> float:
    return (
        calls * output_tokens * OUTPUT_PRICE_PER_MTOK / 1_000_000
        + calls * input_tokens * INPUT_PRICE_PER_MTOK / 1_000_000
    )


def check_paid_generation_cost(plan: Any) -> dict[str, Any]:
    """Validate one paid generation call declaration.

    ``plan`` carries ``model``, ``max_tokens`` (per-call bound),
    ``calls`` (number of paid calls), ``input_tokens`` and
    ``output_tokens`` (expected tokens per call; ``output_tokens``
    defaults to ``max_tokens`` when absent),
    ``estimated_cost_usd``, ``budget_declared``,
    ``budget_usd``, ``hyperframes_version`` (pinned version
    string), and ``anthropic_key_connected``. The estimate must
    cover the recomputed floor, stay within the $0.50
    single-film cap and the declared budget, the HyperFrames
    version must be pinned, and the Anthropic key must be
    connected. Returns a report; never raises.
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
    model = plan.get("model")
    if not isinstance(model, str) or not model.strip():
        return fail(
            "model_undeclared",
            "model must be declared before any paid call",
        )
    max_tokens = plan.get("max_tokens")
    if not _is_positive_int(max_tokens):
        return fail(
            "max_tokens_undeclared",
            "max_tokens must be declared as a positive integer",
        )
    calls = plan.get("calls")
    if not _is_positive_int(calls):
        return fail(
            "calls_undeclared",
            "calls (number of paid calls) must be declared as a positive integer",
        )
    input_tokens = plan.get("input_tokens", 0)
    if not isinstance(input_tokens, int) or isinstance(input_tokens, bool) or input_tokens < 0:
        return fail(
            "input_tokens_invalid",
            "input_tokens must be a non-negative integer",
        )
    output_tokens = plan.get("output_tokens", max_tokens)
    if not _is_positive_int(output_tokens):
        return fail(
            "output_tokens_invalid",
            "output_tokens must be a positive integer",
        )
    if output_tokens > max_tokens:
        return fail(
            "output_tokens_over_max",
            "output_tokens must not exceed max_tokens",
        )
    estimated = plan.get("estimated_cost_usd")
    if not _is_number(estimated):
        return fail(
            "cost_undeclared",
            "estimated_cost_usd must be declared before any paid call",
        )
    if plan.get("budget_declared") is not True or not _is_number(plan.get("budget_usd")):
        return fail(
            "budget_undeclared",
            "a declared budget (budget_declared=true, budget_usd) is required before any paid call",
        )
    budget = plan["budget_usd"]
    if estimated > budget:
        return fail(
            "cost_over_budget",
            f"estimated cost ${estimated} exceeds the declared budget ${budget}",
        )
    if estimated > COST_CAP_USD:
        return fail(
            "cost_over_cap",
            f"estimated cost ${estimated} exceeds the single-film cap ${COST_CAP_USD}",
        )
    floor = _recomputed_cost_usd(calls, output_tokens, input_tokens)
    if estimated < floor - 1e-9:
        return fail(
            "cost_understated",
            f"estimated cost ${estimated} is below the recomputed "
            f"floor ${round(floor, 4)} (model {model}, {calls} calls, "
            f"{output_tokens} output tokens each)",
        )
    version = plan.get("hyperframes_version")
    if not isinstance(version, str) or not version.strip():
        return fail(
            "hyperframes_version_unpinned",
            "hyperframes_version must be pinned before any paid call",
        )
    if plan.get("anthropic_key_connected") is not True:
        return fail(
            "anthropic_key_missing",
            "no Anthropic key is connected here: a paid generation "
            "call cannot run until Soffy approves a key and a budget",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
        "cost_floor_usd": round(floor, 4),
        "cost_cap_usd": COST_CAP_USD,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_paid_generation_cost(params.get("plan"))
    report_path = out_dir / "paid_generation_cost_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_paid_generation_cost_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.paid_generation_cost_gate",
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
                "paid generation cost gate: no paid call without a "
                "declared model, max_tokens, estimated cost and "
                "budget; single-film cap $0.50, HyperFrames version "
                "pinned, Anthropic key connected."
            ),
        )
    )
    return ["qa.paid_generation_cost_gate"]


__all__ = [
    "COST_CAP_USD",
    "COST_REALISTIC_HIGH_USD",
    "COST_REALISTIC_LOW_USD",
    "INPUT_PRICE_PER_MTOK",
    "OUTPUT_PRICE_PER_MTOK",
    "check_paid_generation_cost",
    "register_paid_generation_cost_gate_capabilities_once",
]
