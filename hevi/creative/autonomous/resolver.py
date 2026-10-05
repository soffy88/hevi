"""AssetResolver —— **adapter only**。

裁决(2026-10-03):Resolver 只描述「怎么执行 decision」,不描述「怎么产生 decision」。
它**没有** calculate_score / rank_candidates / pick_best_provider / override_decision。

顺序(由 authority 决定,不由本模块决定):
    requirement → provider_policy(权威选择) → p7 AssetDecisionAuthority(权威决策)
    → Resolver 执行 acquisition → 回填 evidence → 复算 decision → execution-ready

Resolver 允许做的:调用 provider_policy、调用 p7、执行获取与 media 探测、回填证据。
Resolver 禁止做的:自己排序、自己打分、自己挑 provider、覆盖 p7 的 BLOCKED。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from hevi.creative.autonomous.canonical import (
    AssetDecisionAuthority,
    AssetDecisionState,
    AssetRequirement,
    AssetResolution,
)
from hevi.production.p7.evidence import AssetEvidence

FORBIDDEN_METHODS = ("calculate_score", "rank_candidates", "pick_best_provider",
                     "override_decision", "score_candidate")


@runtime_checkable
class Acquirer(Protocol):
    """执行侧能力:按 provider 决策去拿素材并回证据。本包不实现它。"""

    async def acquire(self, requirement: AssetRequirement, provider_id: str,
                      context: dict[str, Any]) -> tuple[str, AssetEvidence]:
        ...


@dataclass(frozen=True)
class ExecutionReadyResolution:
    """execution-ready 结果。decision 字段始终来自 p7,本模块不改写。"""
    requirement_id: str
    decision_state: str
    provider_id: str
    selected_source: str
    evidence_ids: tuple[str, ...] = ()
    reason: str = ""
    blocked: bool = False

    @property
    def usable(self) -> bool:
        return not self.blocked and self.decision_state == AssetDecisionState.ACCEPTED


class AssetResolver:
    """Coordination layer。selection authority 在 provider_policy + p7,不在这里。"""

    def __init__(self, *, authority: AssetDecisionAuthority | None = None,
                 acquirer: Acquirer | None = None) -> None:
        self._authority = authority or AssetDecisionAuthority()
        self._acquirer = acquirer
        for name in FORBIDDEN_METHODS:
            if hasattr(self, name):
                raise AttributeError(f"RESOLVER_OVERREACH:{name} is not a resolver responsibility")

    async def resolve(self, requirement: AssetRequirement, *,
                      provider_decision: Any,
                      context: dict[str, Any] | None = None) -> ExecutionReadyResolution:
        """provider_decision 必须由 provider_policy 产出(权威)。这里只消费。

        未传 provider_decision → p7 直接 BLOCKED(NO_PROVIDER_DECISION),不兜底。
        """
        context = context or {}
        if provider_decision is None:
            resolution = self._authority.decide(requirement, provider_decision=None)
            return self._to_ready(requirement, resolution)

        provider_id = getattr(provider_decision, "selected_provider", "") or ""
        if self._acquirer is not None and provider_id:
            source, evidence = await self._acquirer.acquire(requirement, provider_id, context)
            resolution = self._authority.decide(
                requirement, provider_decision=provider_decision,
                selected_source=source, evidence=(evidence,) if evidence else (),
                policy_id="autonomous/resolver")
        else:
            # 无执行侧能力时只做决策投影,不伪造 selected_source(p7 会因 NO_ASSET_OBTAINED 阻塞)
            resolution = self._authority.decide(
                requirement, provider_decision=provider_decision,
                policy_id="autonomous/resolver")
        return self._to_ready(requirement, resolution, provider_id=provider_id)

    def _to_ready(self, requirement: AssetRequirement, resolution: AssetResolution,
                  provider_id: str = "") -> ExecutionReadyResolution:
        decision = resolution.decision
        resolved_provider = provider_id or (
            decision.provider_decision.selected_provider or ""
            if decision.provider_decision else "")
        return ExecutionReadyResolution(
            requirement_id=requirement.requirement_id,
            decision_state=str(decision.state),
            provider_id=resolved_provider,
            selected_source=decision.selected_source,
            evidence_ids=decision.evidence_ids(),
            reason=decision.reason,
            blocked=decision.state is not AssetDecisionState.ACCEPTED,
        )


__all__ = [
    "FORBIDDEN_METHODS",
    "Acquirer",
    "AssetResolver",
    "ExecutionReadyResolution",
]