import pytest

from hevi.production_graph import ProductionMode, ProductionPlan
from hevi.studio.slate_bridge import production_plan_to_slate


def test_production_plan_becomes_a_deterministic_slate_work_order() -> None:
    plan = ProductionPlan(
        id="plan-1",
        project_id="project-1",
        revision_id="revision-1",
        shot_ids=["shot-1", "shot-2"],
        mode=ProductionMode.SHOT_REVIEW,
    )
    slate = production_plan_to_slate(
        plan,
        line_id="explainer",
        slots={"topic": "canonical work order"},
        slate_id="slate-1",
    )
    assert slate.slate_id == "slate-1"
    assert slate.execute is False
    assert slate.slots["production_plan_id"] == plan.id
    assert slate.slots["canonical_shot_ids"] == plan.shot_ids
    assert slate.slots["production_mode"] == "SHOT_REVIEW"


def test_bridge_does_not_accept_an_empty_line() -> None:
    plan = ProductionPlan(project_id="project-1", revision_id="revision-1")
    with pytest.raises(ValueError, match="line_id"):
        production_plan_to_slate(plan, line_id=" ")
