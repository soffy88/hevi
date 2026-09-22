"""Auditable production-mode policy and cost-aware resource selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hevi.production.low_cost import LOW_COST_POLICY, ProductionPolicy, policy_for


@dataclass(frozen=True)
class ProductionConstraints:
    max_cost_per_video: float | None = None
    max_gpu_hourly_rate: float | None = None
    max_gpu_runtime_minutes: float | None = None
    allow_hourly_gpu: bool = False


@dataclass(frozen=True)
class CostEstimate:
    low_cost_usd: float
    gpu_usd: float
    currency: str = "USD"


@dataclass(frozen=True)
class ResourceDecision:
    mode: str
    reason: str
    estimate: CostEstimate
    blocked: bool = False


def choose_mode(
    requested_mode: str | None,
    *,
    gpu_required: bool,
    local_gpu_available: bool,
    hourly_gpu_available: bool,
    estimate: CostEstimate,
    constraints: ProductionConstraints | None = None,
) -> ResourceDecision:
    """Select a mode without letting an LLM make an untracked spend decision."""

    limits = constraints or ProductionConstraints()
    requested = (requested_mode or "low_cost").strip().lower()
    if requested not in {"low_cost", "gpu", "auto"}:
        raise ValueError(f"unknown production_mode: {requested}")
    if limits.max_cost_per_video is not None:
        if requested == "low_cost" and estimate.low_cost_usd > limits.max_cost_per_video:
            return ResourceDecision(requested, "LOW_COST_OVER_BUDGET", estimate, blocked=True)
        if requested in {"gpu", "auto"} and estimate.gpu_usd > limits.max_cost_per_video and gpu_required:
            return ResourceDecision(requested, "GPU_OVER_BUDGET", estimate, blocked=True)
    if requested == "low_cost":
        return ResourceDecision("low_cost", "EXPLICIT_LOW_COST", estimate)
    if requested == "gpu":
        if local_gpu_available:
            return ResourceDecision("gpu", "LOCAL_GPU_AVAILABLE", estimate)
        if limits.allow_hourly_gpu and hourly_gpu_available:
            return ResourceDecision("gpu", "HOURLY_GPU_AVAILABLE", estimate)
        return ResourceDecision("gpu", "GPU_RESOURCE_UNAVAILABLE", estimate, blocked=True)
    if not gpu_required:
        return ResourceDecision("low_cost", "GPU_NOT_REQUIRED", estimate)
    if local_gpu_available:
        return ResourceDecision("gpu", "REQUIRED_LOCAL_GPU_AVAILABLE", estimate)
    if limits.allow_hourly_gpu and hourly_gpu_available:
        return ResourceDecision("gpu", "REQUIRED_HOURLY_GPU_AVAILABLE", estimate)
    return ResourceDecision("auto", "BLOCKED_RESOURCE", estimate, blocked=True)


def decision_to_dict(decision: ResourceDecision) -> dict[str, Any]:
    return {
        "mode": decision.mode,
        "reason": decision.reason,
        "blocked": decision.blocked,
        "low_cost_estimate": decision.estimate.low_cost_usd,
        "gpu_estimate": decision.estimate.gpu_usd,
        "currency": decision.estimate.currency,
    }


__all__ = [
    "LOW_COST_POLICY", "CostEstimate", "ProductionConstraints", "ProductionPolicy",
    "ResourceDecision", "choose_mode", "decision_to_dict", "policy_for",
]
