"""compute_severity_score — 告警事件严重度评分 (0–100)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

SeverityLabel = Literal["critical", "high", "medium", "low", "info"]

_SEVERITY_THRESHOLDS = [
    (80, "critical"),
    (60, "high"),
    (40, "medium"),
    (20, "low"),
    (0, "info"),
]


class SeverityResult(BaseModel):
    score: float
    label: SeverityLabel
    contributing_factors: list[dict[str, Any]]


def compute_severity_score(
    *,
    signal: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> SeverityResult:
    """信号严重度评分 — 基于多维特征加权聚合得分 (0–100).

    Composition note: pure algorithm. Feed output into synthesize_action_plan
    or use as filter in TriageEngine.

    Args:
        signal: 信号 dict, 可含:
                - "error_rate" (float, 0–1): 错误率
                - "latency_p99_ms" (float): P99 延迟
                - "affected_users" (int): 受影响用户数
                - "resource_used_percent" (float, 0–100): 资源使用率
                - "is_prod" (bool): 是否生产环境
                - "pattern_confidence" (float, 0–1): 来自 diagnose_pattern_match 的置信度
        weights: 各维度权重覆盖 (默认均等 0.2)

    Returns:
        SeverityResult (score 0–100, label critical/high/medium/low/info)
    """
    default_weights = {
        "error_rate": 0.25,
        "latency_p99_ms": 0.15,
        "affected_users": 0.2,
        "resource_used_percent": 0.2,
        "pattern_confidence": 0.2,
    }
    w = {**default_weights, **(weights or {})}

    factors: list[dict[str, Any]] = []
    total_score = 0.0

    # error_rate: 0–1 → score 0–100
    err = float(signal.get("error_rate", 0.0))
    if err > 0:
        s = min(err * 100, 100) * w["error_rate"]
        factors.append({"factor": "error_rate", "value": err, "contribution": round(s, 2)})
        total_score += s

    # latency_p99_ms: >1000ms is severe
    lat = float(signal.get("latency_p99_ms", 0.0))
    if lat > 0:
        normalized = min(lat / 5000.0, 1.0)
        s = normalized * 100 * w["latency_p99_ms"]
        factors.append({"factor": "latency_p99_ms", "value": lat, "contribution": round(s, 2)})
        total_score += s

    # affected_users: log scale, 10000 users = full weight
    users = int(signal.get("affected_users", 0))
    if users > 0:
        import math

        normalized = min(math.log10(users + 1) / 4.0, 1.0)
        s = normalized * 100 * w["affected_users"]
        factors.append({"factor": "affected_users", "value": users, "contribution": round(s, 2)})
        total_score += s

    # resource_used_percent
    res = float(signal.get("resource_used_percent", 0.0))
    if res > 0:
        s = (res / 100.0) * 100 * w["resource_used_percent"]
        factors.append(
            {"factor": "resource_used_percent", "value": res, "contribution": round(s, 2)}
        )
        total_score += s

    # pattern_confidence
    pc = float(signal.get("pattern_confidence", 0.0))
    if pc > 0:
        s = pc * 100 * w["pattern_confidence"]
        factors.append({"factor": "pattern_confidence", "value": pc, "contribution": round(s, 2)})
        total_score += s

    # prod multiplier
    if signal.get("is_prod"):
        total_score = min(total_score * 1.3, 100)

    score = round(min(max(total_score, 0.0), 100.0), 2)
    label: SeverityLabel = "info"
    for threshold, lbl in _SEVERITY_THRESHOLDS:
        if score >= threshold:
            label = lbl  # type: ignore[assignment]
            break

    return SeverityResult(score=score, label=label, contributing_factors=factors)
