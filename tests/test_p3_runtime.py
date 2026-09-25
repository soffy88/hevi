"""P3 Autonomous Production Runtime — fast unit tests (no TTS/render)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from hevi.missions.p3_runners import RUNNERS
from hevi.missions.p3_runtime import (
    MissionExecutor,
    MissionStore,
    build_chapters,
    build_plan,
    build_research,
    build_script,
    classify_failure,
    create_mission,
    invalidate_dependents,
    plan_graph_edges,
    status_view,
)
from hevi.missions.p3_types import PlanNode, validate_mission_transition


def _mission(tmp_path: Path, narration: str):
    root = tmp_path / "m"
    mission, store = create_mission(
        root, request="test", profile_id="SCIENCE_EXPLAINER",
        production_goal="test", target_duration_s=60.0, budget_usd=50.0)
    mission.set_status("PLANNING")
    mission.set_status("RESEARCHING")
    mission.research_bundle = build_research(mission.request, narration)
    mission.set_status("SCRIPTING")
    mission.script = build_script(mission.research_bundle, narration, mission.profile_id)
    mission.set_status("PLANNED")
    mission.plan = build_plan(mission, narration, segments_per_chapter=3)
    build_chapters(mission, narration, segments_per_chapter=3)
    store.save(mission)
    return mission, store


def test_mission_transitions_valid() -> None:
    validate_mission_transition("CREATED", "PLANNING")
    validate_mission_transition("PLANNED", "PRODUCING")
    validate_mission_transition("FINALIZING", "REPAIRING")
    with pytest.raises(ValueError):
        validate_mission_transition("CREATED", "COMPLETED")


def test_plan_structure_and_deps(tmp_path: Path) -> None:
    mission, _store = _mission(tmp_path, "Black hole gravity orbit. " * 4)
    assert mission.plan is not None
    kinds = [n.kind for n in mission.plan.nodes]
    assert kinds[0] == "RESEARCH" and kinds[1] == "SCRIPT"
    assert kinds[-2] == "EDIT" and kinds[-1] == "DELIVERY"
    render_nodes = [n for n in mission.plan.nodes if n.kind == "RENDER"]
    assert len(render_nodes) >= 3
    edges = plan_graph_edges(mission.plan)
    assert edges["script"] == ["research"]
    assert set(edges["fanin"]) == {f"segment-{i}" for i in range(len(render_nodes))}
    assert edges["delivery"] == ["fanin"]
    ready = mission.plan.ready_nodes()
    assert [n.node_id for n in ready] == ["research"]


def test_research_grounding_blocks_unverified(tmp_path: Path) -> None:
    from hevi.missions.p3_types import ClaimRecord, ResearchBundle

    # Invented content with no known source is classified as original
    # expression (allowed), never as an unverified fact.
    bundle = build_research("test", "Completely invented blorptar physics with no source.")
    assert not bundle.unverified_fact_claims()
    assert all(c.kind == "original_expression" for c in bundle.claims)
    # An unverified *fact* claim must fail closed.
    from hevi.missions.p3_runners import assert_research_grounded

    bad = ResearchBundle(
        bundle_id="b", sources=[],
        claims=[ClaimRecord(claim_id="c", statement="x", kind="fact", verified=False)])
    with pytest.raises(RuntimeError, match="UNVERIFIED_CLAIM_PRODUCTION"):
        assert_research_grounded(bad)


def test_script_blocks_unverified_quotes() -> None:
    from hevi.missions.p3_types import NarrationBlock, ScriptDocument, ScriptSection
    script = ScriptDocument(script_id="s", sections=[ScriptSection(
        section_id="sec", title="t",
        blocks=[NarrationBlock(block_id="b", text="famous quote", kind="quotation", verified=False)])])
    assert script.unverified_quotes()


def test_classify_failure_mapping() -> None:
    assert classify_failure(PlanNode(node_id="x", kind="QA", error="visual quality policy blocked artifact")) == "VISUAL_QA"
    assert classify_failure(PlanNode(node_id="x", kind="RENDER", error="TTS timeout")) == "AUDIO"
    assert classify_failure(PlanNode(node_id="x", kind="RENDER", error="unverified source claim")) == "SOURCE_TRUTH"


def test_invalidate_dependents_resets_downstream(tmp_path: Path) -> None:
    mission, _store = _mission(tmp_path, "Black hole gravity orbit. " * 4)
    assert mission.plan is not None
    for n in mission.plan.nodes:
        n.status = "COMPLETED"
    reset = invalidate_dependents(mission, ("segment-0",))
    assert "fanin" in reset and "delivery" in reset
    # The changed node itself must also re-run (its inputs changed).
    assert "segment-0" in reset
    assert mission.plan.node("segment-0").status == "PENDING"


def test_budget_blocks_over_ceiling(tmp_path: Path) -> None:
    mission, _store = _mission(tmp_path, "Black hole gravity orbit. " * 4)
    mission.budget.max_total_cost_usd = 0.5
    ok, reason = mission.budget.check(1.0)
    assert not ok and reason == "BUDGET_BLOCKED"


def test_runners_cover_all_node_kinds(tmp_path: Path) -> None:
    mission, _store = _mission(tmp_path, "Black hole gravity orbit. " * 4)
    assert mission.plan is not None
    kinds = {n.kind for n in mission.plan.nodes}
    assert kinds <= set(RUNNERS), f"missing runners for {kinds - set(RUNNERS)}"


def test_cancel_marks_pending_nodes(tmp_path: Path) -> None:
    mission, store = _mission(tmp_path, "Black hole gravity orbit. " * 4)
    store.request_cancel()

    async def _noop(m: object, n: PlanNode, s: MissionStore) -> dict[str, object]:
        return {"artifact_ids": [], "actual_cost_usd": 0.0}

    ex = MissionExecutor(store, {"RESEARCH": _noop, "SCRIPT": _noop, "RENDER": _noop,
                                 "EDIT": _noop, "DELIVERY": _noop})
    out = asyncio.run(ex.run(mission))
    assert out.status == "CANCELLED"
    assert all(n.status == "CANCELLED" for n in (out.plan.nodes if out.plan else []))


def test_idempotency_skips_completed_node(tmp_path: Path) -> None:
    mission, store = _mission(tmp_path, "Black hole gravity orbit. " * 4)
    assert mission.plan is not None
    node = mission.plan.node("research")
    assert node is not None
    node.status = "COMPLETED"
    probe = tmp_path / "m" / "probe.txt"
    probe.write_text("x")
    from hevi.missions.p3_types import ArtifactRecord
    mission.artifacts["aid"] = ArtifactRecord(
        artifact_id="aid", type="research_bundle", producer="research",
        hash="x", status="VALID", path=str(probe))
    node.artifact_ids = ("aid",)
    store.save(mission)

    calls: list[str] = []

    async def _runner(m: object, n: PlanNode, s: MissionStore) -> dict[str, object]:
        calls.append(n.node_id)
        return {"artifact_ids": [], "actual_cost_usd": 0.0}

    ex = MissionExecutor(store, {"RESEARCH": _runner, "SCRIPT": _runner, "RENDER": _runner,
                                 "EDIT": _runner, "DELIVERY": _runner}, max_parallel=1)
    # Only research is ready and it is cached → executor should stop without calling
    asyncio.run(ex.run(mission))
    assert calls == []


def test_status_view_observability(tmp_path: Path) -> None:
    mission, _store = _mission(tmp_path, "Black hole gravity orbit. " * 4)
    view = status_view(mission)
    assert view["total_nodes"] >= 7
    assert view["progress_pct"] == 0.0
    assert "next_dependencies" in view


def test_split_narration_is_contiguous() -> None:
    from hevi.missions.p3_runtime import _split_narration

    sents = [f"Sentence {i}." for i in range(12)]
    parts = _split_narration(" ".join(sents), 3)
    assert len(parts) == 3
    # Contiguous chunks preserve narrative order (never round-robin),
    # with sentence boundaries intact.
    assert parts[0].startswith("Sentence 0. Sentence 1.")
    assert "Sentence 4" in parts[1] and "Sentence 0" not in parts[1]
    assert parts[2].startswith("Sentence 8. Sentence 9.")


def test_no_second_pipeline_in_p3() -> None:
    import inspect

    import hevi.missions.p3_runners as runners
    import hevi.missions.p3_runtime as runtime

    runtime_src = inspect.getsource(runtime)
    assert "remotion_render_workflow" not in runtime_src
    assert "execute_local_media_task" not in runtime_src
    runners_src = inspect.getsource(runners)
    assert "run_p2_production" in runners_src
