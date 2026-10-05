"""S1-8:失败/修复接线 —— canonical = `creative/layer4/repair_incident.py`。

裁决:`RepairIncident` = canonical 失败/恢复状态;既有 `RepairPolicy`
(AUTO_SAFE / CONFIRM_REQUIRED / MANUAL_ONLY)= canonical 修复许可。

本模块**不定义** RepairPolicy / RepairIncident / RepairPlan / *RepairPlan。
它只把「既有 verdict 的失败」翻译成既有 incident,并按既有 policy 授权。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hevi.creative.layer4.plan_projection import RepairKind
from hevi.creative.layer4.repair_incident import (
    ProjectRepairPolicy,
    RepairActionProposal,
    RepairPolicy,
    SelfHealingCoordinator,
)

# canonical 失败 → canonical RepairKind。不新增 action 词汇。
FAILURE_TO_KIND: dict[str, RepairKind] = {
    "ARTIFACT_INVALID": RepairKind.RESTORE_ASSET,
    "ASSET_MISSING": RepairKind.RESTORE_ASSET,
    "ASSET_ASPECT_MISMATCH": RepairKind.REGENERATE_EXPLICIT,
    "DURATION_MISMATCH": RepairKind.REPLAN,
    "SUBTITLE_TIMING_MISMATCH": RepairKind.REPLAN,
    "SILENT_AUDIO": RepairKind.REGENERATE_EXPLICIT,
    "RENDER_FAILED": RepairKind.RETRY_TARGET,
    "EMPTY_OUTPUT": RepairKind.RETRY_TARGET,
    "QC_THRESHOLD_FAILED": RepairKind.REPLAN,
}


@dataclass(frozen=True)
class RepairRequest:
    """一次修复请求。只描述「什么坏了」,不决定「能不能自动修」。"""
    production_run_id: str
    node_key: str
    failure_code: str
    artifact_id: str = ""
    evidence: dict[str, Any] | None = None


def to_kind(failure_code: str) -> RepairKind:
    """canonical 失败码 → 既有 RepairKind。不新增 action 词汇。"""
    return FAILURE_TO_KIND.get(failure_code, RepairKind.RETRY_TARGET)


def open_repair(coordinator: SelfHealingCoordinator, request: RepairRequest) -> Any:
    """走既有 `SelfHealingCoordinator.open_incident`。返回既有 RepairIncident。

    **root_cause 由既有 `classify_deterministic` 决定**,本模块不预设、不覆盖 ——
    分类是既有 authority 的职责;我们只提供 failure_code 与证据。
    """
    return coordinator.open_incident(
        production_run_id=request.production_run_id,
        node_key=request.node_key,
        failure=request.failure_code,
        artifact_id=request.artifact_id,
        evidence=dict(request.evidence or {}),
    )


def propose(coordinator: SelfHealingCoordinator, incident: Any, *,
            cost_usd: float = 0.0) -> Any:
    """提出既有 RepairActionProposal。policy 默认 CONFIRM_REQUIRED(既有保守默认)。"""
    action = RepairActionProposal(
        kind=to_kind(str(incident.failure_code)), target_id=incident.artifact_id,
        policy=RepairPolicy.CONFIRM_REQUIRED, estimated_cost_usd=cost_usd)
    return coordinator.propose_agent_action(incident.incident_id, action)


def authorize_auto_safe(coordinator: SelfHealingCoordinator, incident_id: str, *,
                        cost_usd: float = 0.0) -> tuple[bool, str]:
    """P0 只允许 AUTO_SAFE:用既有 RepairPolicy.AUTO_SAFE 提案,由既有 coordinator 裁决。

    是否放行取决于 ProjectRepairPolicy.allow_budget_bound_auto_repair(既有默认 False)
    与 loop guard —— 本模块不复制、不绕过这两道闸。
    """
    action = RepairActionProposal(kind=RepairKind.RETRY_TARGET, policy=RepairPolicy.AUTO_SAFE,
                                  estimated_cost_usd=cost_usd)
    return coordinator.authorize(incident_id, action, confirmed=False)


__all__ = [
    "FAILURE_TO_KIND",
    "ProjectRepairPolicy",
    "RepairActionProposal",
    "RepairKind",
    "RepairPolicy",
    "RepairRequest",
    "RootCauseCategory",
    "SelfHealingCoordinator",
    "authorize_auto_safe",
    "open_repair",
    "propose",
    "to_kind",
]