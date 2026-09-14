"""Deterministic creative production analytics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from hevi.obase.creative import NarrativeAudit, ProductionRun


@dataclass(frozen=True)
class UsageRecord:
    """One model call's token, cost, and latency telemetry."""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class CreativeAnalytics:
    word_count: int
    artifact_count: int
    audit_pass_rate: float
    issue_distribution: dict[str, int]
    revision_count: int
    run_failure_rate: float
    run_recovery_rate: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    token_usage: dict[str, int] = field(default_factory=dict)
    model_usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    latency_ms_total: float = 0.0
    latency_ms_avg: float = 0.0


def calculate_analytics(
    *,
    texts: Iterable[str],
    audits: Iterable[NarrativeAudit],
    runs: Iterable[ProductionRun],
    revision_count: int,
    usage: Iterable[UsageRecord] = (),
) -> CreativeAnalytics:
    if revision_count < 0:
        raise ValueError("ANALYTICS_INPUT_INVALID")
    audit_list = tuple(audits)
    run_list = tuple(runs)
    usage_list = tuple(usage)
    if any(
        item.prompt_tokens < 0
        or item.completion_tokens < 0
        or item.cost_usd < 0
        or item.latency_ms < 0
        for item in usage_list
    ):
        raise ValueError("ANALYTICS_INPUT_INVALID")
    issues = Counter(finding.dimension for audit in audit_list for finding in audit.findings)
    completed = sum(audit.status == "PASS" for audit in audit_list)
    failed = sum(run.status == "FAILED" for run in run_list)
    recovered = sum(
        any(item.status == "SUCCEEDED" for item in run.stage_results) and run.revision > 1
        for run in run_list
    )
    token_usage: dict[str, int] = {}
    model_usage: dict[str, int] = {}
    for item in usage_list:
        token_usage[item.model] = token_usage.get(item.model, 0) + item.total_tokens
        model_usage[item.model] = model_usage.get(item.model, 0) + 1
    total_latency = sum(item.latency_ms for item in usage_list)
    return CreativeAnalytics(
        word_count=sum(len(text.split()) for text in texts),
        artifact_count=sum(len(run.artifact_manifest.artifact_ids) for run in run_list),
        audit_pass_rate=completed / len(audit_list) if audit_list else 0.0,
        issue_distribution=dict(issues),
        revision_count=revision_count,
        run_failure_rate=failed / len(run_list) if run_list else 0.0,
        run_recovery_rate=recovered / len(run_list) if run_list else 0.0,
        prompt_tokens=sum(item.prompt_tokens for item in usage_list),
        completion_tokens=sum(item.completion_tokens for item in usage_list),
        token_usage=token_usage,
        model_usage=model_usage,
        cost_usd=sum(item.cost_usd for item in usage_list),
        latency_ms_total=total_latency,
        latency_ms_avg=total_latency / len(usage_list) if usage_list else 0.0,
    )


__all__ = ["CreativeAnalytics", "UsageRecord", "calculate_analytics"]
