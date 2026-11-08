"""Four-thread collaboration contract (``video.four_thread_contract``).

Fake-level contract for the four-thread working mode
described in the Eian workflow review (see
``EIAN_WORKFLOW_ATTRIBUTION.md``): one lead maker, one
reviewer who only finds faults, one supervisor who keeps
the list of the director's stated requirements, and one
agent who decides by the director's stated preferences
within a fixed budget. The contract certifies the shape
of the collaboration only. It opens no agents and spends
nothing: every compiled contract declares
``executed_here: false``. The four roles are mapped to
hevi and veya mechanisms for reference only — the
reviewer to the blind-review gate, the supervisor to a
standing decision ledger, the agent to an approval card —
and the mapping is not an equivalence claim. Any plan
claiming equivalence fails outright.
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

ROLES: tuple[str, ...] = ("lead", "reviewer", "supervisor", "agent")


def compile_four_thread_contract(plan: Any) -> dict[str, Any]:
    """Compile one four-thread collaboration contract.

    ``plan`` carries ``roles`` (all four), ``budget``
    (currency and amount), ``decisions`` (each with a
    decision, a basis and a confidence), and optionally
    ``estimated_cost`` and ``review_passed``. Raises
    :class:`CapabilityError` on any shape violation, on a
    missing role, on a decision without a stated basis,
    on a submission without a reviewer pass, on an
    estimated cost above budget, or on any claim that the
    four threads are equivalent to hevi or veya
    mechanisms. The returned contract records that
    nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("four-thread plan must be an object")
    if plan.get("executed_here") is True:
        raise CapabilityError(
            "thread execution claims are refused here; this contract executes nothing"
        )
    if plan.get("claims_equivalence") is True:
        raise CapabilityError(
            "the four threads are a mapping only; equivalence to hevi "
            "or veya mechanisms is not claimed"
        )
    if plan.get("mapping_only") is not True:
        raise CapabilityError(
            "four-thread plan must declare mapping_only: the roles map "
            "to hevi and veya mechanisms for reference only"
        )
    roles = plan.get("roles")
    if not isinstance(roles, dict):
        raise CapabilityError("four-thread plan requires a roles object")
    for role in ROLES:
        if not isinstance(roles.get(role), str) or not roles[role].strip():
            raise CapabilityError(f"four-thread plan is missing its {role} role")
    budget = plan.get("budget")
    if not isinstance(budget, dict):
        raise CapabilityError("four-thread plan requires a budget")
    amount = budget.get("amount")
    if not isinstance(amount, (int, float)) or amount <= 0:
        raise CapabilityError("four-thread budget amount must be a positive number")
    if not isinstance(budget.get("currency"), str) or not budget["currency"].strip():
        raise CapabilityError("four-thread budget needs a currency")
    decisions = plan.get("decisions")
    if not isinstance(decisions, list):
        raise CapabilityError("four-thread plan requires a decisions list")
    for position, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            raise CapabilityError(f"decision {position} must be an object")
        if not isinstance(decision.get("decision"), str) or not decision["decision"].strip():
            raise CapabilityError(f"decision {position} must state its decision")
        if not isinstance(decision.get("basis"), str) or not decision["basis"].strip():
            raise CapabilityError(f"decision {position} must state its basis")
    if plan.get("submitted") is True:
        if plan.get("review_passed") is not True:
            raise CapabilityError("nothing is submitted without a reviewer pass")
        estimated = plan.get("estimated_cost")
        if isinstance(estimated, (int, float)) and estimated > amount:
            raise CapabilityError("estimated cost is above budget; submission stops here")
    return {
        "contract": "four-thread",
        "roles": {role: roles[role] for role in ROLES},
        "budget": {"currency": budget["currency"], "amount": amount},
        "decision_count": len(decisions),
        "mapping_only": True,
        "executed_here": False,
        "submitted": bool(plan.get("submitted", False)),
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_four_thread_contract(params.get("plan"))
    report_path = out_dir / "four_thread_contract.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "decision_count": report["decision_count"],
            "executed_here": False,
        },
    )


def register_four_thread_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.four_thread_contract",
            kind="video",
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
            layer="obase",
            description=(
                "Four-thread collaboration contract (fake): lead, "
                "reviewer, supervisor and agent roles, budget cap, "
                "decisions with stated bases; mapping only, no "
                "equivalence to hevi or veya mechanisms."
            ),
        )
    )
    return ["video.four_thread_contract"]


__all__ = [
    "ROLES",
    "compile_four_thread_contract",
    "register_four_thread_contract_capabilities_once",
]
