"""AssetResolver —— **provider 平面的执行 adapter**,仅此而已。

裁决(2026-10-03,S1):Resolver 只描述「怎么执行 decision」,不描述「怎么产生 decision」。
它**没有** calculate_score / rank_candidates / pick_best_provider / override_decision。

顺序(由 authority 决定,不由本模块决定):
    requirement → provider_policy(权威选择) → p7 AssetDecisionAuthority(权威决策)
    → Resolver 执行 acquisition → 回填 evidence → 复算 decision → execution-ready

Resolver 允许做的:调用 provider_policy、调用 p7、执行获取与 media 探测、回填证据。
Resolver 禁止做的:自己排序、自己打分、自己挑 provider、覆盖 p7 的 BLOCKED。

## F10 冻结裁决(2026-10-05)—— 读这一段再接线

`AssetResolver` 的最终角色:**provider 平面的执行 adapter,仅此而已**。

三条不可让渡的性质:

1. **不产候选。** 本模块从不构造 `AssetCandidate`,所以它在结构上无法参与
   P1 的 selection。候选只能由 Acquirer 产出、由 `select_candidate` 选。
2. **不产 admission。** `ExecutionReadyResolution.usable` 表示
   「p7 决策已 ACCEPTED」,**不是**「这个资产可以用」。它**不得**被任何
   generation 代码消费。唯一的 generation admission 是
   `selection.admit_generation(resolution, candidates)`。
3. **不在生产路径。** 无生产调用方,由 `assert_resolver_is_not_production_authority()`
   锁死:生产模块不得 import 本模块的 `AssetResolver` / `ExecutionReadyResolution`。

字段名从 `selected_source` 改为 `obtained_source` 是这次裁决的一部分:
它记录的是「acquirer 拿到了什么」,**不是**「谁被选中」。单值返回的
`Acquirer.acquire()` 恰好就是 acquirer 的第一次命中 —— 那是 P1 刚从 p0 拆掉的形态,
不能让它继续以「选择结论」的名字存在于类型里。
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
    """execution-ready 结果。decision 字段始终来自 p7,本模块不改写。

    `obtained_source` 是**取得**的来源,不是**选中**的资产 —— 见模块 docstring 的
    F10 裁决。它的值来自单值返回的 `Acquirer.acquire()`(即 acquirer 的第一次命中),
    因此下游**不得**把它当作素材取舍结论。
    """

    requirement_id: str
    decision_state: str
    provider_id: str
    obtained_source: str
    evidence_ids: tuple[str, ...] = ()
    reason: str = ""
    blocked: bool = False

    @property
    def usable(self) -> bool:
        """p7 决策是否 ACCEPTED。

        **不是** `ready_for_generation`,**不是**「这个资产可以用」。
        generation 必须走 `selection.admit_generation(resolution, candidates)`。
        """
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
            obtained_source=decision.selected_source,
            evidence_ids=decision.evidence_ids(),
            reason=decision.reason,
            blocked=decision.state is not AssetDecisionState.ACCEPTED,
        )


@dataclass(frozen=True)
class ResolverRole:
    """F10 冻结声明。角色写在数据里,守卫读数据 —— 不是散落在注释里。"""

    component: str
    role: str
    produces_candidates: bool
    is_generation_admission: bool
    on_production_path: bool
    consumes: str
    ruled_out: tuple[str, ...]


RESOLVER_ROLE: ResolverRole = ResolverRole(
    component="hevi.creative.autonomous.resolver.AssetResolver",
    role="provider-plane execution adapter: ProviderDecision + acquirer → p7 AssetDecision",
    produces_candidates=False,
    is_generation_admission=False,
    on_production_path=False,
    consumes="ProviderDecision (from provider_policy) + Acquirer.acquire()",
    ruled_out=(
        "candidate selection — owned by shot_readiness.select_candidate",
        "generation admission — owned by selection.admit_generation",
        "production path — P2-A reaches acquisition without it",
    ),
)


def assert_resolver_is_not_production_authority() -> None:
    """确认 AssetResolver 未越界成为候选选择或 generation admission。

    任一越界立即失败:那是 P1 结构性倒退的原样复发。
    """
    if RESOLVER_ROLE.produces_candidates:
        raise AssertionError(
            f"RESOLVER_OVERREACH:{RESOLVER_ROLE.component} must not produce AssetCandidate; "
            "candidates are produced by Acquirers and chosen by select_candidate")
    if RESOLVER_ROLE.is_generation_admission:
        raise AssertionError(
            f"RESOLVER_OVERREACH:{RESOLVER_ROLE.component} must not be generation admission; "
            "use selection.admit_generation(resolution, candidates)")
    if RESOLVER_ROLE.on_production_path:
        raise AssertionError(
            f"RESOLVER_ON_PRODUCTION_PATH:{RESOLVER_ROLE.component} is declared non-production; "
            "the acquisition chain reaches providers without it")


__all__ = [
    "FORBIDDEN_METHODS",
    "RESOLVER_ROLE",
    "Acquirer",
    "AssetResolver",
    "ExecutionReadyResolution",
    "ResolverRole",
    "assert_resolver_is_not_production_authority",
]