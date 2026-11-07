from typing import Literal

from pydantic import BaseModel


class MetricDelta(BaseModel):
    metric_name: str
    baseline_value: float
    current_value: float
    delta_percent: float  # (current - baseline) / baseline × 100
    degraded: bool  # 按 degradation_threshold 判断


class BaselineCompareResult(BaseModel):
    degraded_metrics: list[MetricDelta]
    improved_metrics: list[MetricDelta]
    overall_health_score: float  # 0-1, 1=完全健康
    verdict: Literal["healthy", "degraded", "critical"]


def metric_baseline_compare(
    *,
    current_metrics: dict[str, float],  # {metric_name: value}
    baseline_metrics: dict[str, float],
    degradation_threshold: float = 0.2,  # 20% 恶化算 degraded
    critical_threshold: float = 0.5,  # 50% 恶化算 critical
    metric_directions: dict[str, Literal["higher_is_better", "lower_is_better"]] | None = None,
) -> BaselineCompareResult:
    """对比当前指标与基线, 输出 health verdict."""
    directions = metric_directions or {}

    degraded_metrics: list[MetricDelta] = []
    improved_metrics: list[MetricDelta] = []

    # Only compare common metrics
    common_metrics = set(current_metrics.keys()) & set(baseline_metrics.keys())

    if not common_metrics:
        return BaselineCompareResult(
            degraded_metrics=[], improved_metrics=[], overall_health_score=1.0, verdict="healthy"
        )

    for name in common_metrics:
        current = current_metrics[name]
        baseline = baseline_metrics[name]
        direction = directions.get(name, "lower_is_better")

        delta_percent: float
        if baseline == 0:
            delta_percent = 1.0 if current > 0 else 0.0
        else:
            delta_percent = (current - baseline) / baseline

        is_degraded = False
        if direction == "lower_is_better":
            if delta_percent > degradation_threshold:
                is_degraded = True
        else:  # higher_is_better
            if delta_percent < -degradation_threshold:
                is_degraded = True

        delta_obj = MetricDelta(
            metric_name=name,
            baseline_value=baseline,
            current_value=current,
            delta_percent=delta_percent * 100,
            degraded=is_degraded,
        )

        if is_degraded:
            degraded_metrics.append(delta_obj)
        else:
            improved_metrics.append(delta_obj)

    # Verdict calculation
    max_degradation = 0.0
    for d in degraded_metrics:
        name = d.metric_name
        direction = directions.get(name, "lower_is_better")
        raw_delta = d.delta_percent / 100
        if direction == "lower_is_better":
            max_degradation = max(max_degradation, raw_delta)
        else:
            max_degradation = max(max_degradation, -raw_delta)

    verdict: Literal["healthy", "degraded", "critical"]
    if max_degradation >= critical_threshold:
        verdict = "critical"
    elif max_degradation >= degradation_threshold:
        verdict = "degraded"
    else:
        verdict = "healthy"

    score = 1.0 - (len(degraded_metrics) / len(common_metrics))

    return BaselineCompareResult(
        degraded_metrics=degraded_metrics,
        improved_metrics=improved_metrics,
        overall_health_score=max(0.0, score),
        verdict=verdict,
    )
