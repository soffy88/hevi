"""Bridge canonical ProductionPlan work orders into the existing Slate.

The bridge is intentionally boring: it serializes an already-decided plan
into Slate slots and delegates execution to ``run_slate``.  It does not select
providers, invent shots, or add creative reasoning to the deterministic
runtime.
"""

from __future__ import annotations

from typing import Any

from hevi.production_graph.domain import ProductionPlan
from hevi.studio.slate import Slate, SlateResult, run_slate


def production_plan_to_slate(
    plan: ProductionPlan,
    *,
    line_id: str,
    slots: dict[str, Any] | None = None,
    execute: bool = False,
    slate_id: str | None = None,
) -> Slate:
    """Create a legacy-compatible Slate from an immutable canonical plan."""

    if not line_id.strip():
        raise ValueError("line_id is required for a Slate bridge")
    payload = dict(slots or {})
    payload.update(
        {
            "production_plan_id": plan.id,
            "production_project_id": plan.project_id,
            "production_revision_id": plan.revision_id,
            "canonical_shot_ids": list(plan.shot_ids),
            "production_mode": plan.mode.value,
        }
    )
    return Slate(
        line_id=line_id,
        slots=payload,
        execute=execute,
        slate_id=slate_id or "",
    )


async def run_production_plan(
    plan: ProductionPlan,
    *,
    line_id: str,
    slots: dict[str, Any] | None = None,
    execute: bool = False,
    slate_id: str | None = None,
) -> SlateResult:
    """Execute the canonical work order through the unchanged Slate runtime."""

    slate = production_plan_to_slate(
        plan,
        line_id=line_id,
        slots=slots,
        execute=execute,
        slate_id=slate_id,
    )
    return await run_slate(slate)


__all__ = ["production_plan_to_slate", "run_production_plan"]
