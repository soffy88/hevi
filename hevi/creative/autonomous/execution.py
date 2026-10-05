"""S1-6:canonical execution substrate = `missions/p3_runtime.MissionExecutor`。

裁决:不创建 AutonomousRunner / ProductionOrchestrator / PipelineExecutor。
本模块只做**接线**:Director 计划 → 既有 PlanNode/NodeKind → 既有 MissionExecutor。

既有事实(不得掩盖):
- `MissionExecutor.__init__(store, runners, max_parallel=2, crash_after=-1)`
- `NodeRunner = Callable[[ProductionMission, PlanNode, MissionStore], Any]`,
  必须返回含 `actual_cost_usd` 的 dict(否则预算无法累计)。
- mission 的 `provider_policy` 是 **p3_types 自己的 dataclass**,不是
  `hevi.provider_policy` 的 pydantic 模型 —— 这是第 4 套词汇,接线时不得混用。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hevi.missions.p3_runtime import MissionExecutor, MissionStore, create_mission
from hevi.missions.p3_types import (
    ArtifactRecord,
    NodeKind,
    PlanNode,
    ProductionMission,
    ProductionPlan,
)

# 复用既有类型别名;不定义任何 *Runner 类
NodeRunner = Callable[[ProductionMission, PlanNode, MissionStore], Any]

# Director 阶段 → 既有 NodeKind。不新增 kind。
STAGE_TO_NODE_KIND = {
    "SCRIPT": NodeKind.SCRIPT,
    "VOICE": NodeKind.AUDIO,
    "STORYBOARD": NodeKind.SHOT,
    "ASSET_PLAN": NodeKind.ASSET,
    "ASSET_RESOLVE": NodeKind.ASSET,
    "EDIT": NodeKind.EDIT,
    "RENDER": NodeKind.RENDER,
    "QC": NodeKind.QA,
    "REPAIR": NodeKind.REPAIR,
    "DELIVERY": NodeKind.DELIVERY,
}


@dataclass(frozen=True)
class CanonicalRunRef:
    """指向一次「用既有 substrate 跑」的结果。不持有执行权。"""
    mission_id: str
    plan_id: str
    node_ids: tuple[str, ...]

    @property
    def executor_class(self) -> str:
        return f"{MissionExecutor.__module__}.{MissionExecutor.__qualname__}"


def build_plan_nodes(stages: tuple[dict[str, Any], ...], *, plan_id: str,
                     mission_id: str, revision: int = 1) -> ProductionPlan:
    """阶段字典 → 既有 PlanNode 列表。

    idempotency_key 沿用既有格式 `{mission_id}:{node_id}:v{revision}`
    (与 p3_runtime.build_plan 同构,不引入第二套键规则)。
    """
    nodes: list[PlanNode] = []
    previous: str | None = None
    for index, stage in enumerate(stages):
        stage_name = str(stage.get("stage", ""))
        kind = STAGE_TO_NODE_KIND.get(stage_name)
        if kind is None:
            raise ValueError(f"UNKNOWN_STAGE_FOR_CANONICAL_KIND:{stage_name}")
        node_id = f"{mission_id}:{index:02d}:{stage_name.lower()}"
        nodes.append(PlanNode(
            node_id=node_id, kind=str(kind), label=stage_name,
            dependencies=() if previous is None else (previous,),
            status=str(stage.get("status", "PENDING")),
            estimated_cost_usd=float(stage.get("estimated_cost_usd", 0.0)),
            idempotency_key=f"{mission_id}:{node_id}:v{revision}",
            payload=dict(stage.get("payload", {})),
        ))
        previous = node_id
    return ProductionPlan(plan_id=plan_id, nodes=nodes, revision=revision)


def build_stage_runners(adapters: dict[str, Any]) -> dict[str, NodeRunner]:
    """校验 adapter 覆盖情况。缺 runner 的 kind 在既有 executor 里会 FAILED。"""
    runners: dict[str, NodeRunner] = {}
    for key, fn in adapters.items():
        kind = getattr(key, "value", key)
        canonical = STAGE_TO_NODE_KIND.get(str(kind).upper())
        if canonical is None and str(kind) not in {k.value for k in NodeKind}:
            raise ValueError(f"NON_CANONICAL_NODE_KIND:{kind}")
        runners[str(kind)] = fn
    return runners


def prepare_mission(*, root: Any, request: str, profile_id: str,
                    stages: tuple[dict[str, Any], ...],
                    budget_usd: float = 50.0) -> tuple[ProductionMission, ProductionPlan]:
    """创建 mission 并装上 Director 派生的 plan。不执行。"""
    mission, store = create_mission(root, request, profile_id,
                                    budget_usd=budget_usd)
    plan = build_plan_nodes(stages, plan_id=f"{mission.mission_id}:autonomous",
                            mission_id=mission.mission_id)
    mission.plan = plan
    store.save(mission)
    return mission, plan


def to_run_ref(mission: ProductionMission) -> CanonicalRunRef:
    plan = mission.plan
    return CanonicalRunRef(
        mission_id=mission.mission_id,
        plan_id=plan.plan_id if plan else "",
        node_ids=tuple(n.node_id for n in (plan.nodes if plan else [])),
    )


def artifact_projection(mission: ProductionMission) -> tuple[dict[str, Any], ...]:
    """artifact 记录投影(供 production_manifest 消费)。"""
    return tuple({"artifact_id": aid, "type": rec.type, "status": rec.status,
                  "hash": rec.hash, "producer": rec.producer}
                 for aid, rec in sorted(mission.artifacts.items()))


__all__ = [
    "STAGE_TO_NODE_KIND",
    "ArtifactRecord",
    "CanonicalRunRef",
    "NodeKind",
    "NodeRunner",
    "artifact_projection",
    "build_plan_nodes",
    "build_stage_runners",
    "prepare_mission",
    "to_run_ref",
]