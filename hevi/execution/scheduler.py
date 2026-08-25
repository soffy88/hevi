"""Explainable multi-objective scheduling for queued production tasks.

The scheduler is deliberately pure.  A worker supplies a live resource
snapshot, while PostgreSQL remains the source of queued tasks and the atomic
claim.  This keeps policy decisions deterministic and makes them testable
without GPU, Redis, or provider calls.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SchedulingWeights(BaseModel):
    priority: float = Field(default=0.30, ge=0)
    deadline: float = Field(default=0.20, ge=0)
    resource_fit: float = Field(default=0.15, ge=0)
    warm_model: float = Field(default=0.10, ge=0)
    provider_quota: float = Field(default=0.10, ge=0)
    expected_cost: float = Field(default=0.10, ge=0)
    tenant_fairness: float = Field(default=0.05, ge=0)


class ResourceSnapshot(BaseModel):
    """Capabilities and live capacity advertised by one worker pool."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    worker_id: str = "scheduler"
    resource_class: str = "any"
    available_vram_mb: int | None = Field(default=None, ge=0)
    active_slots: int = Field(default=0, ge=0)
    capacity_slots: int = Field(default=1, ge=1)
    warm_providers: set[str] = Field(default_factory=set)
    provider_tokens: dict[str, int] = Field(default_factory=dict)
    tenant_running: dict[str, int] = Field(default_factory=dict)


class SchedulingRequest(BaseModel):
    """Scheduling-relevant projection of a persisted task."""

    task_id: uuid.UUID
    tenant_id: str = "anonymous"
    priority: int = 0
    deadline_at: datetime | None = None
    resource_class: str = "any"
    required_vram_mb: int = Field(default=0, ge=0)
    provider_id: str | None = None
    expected_cost_usd: float = Field(default=0.0, ge=0)
    budget_remaining_usd: float | None = Field(default=None, ge=0)
    tenant_weight: float = Field(default=1.0, gt=0)
    queued_at: datetime | None = None

    @classmethod
    def from_task(cls, task: Mapping[str, Any]) -> SchedulingRequest:
        config = task.get("config_json") or {}
        raw_id = task.get("id")
        if raw_id is None:
            raise ValueError("queued task has no id")
        budget_remaining = config.get("budget_remaining_usd")
        return cls(
            task_id=uuid.UUID(str(raw_id)),
            tenant_id=str(task.get("user_id") or "anonymous"),
            priority=int(task.get("priority") or config.get("priority") or 0),
            deadline_at=task.get("deadline_at") or config.get("deadline_at"),
            resource_class=str(task.get("resource_class") or "any"),
            required_vram_mb=int(
                task.get("required_vram_mb") or config.get("required_vram_mb") or 0
            ),
            provider_id=str(task.get("video_provider") or "") or None,
            expected_cost_usd=float(
                task.get("expected_cost_usd")
                or config.get("estimated_usd")
                or 0.0
            ),
            budget_remaining_usd=(
                float(budget_remaining) if budget_remaining is not None else None
            ),
            tenant_weight=float(task.get("tenant_weight") or 1.0),
            queued_at=task.get("queued_at"),
        )


class SchedulingDecision(BaseModel):
    task_id: uuid.UUID
    feasible: bool
    score: float = 0.0
    components: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    policy_version: int = 1
    worker_id: str = "scheduler"

    def explain(self) -> str:
        status = "eligible" if self.feasible else "rejected"
        parts = ", ".join(f"{key}={value:.3f}" for key, value in self.components.items())
        reason = "; ".join(self.reasons) or "ok"
        return f"{self.task_id}: {status}; score={self.score:.3f}; {parts}; {reason}"


def _deadline_urgency(deadline_at: datetime | None, now: datetime) -> float:
    if deadline_at is None:
        return 0.0
    if deadline_at.tzinfo is None:
        deadline_at = deadline_at.replace(tzinfo=UTC)
    seconds_left = (deadline_at - now).total_seconds()
    if seconds_left <= 0:
        return 1.0
    return 1.0 / (1.0 + seconds_left / 3600.0)


class Scheduler:
    """Calculate and rank scheduling decisions for one worker snapshot."""

    def __init__(
        self,
        *,
        weights: SchedulingWeights | None = None,
        policy_version: int = 1,
        clock: Any | None = None,
    ) -> None:
        self.weights = weights or SchedulingWeights()
        self.policy_version = policy_version
        self._clock = clock or (lambda: datetime.now(UTC))

    def decide(
        self,
        request: SchedulingRequest,
        resources: ResourceSnapshot,
    ) -> SchedulingDecision:
        reasons: list[str] = []
        resource_fit = 1.0
        if resources.resource_class != "any" and request.resource_class not in {
            "any",
            resources.resource_class,
        }:
            resource_fit = 0.0
            reasons.append(f"resource_class_mismatch:{request.resource_class}")
        if (
            request.required_vram_mb > 0
            and resources.available_vram_mb is not None
            and request.required_vram_mb > resources.available_vram_mb
        ):
            resource_fit = 0.0
            reasons.append("insufficient_vram")
        if resources.active_slots >= resources.capacity_slots:
            reasons.append("worker_capacity_full")
        provider_tokens = resources.provider_tokens.get(request.provider_id or "")
        if provider_tokens is not None and provider_tokens <= 0:
            reasons.append("provider_concurrency_exhausted")
        if (
            request.budget_remaining_usd is not None
            and request.expected_cost_usd > request.budget_remaining_usd
        ):
            reasons.append("budget_remaining_below_expected_cost")

        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        deadline = _deadline_urgency(request.deadline_at, now)
        priority = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, request.priority)) / 10.0))
        warm = 1.0 if request.provider_id in resources.warm_providers else 0.25
        quota = (
            1.0
            if provider_tokens is None
            else min(1.0, provider_tokens / max(1, resources.capacity_slots))
        )
        if request.budget_remaining_usd is None:
            cost = 0.5
        elif request.expected_cost_usd <= 0:
            cost = 1.0
        else:
            cost = 1.0 / (1.0 + request.expected_cost_usd / max(request.budget_remaining_usd, 0.01))
        running = resources.tenant_running.get(request.tenant_id, 0)
        fairness = 1.0 / (1.0 + running / request.tenant_weight)
        components = {
            "priority": priority,
            "deadline": deadline,
            "resource_fit": resource_fit,
            "warm_model": warm,
            "provider_quota": quota,
            "expected_cost": cost,
            "tenant_fairness": fairness,
        }
        score = sum(getattr(self.weights, name) * value for name, value in components.items())
        return SchedulingDecision(
            task_id=request.task_id,
            feasible=not reasons,
            score=score if not reasons else 0.0,
            components=components,
            reasons=reasons,
            policy_version=self.policy_version,
            worker_id=resources.worker_id,
        )

    def rank(
        self,
        requests: list[SchedulingRequest],
        resources: ResourceSnapshot,
    ) -> list[SchedulingDecision]:
        decisions = [self.decide(request, resources) for request in requests]
        return sorted(
            decisions,
            key=lambda decision: (
                not decision.feasible,
                -decision.score,
                str(decision.task_id),
            ),
        )

    def choose(
        self,
        requests: list[SchedulingRequest],
        resources: ResourceSnapshot,
    ) -> SchedulingDecision | None:
        for decision in self.rank(requests, resources):
            if decision.feasible:
                return decision
        return None


__all__ = [
    "ResourceSnapshot",
    "Scheduler",
    "SchedulingDecision",
    "SchedulingRequest",
    "SchedulingWeights",
]
