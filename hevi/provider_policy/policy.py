"""Provider Policy Engine v1.

The existing cost router selects a provider, but callers could not retain why
alternatives were rejected.  This layer returns the full decision record so a
task, UI, or repair loop can explain capability, health, quality, and budget
choices without re-running provider discovery.
"""

from __future__ import annotations

import random
from typing import Any

from pydantic import BaseModel, Field

from hevi.cost.estimator import estimate_cost
from hevi.cost.selector import PROVIDER_QUALITY
from hevi.resilience.live_state import provider_routable
from hevi.video.capability_guard import PROVIDER_LIMITS


class ProviderPolicy(BaseModel):
    mode: str = "t2v"
    duration_archetype: str = "1-5min"
    audio_provider: str = "vibevoice"
    quality_floor: int = 9
    required_capabilities: set[str] = Field(default_factory=set)
    candidates: list[str] | None = None
    max_estimated_cost_usd: float | None = None
    min_health: float = Field(default=0.5, ge=0.0, le=1.0)
    min_balance_usd: float = Field(default=0.0, ge=0.0)
    min_quota_remaining: int = Field(default=1, ge=0)
    quality_weight: float = Field(default=0.35, ge=0.0)
    latency_weight: float = Field(default=0.15, ge=0.0)
    cost_weight: float = Field(default=0.20, ge=0.0)
    health_weight: float = Field(default=0.20, ge=0.0)
    capacity_weight: float = Field(default=0.10, ge=0.0)
    exploration_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    policy_version: int = 1


class ProviderRejection(BaseModel):
    provider_id: str
    reasons: list[str] = Field(default_factory=list)


class ProviderDecision(BaseModel):
    selected_provider: str | None = None
    estimated_cost_usd: float | None = None
    # Ordered eligible candidates are persisted with the task so fallback is
    # derived from the same policy snapshot instead of a source-code chain.
    eligible: list[str] = Field(default_factory=list)
    considered: list[str] = Field(default_factory=list)
    rejected: list[ProviderRejection] = Field(default_factory=list)
    candidate_scores: dict[str, dict[str, float]] = Field(default_factory=dict)
    selected_reason: str | None = None
    explored: bool = False
    policy_version: int = 1


class ProviderPolicyError(ValueError):
    def __init__(self, decision: ProviderDecision) -> None:
        self.decision = decision
        super().__init__(
            "no provider satisfies policy: "
            + "; ".join(
                f"{item.provider_id} ({', '.join(item.reasons)})"
                for item in decision.rejected
            )
        )


async def evaluate_provider_policy(
    policy: ProviderPolicy, *, state_repository: Any | None = None
) -> ProviderDecision:
    candidates = policy.candidates or list(PROVIDER_LIMITS)
    decision = ProviderDecision(
        considered=list(candidates),
        policy_version=policy.policy_version,
    )
    eligible: list[tuple[str, float]] = []
    for provider_id in candidates:
        limits = PROVIDER_LIMITS.get(provider_id)
        reasons: list[str] = []
        if limits is None:
            reasons.append("unknown_provider")
        else:
            runtime_state: dict[str, Any] = {}
            if policy.mode not in limits.modes:
                reasons.append(f"mode_unsupported:{policy.mode}")
            reasons.extend(
                f"capability_missing:{capability}"
                for capability in sorted(policy.required_capabilities)
                if not bool(getattr(limits, capability, False))
            )
            if not provider_routable(provider_id):
                reasons.append("not_routable")
            if state_repository is not None:
                state = await state_repository.get(provider_id)
                if state is not None:
                    runtime_state = dict(state)
                    health = state.get("health")
                    if health is not None and float(health) < policy.min_health:
                        reasons.append(f"health_below_floor:{policy.min_health}")
                    balance = state.get("balance_usd")
                    if balance is not None and float(balance) < policy.min_balance_usd:
                        reasons.append(f"balance_below_floor:{policy.min_balance_usd}")
                    quota = state.get("quota_remaining")
                    if quota is not None and int(quota) < policy.min_quota_remaining:
                        reasons.append(f"quota_below_floor:{policy.min_quota_remaining}")
                    quality = state.get("quality_score")
                    if quality is not None and float(quality) * 10 < policy.quality_floor:
                        reasons.append(f"quality_history_below_floor:{policy.quality_floor}")
            historical_quality = runtime_state.get("quality_score")
            if historical_quality is not None:
                if float(historical_quality) * 10 < policy.quality_floor:
                    reasons.append(f"quality_history_below_floor:{policy.quality_floor}")
            elif PROVIDER_QUALITY.get(provider_id, 0) < policy.quality_floor:
                reasons.append(f"quality_below_floor:{policy.quality_floor}")
        if reasons:
            decision.rejected.append(ProviderRejection(provider_id=provider_id, reasons=reasons))
            continue
        estimate = await estimate_cost(
            duration_archetype=policy.duration_archetype,
            video_provider=provider_id,
            audio_provider=policy.audio_provider,
        )
        if (
            policy.max_estimated_cost_usd is not None
            and estimate.total_usd > policy.max_estimated_cost_usd
        ):
            decision.rejected.append(
                ProviderRejection(
                    provider_id=provider_id,
                    reasons=[f"budget_exceeded:{policy.max_estimated_cost_usd}"],
                )
            )
            continue
        quality = float(
            runtime_state["quality_score"]
            if runtime_state.get("quality_score") is not None
            else PROVIDER_QUALITY.get(provider_id, 0) / 10
        )
        health = float(runtime_state["health"] if runtime_state.get("health") is not None else 1.0)
        p95_ms = float(
            runtime_state["p95_latency_ms"]
            if runtime_state.get("p95_latency_ms") is not None
            else 1000.0
        )
        quota = float(
            runtime_state["quota_remaining"]
            if runtime_state.get("quota_remaining") is not None
            else 1
        )
        cost_score = 1.0 / (1.0 + max(0.0, estimate.total_usd))
        latency_score = 1.0 / (1.0 + max(0.0, p95_ms) / 1000.0)
        capacity_score = min(1.0, quota / max(1.0, float(policy.min_quota_remaining)))
        score = (
            policy.quality_weight * max(0.0, min(1.0, quality))
            + policy.latency_weight * max(0.0, min(1.0, latency_score))
            + policy.cost_weight * max(0.0, min(1.0, cost_score))
            + policy.health_weight * max(0.0, min(1.0, health))
            + policy.capacity_weight * max(0.0, min(1.0, capacity_score))
        )
        decision.candidate_scores[provider_id] = {
            "score": score,
            "quality": quality,
            "health": health,
            "latency": latency_score,
            "cost": cost_score,
            "capacity": capacity_score,
            "estimated_cost_usd": estimate.total_usd,
        }
        eligible.append((provider_id, score))
    if eligible:
        decision.eligible = [
            provider_id
            for provider_id, _ in sorted(eligible, key=lambda item: (-item[1], item[0]))
        ]
        selected, _ = max(eligible, key=lambda item: (item[1], item[0]))
        explorers = decision.eligible[1:4]
        if (
            policy.exploration_rate > 0
            and explorers
            and random.random() < policy.exploration_rate
        ):
            selected = explorers[0]
            decision.explored = True
        decision.selected_provider = selected
        decision.estimated_cost_usd = decision.candidate_scores[selected]["estimated_cost_usd"]
        reason_prefix = (
            "exploration sample; "
            if decision.explored
            else f"highest weighted score {decision.candidate_scores[selected]['score']:.4f}; "
        )
        decision.selected_reason = (
            f"{reason_prefix}alternatives={','.join(decision.eligible[1:]) or 'none'}"
        )
    return decision


def require_provider(decision: ProviderDecision) -> str:
    if decision.selected_provider is None:
        raise ProviderPolicyError(decision)
    return decision.selected_provider


__all__ = [
    "ProviderDecision",
    "ProviderPolicy",
    "ProviderPolicyError",
    "ProviderRejection",
    "evaluate_provider_policy",
    "require_provider",
]
