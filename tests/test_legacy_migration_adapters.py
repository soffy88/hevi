import asyncio

import pytest

from hevi.production_graph.adapters.canvas import (
    CanvasProjectionError,
    canvas_graph_to_projection,
    canvas_semantic_patch,
)
from hevi.production_graph.adapters.studio import (
    production_plan_to_legacy_slots,
    slate_to_production_plan,
)
from hevi.production_graph.domain import ProductionPlan
from hevi.production_graph.migration import (
    MigrationProjectionError,
    canonical_first_read,
    canonical_first_write,
)
from hevi.studio.slate import Slate


def test_canvas_is_a_projection_and_semantic_edits_require_canonical_identity() -> None:
    projection = canvas_graph_to_projection(
        {
            "id": "canvas-1",
            "nodes_json": [
                {
                    "node_id": "n1",
                    "node_type": "shot",
                    "label": "SH01",
                    "config": {"production_object_id": "shot-1", "production_type": "shots"},
                    "position": {"x": 10, "y": 20},
                }
            ],
            "edges_json": [],
        },
        project_id="project-1",
        revision_id="revision-1",
    )
    assert projection.nodes[0].production_object_id == "shot-1"
    assert canvas_semantic_patch(
        project_id="project-1",
        revision_id="revision-1",
        actor="user",
        reason="move node",
        node=projection.nodes[0].model_dump(),
        field="position",
        value={"x": 100, "y": 200},
    ) is None
    patch = canvas_semantic_patch(
        project_id="project-1",
        revision_id="revision-1",
        actor="user",
        reason="change action",
        node=projection.nodes[0].model_dump(),
        field="action_description",
        value="runs",
    )
    assert patch is not None
    assert patch.operations[0].path == "/shots/shot-1/action_description"
    with pytest.raises(CanvasProjectionError):
        canvas_semantic_patch(
            project_id="project-1",
            revision_id="revision-1",
            actor="user",
            reason="unsafe edit",
            node={"node_id": "n2", "config": {}},
            field="action_description",
            value="runs",
        )


def test_studio_slate_round_trip_preserves_canonical_ids_as_projection_metadata() -> None:
    plan = ProductionPlan(
        id="plan-1",
        project_id="project-1",
        revision_id="revision-1",
        shot_ids=["shot-1"],
    )
    slate = Slate(
        line_id="explainer",
        slate_id="slate-1",
        slots=production_plan_to_legacy_slots(plan),
    )
    imported = slate_to_production_plan(slate, project_id="project-1", revision_id="revision-1")
    assert imported.id == plan.id
    assert imported.shot_ids == plan.shot_ids
    assert imported.legacy_ids["studio.slate_id"] == "slate-1"


def test_dual_read_write_is_canonical_first_and_reversible_on_projection_failure() -> None:
    assert canonical_first_read({"value": "canonical"}, lambda: {"value": "legacy"}) == (
        {"value": "canonical"},
        "canonical",
    )

    async def run() -> None:
        calls: list[str] = []

        async def canonical_writer() -> str:
            calls.append("canonical")
            return "revision"

        async def projector(_: str) -> None:
            calls.append("legacy")

        result = await canonical_first_write(canonical_writer, projector)
        assert result == ("revision", "projected")
        assert calls == ["canonical", "legacy"]

        async def broken(_: str) -> None:
            raise RuntimeError("legacy unavailable")

        with pytest.raises(MigrationProjectionError, match="canonical write committed"):
            await canonical_first_write(canonical_writer, broken)

    asyncio.run(run())
