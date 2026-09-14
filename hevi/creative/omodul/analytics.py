"""Deterministic creative production analytics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from hevi.obase.creative import NarrativeAudit, ProductionRun


@dataclass(frozen=True)
class CreativeAnalytics:
    word_count: int
    artifact_count: int
    audit_pass_rate: float
    issue_distribution: dict[str, int]
    revision_count: int
    run_failure_rate: float
    run_recovery_rate: float


def calculate_analytics(
    *,
    texts: Iterable[str],
    audits: Iterable[NarrativeAudit],
    runs: Iterable[ProductionRun],
    revision_count: int,
) -> CreativeAnalytics:
    if revision_count < 0:
        raise ValueError("ANALYTICS_INPUT_INVALID")
    audit_list = tuple(audits)
    run_list = tuple(runs)
    issues = Counter(finding.dimension for audit in audit_list for finding in audit.findings)
    completed = sum(audit.status == "PASS" for audit in audit_list)
    failed = sum(run.status == "FAILED" for run in run_list)
    recovered = sum(
        any(item.status == "SUCCEEDED" for item in run.stage_results) and run.revision > 1
        for run in run_list
    )
    return CreativeAnalytics(
        word_count=sum(len(text.split()) for text in texts),
        artifact_count=sum(len(run.artifact_manifest.artifact_ids) for run in run_list),
        audit_pass_rate=completed / len(audit_list) if audit_list else 0.0,
        issue_distribution=dict(issues),
        revision_count=revision_count,
        run_failure_rate=failed / len(run_list) if run_list else 0.0,
        run_recovery_rate=recovered / len(run_list) if run_list else 0.0,
    )


__all__ = ["CreativeAnalytics", "calculate_analytics"]
