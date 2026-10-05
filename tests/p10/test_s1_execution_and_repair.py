"""S1-6 / S1-8 接线验收:MissionExecutor substrate + RepairIncident canonical。"""

import pytest

from hevi.creative.autonomous.execution import (
    STAGE_TO_NODE_KIND,
    build_plan_nodes,
    build_stage_runners,
    prepare_mission,
    to_run_ref,
)
from hevi.creative.autonomous.repair import (
    FAILURE_TO_KIND,
    RepairRequest,
    authorize_auto_safe,
    open_repair,
    to_kind,
)
from hevi.creative.layer4.repair_incident import (
    RepairActionProposal,
    RepairPolicy,
    SelfHealingCoordinator,
)
from hevi.missions.p3_runtime import MissionExecutor
from hevi.missions.p3_types import NodeKind

STAGES = (
    {"stage": "SCRIPT", "status": "PENDING"},
    {"stage": "STORYBOARD", "status": "PENDING", "payload": {"shots": 3}},
    {"stage": "ASSET_PLAN", "status": "PENDING"},
    {"stage": "VOICE", "status": "PENDING"},
    {"stage": "EDIT", "status": "PENDING"},
    {"stage": "RENDER", "status": "PENDING", "estimated_cost_usd": 2.0},
    {"stage": "QC", "status": "PENDING"},
    {"stage": "DELIVERY", "status": "PENDING"},
)


# ── S1-6 ──
def test_plan_nodes_use_existing_node_kinds_only():
    plan = build_plan_nodes(STAGES, plan_id="p", mission_id="m")
    kinds = {node.kind for node in plan.nodes}
    assert kinds <= {str(k) for k in NodeKind}
    assert {str(k) for k in NodeKind} >= kinds
    assert "SCRIPT" in kinds and "RENDER" in kinds


def test_plan_nodes_dependencies_are_linear_and_idempotency_key_canonical():
    plan = build_plan_nodes(STAGES, plan_id="p", mission_id="m", revision=2)
    ids = [n.node_id for n in plan.nodes]
    assert plan.nodes[0].dependencies == ()
    assert all(node.dependencies == (ids[i - 1],)
               for i, node in enumerate(plan.nodes) if i)
    for node in plan.nodes:
        assert node.idempotency_key == f"m:{node.node_id}:v2"


def test_unknown_stage_is_rejected_not_invented():
    with pytest.raises(ValueError, match="UNKNOWN_STAGE_FOR_CANONICAL_KIND"):
        build_plan_nodes(({"stage": "AUTONOMOUS_ORCHESTRATION"},), plan_id="p", mission_id="m")


def test_prepare_mission_uses_existing_executor_substrate(tmp_path):
    mission, _plan = prepare_mission(root=tmp_path, request="一个45秒视频",
                                    profile_id="default", stages=STAGES)
    ref = to_run_ref(mission)
    assert ref.executor_class.endswith("MissionExecutor")
    assert mission.plan is not None and mission.plan.plan_id.endswith(":autonomous")
    # mission 持久化后由既有 store 承载(durable substrate)
    from hevi.missions.p3_runtime import MissionStore

    assert MissionStore(tmp_path).load() is not None
    assert len(ref.node_ids) == len(STAGES)


def test_stage_runners_reject_non_canonical_kinds():
    with pytest.raises(ValueError, match="NON_CANONICAL_NODE_KIND"):
        build_stage_runners({"AUTONOMOUS_ORCHESTRATION": lambda *a: {"actual_cost_usd": 0.0}})


async def test_mission_executor_runs_with_injected_adapters(tmp_path):
    """真跑既有 executor:adapter 是注入的既有 NodeRunner,不是新建 runner 类。"""
    from hevi.missions.p3_runtime import MissionStore

    mission, _plan = prepare_mission(root=tmp_path, request="r", profile_id="default",
                                     stages=STAGES)
    executed: list[str] = []

    def make_adapter(kind: str):
        def _run(mission_arg, node, store):
            executed.append(kind)
            return {"actual_cost_usd": 0.0, "artifact_ids": []}
        return _run

    runners = {str(k): make_adapter(str(k)) for k in NodeKind}
    executor = MissionExecutor(MissionStore(tmp_path), runners, max_parallel=1)
    await executor.run(mission)
    assert "SCRIPT" in executed and "DELIVERY" in executed
    assert all(n.status in ("COMPLETED", "BLOCKED") for n in mission.plan.nodes)


# ── S1-8 ──
def test_failure_codes_map_to_existing_repair_kinds():
    for code, kind in FAILURE_TO_KIND.items():
        assert to_kind(code) is kind
    assert str(to_kind("SOMETHING_NEW")) == "retry_target"  # 未知失败不静默特判


def test_repair_goes_through_existing_coordinator():
    coordinator = SelfHealingCoordinator()
    incident = open_repair(coordinator, RepairRequest(
        production_run_id="run-1", node_key="render:0", failure_code="RENDER_FAILED",
        artifact_id="a1"))
    # 返回的是既有 RepairIncident,不是本包新类型
    assert type(incident).__name__ == "RepairIncident"
    assert incident.status.value == "open"
    # root_cause 由既有 classify_deterministic 决定 —— adapter 不预设分类
    from hevi.creative.layer4.repair_incident import RootCauseCategory
    assert incident.root_cause in set(RootCauseCategory)


def test_auto_safe_zero_cost_allowed_but_cost_bearing_needs_project_optin():
    """既有语义:project policy 只门控 cost-bearing 动作(默认不允许自动花费)。

    AUTO_SAFE + 零成本 → 放行;AUTO_SAFE + 花费 → 必须项目显式 opt-in。
    """
    coordinator = SelfHealingCoordinator()  # allow_budget_bound_auto_repair=False
    incident = open_repair(coordinator, RepairRequest(
        production_run_id="run-2", node_key="render:1", failure_code="RENDER_FAILED"))
    assert authorize_auto_safe(coordinator, incident.incident_id, cost_usd=0.0)[0] is True

    paid = SelfHealingCoordinator()
    incident2 = open_repair(paid, RepairRequest(
        production_run_id="run-3", node_key="render:2", failure_code="RENDER_FAILED"))
    allowed, reason = authorize_auto_safe(paid, incident2.incident_id, cost_usd=5.0)
    assert allowed is False and reason


def test_repair_policy_values_are_the_canonical_ones():
    assert {p.value for p in RepairPolicy} == {"auto_safe", "confirm_required", "manual_only"}
    proposal = RepairActionProposal(kind=to_kind("ASSET_MISSING"), policy=RepairPolicy.AUTO_SAFE)
    assert proposal.policy is RepairPolicy.AUTO_SAFE


def test_stage_to_node_kind_covers_repair_and_qc():
    assert STAGE_TO_NODE_KIND["QC"] is NodeKind.QA
    assert STAGE_TO_NODE_KIND["REPAIR"] is NodeKind.REPAIR
    assert STAGE_TO_NODE_KIND["RENDER"] is NodeKind.RENDER