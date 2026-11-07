import sys
from unittest.mock import MagicMock

sys.modules["docker"] = MagicMock()
sys.modules["docker.errors"] = MagicMock()

from oskill.metric_baseline_compare import metric_baseline_compare


def test_metric_baseline_compare_no_common():
    result = metric_baseline_compare(current_metrics={"a": 1}, baseline_metrics={"b": 1})
    assert result.verdict == "healthy"
    assert result.overall_health_score == 1.0


def test_metric_baseline_compare_higher_is_better_degradation():
    current = {"success_rate": 0.8}
    baseline = {"success_rate": 0.9}  # -11% decrease
    # 0.8 - 0.9 / 0.9 = -0.111
    result = metric_baseline_compare(
        current_metrics=current,
        baseline_metrics=baseline,
        degradation_threshold=0.1,
        metric_directions={"success_rate": "higher_is_better"},
    )
    assert result.verdict == "degraded"
    assert result.degraded_metrics[0].degraded is True


def test_metric_baseline_compare_zero_baseline():
    # lower_is_better (default)
    result = metric_baseline_compare(current_metrics={"errors": 10}, baseline_metrics={"errors": 0})
    assert result.verdict == "critical"  # 1.0 degradation assumed for 0 -> >0


def test_metric_baseline_compare_healthy():
    current = {"latency": 100, "error_rate": 0.01}
    baseline = {"latency": 110, "error_rate": 0.02}
    result = metric_baseline_compare(current_metrics=current, baseline_metrics=baseline)
    assert result.verdict == "healthy"
    assert len(result.degraded_metrics) == 0


def test_metric_baseline_compare_degraded():
    current = {"latency": 130}  # +30% vs baseline
    baseline = {"latency": 100}
    result = metric_baseline_compare(
        current_metrics=current, baseline_metrics=baseline, degradation_threshold=0.2
    )
    assert result.verdict == "degraded"
    assert len(result.degraded_metrics) == 1


def test_metric_baseline_compare_critical():
    current = {"latency": 160}  # +60% vs baseline
    baseline = {"latency": 100}
    result = metric_baseline_compare(
        current_metrics=current, baseline_metrics=baseline, critical_threshold=0.5
    )
    assert result.verdict == "critical"


def test_metric_baseline_compare_multiple_mixed():
    current = {"latency": 100, "errors": 5}
    baseline = {"latency": 100, "errors": 1}  # errors +400%
    result = metric_baseline_compare(current_metrics=current, baseline_metrics=baseline)
    assert result.verdict == "critical"
    assert len(result.degraded_metrics) == 1
    assert len(result.improved_metrics) == 1
    assert result.overall_health_score == 0.5


def test_metric_baseline_compare_zero_current_higher_is_better():
    current = {"throughput": 0}
    baseline = {"throughput": 100}
    result = metric_baseline_compare(
        current_metrics=current,
        baseline_metrics=baseline,
        metric_directions={"throughput": "higher_is_better"},
    )
    # (0 - 100) / 100 = -1.0
    assert result.verdict == "critical"


def test_metric_baseline_compare_both_zero():
    result = metric_baseline_compare(current_metrics={"x": 0}, baseline_metrics={"x": 0})
    assert result.verdict == "healthy"
    assert result.overall_health_score == 1.0
