"""compute_capacity_forecast — 容量预测与扩容建议.

Pure algorithm oskill — uses linear regression on time-series samples.
Optional LLM callable for narrative summary.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel


class ForecastPoint(BaseModel):
    t_offset: int
    predicted_value: float


class CapacityForecastResult(BaseModel):
    metric_name: str
    current_value: float
    predicted_values: list[ForecastPoint]
    trend_slope: float
    will_breach_threshold: bool
    breach_at_offset: int | None
    recommendation: str
    narrative: str | None


def _linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Returns (slope, intercept) for simple least-squares regression."""
    n = len(xs)
    if n < 2:
        return 0.0, ys[-1] if ys else 0.0
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_xx = sum(x * x for x in xs)
    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return 0.0, sum_y / n
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept


def compute_capacity_forecast(
    *,
    metric_name: str,
    samples: list[float],
    threshold: float,
    forecast_steps: int = 5,
    llm_fn: Callable[..., Any] | None = None,
) -> CapacityForecastResult:
    """容量趋势预测 — 线性外推 + 阈值预警 + 可选 LLM 摘要.

    Composition note: pure linear regression on historical samples.
    LLM summary is optional — used when llm_fn is provided (e.g., from
    synthesize_action_plan context). Without llm_fn, recommendation is
    generated from rule-based logic.

    Args:
        metric_name: 指标名称 (e.g. "disk_used_percent")
        samples: 历史观测值列表 (时序, 最新在末尾)
        threshold: 触发告警的阈值 (e.g. 90.0 for disk percent)
        forecast_steps: 预测步数 (与采样间隔一致)
        llm_fn: 可选 LLM callable (prompt: str) → str, 用于生成自然语言摘要

    Returns:
        CapacityForecastResult
    """
    n = len(samples)
    if n == 0:
        return CapacityForecastResult(
            metric_name=metric_name,
            current_value=0.0,
            predicted_values=[],
            trend_slope=0.0,
            will_breach_threshold=False,
            breach_at_offset=None,
            recommendation="No data available for forecast",
            narrative=None,
        )

    xs = list(range(n))
    slope, intercept = _linear_regression([float(x) for x in xs], [float(y) for y in samples])
    current = float(samples[-1])

    predictions: list[ForecastPoint] = []
    breach_at: int | None = None

    for step in range(1, forecast_steps + 1):
        t = n - 1 + step
        pred = slope * t + intercept
        predictions.append(ForecastPoint(t_offset=step, predicted_value=round(pred, 4)))
        if breach_at is None and pred >= threshold:
            breach_at = step

    will_breach = breach_at is not None

    # Rule-based recommendation
    if slope > 0 and will_breach:
        recommendation = (
            f"{metric_name} trending up (slope={slope:.3f}/step), "
            f"will breach {threshold} in {breach_at} steps — scale now"
        )
    elif slope > 0:
        recommendation = (
            f"{metric_name} trending up (slope={slope:.3f}/step) "
            f"but within threshold for next {forecast_steps} steps — monitor"
        )
    elif slope < 0:
        recommendation = f"{metric_name} trending down (slope={slope:.3f}/step) — no action needed"
    else:
        recommendation = f"{metric_name} stable — no action needed"

    narrative: str | None = None
    if llm_fn is not None:
        pred_summary = ", ".join(f"t+{p.t_offset}: {p.predicted_value:.1f}" for p in predictions)
        prompt = (
            f"Capacity forecast for {metric_name}:\n"
            f"Current value: {current}\nThreshold: {threshold}\n"
            f"Trend slope: {slope:.4f} per step\n"
            f"Predicted values: {pred_summary}\n"
            f"Will breach threshold: {will_breach}"
            + (f" at t+{breach_at}" if breach_at else "")
            + "\n\nProvide a brief (2–3 sentence) capacity planning recommendation."
        )
        try:
            narrative = str(llm_fn(prompt))
        except Exception:
            narrative = None

    return CapacityForecastResult(
        metric_name=metric_name,
        current_value=round(current, 4),
        predicted_values=predictions,
        trend_slope=round(slope, 6),
        will_breach_threshold=will_breach,
        breach_at_offset=breach_at,
        recommendation=recommendation,
        narrative=narrative,
    )
