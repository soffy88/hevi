"""Adapters for the RC6 Studio/Slate projection."""

from __future__ import annotations

from typing import Any

from hevi.production_graph.domain import ProductionMode, ProductionPlan
from hevi.studio.slate import Slate


def slate_to_production_plan(slate: Slate, *, project_id: str, revision_id: str) -> ProductionPlan:
    """Import an existing Slate without making its slots canonical state."""

    raw_mode = str(slate.slots.get("production_mode") or ProductionMode.AUTO.value)
    try:
        mode = ProductionMode(raw_mode)
    except ValueError:
        mode = ProductionMode.AUTO
    return ProductionPlan(
        id=str(slate.slots.get("production_plan_id") or f"slate:{slate.slate_id}"),
        project_id=project_id,
        revision_id=revision_id,
        shot_ids=[str(item) for item in slate.slots.get("canonical_shot_ids") or []],
        mode=mode,
        legacy_ids={"studio.slate_id": slate.slate_id, "studio.line_id": slate.line_id},
    )


def production_plan_to_legacy_slots(
    plan: ProductionPlan, *, slots: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Project canonical identifiers into old recipe slots for RC6 readers."""

    result = dict(slots or {})
    result.update(
        {
            "production_plan_id": plan.id,
            "production_project_id": plan.project_id,
            "production_revision_id": plan.revision_id,
            "canonical_shot_ids": list(plan.shot_ids),
            "production_mode": plan.mode.value,
        }
    )
    return result


def studio_snapshot_projection(snapshot: Any) -> dict[str, Any]:
    """Return a stable legacy-friendly projection of a canonical snapshot."""

    return {
        "project_id": snapshot.project.id,
        "revision_id": snapshot.revision.id,
        "title": snapshot.project.title,
        "episodes": [item.model_dump(mode="json") for item in snapshot.episodes],
        "scenes": [item.model_dump(mode="json") for item in snapshot.scenes],
        "shots": [item.model_dump(mode="json") for item in snapshot.shots],
        "production_plans": [item.model_dump(mode="json") for item in snapshot.production_plans],
    }


__all__ = [
    "production_plan_to_legacy_slots",
    "slate_to_production_plan",
    "studio_snapshot_projection",
]
