"""B3 tests: diagnose_pattern_match, compute_severity_score, classify_signal,
circuit_breaker_check, compute_capacity_forecast (pure algorithm elements).
"""

from oskill.circuit_breaker_check import circuit_breaker_check
from oskill.classify_signal import SignalClassification, classify_signal
from oskill.compute_capacity_forecast import CapacityForecastResult, compute_capacity_forecast
from oskill.compute_severity_score import compute_severity_score
from oskill.diagnose_pattern_match import PatternMatchResult, diagnose_pattern_match

# ─── diagnose_pattern_match ──────────────────────────────────────────────────


class TestDiagnosePatternMatch:
    def test_memory_pressure_detected(self):
        signal = {"message": "OOM killer running", "ram_used_percent": 95}
        result = diagnose_pattern_match(signal=signal)
        assert isinstance(result, PatternMatchResult)
        assert result.matched is True
        assert result.pattern_name == "memory_pressure"
        assert result.confidence >= 0.5

    def test_cpu_saturation_detected(self):
        signal = {"message": "cpu throttling detected", "cpu_used_percent": 98}
        result = diagnose_pattern_match(signal=signal)
        assert result.matched is True
        assert result.pattern_name == "cpu_saturation"

    def test_queue_backlog_detected(self):
        signal = {"message": "queue depth increasing", "queue_depth": 10000}
        result = diagnose_pattern_match(signal=signal)
        assert result.matched is True
        assert result.pattern_name == "queue_backlog"

    def test_no_match_below_min_confidence(self):
        signal = {"message": "hello world"}
        result = diagnose_pattern_match(signal=signal, min_confidence=0.9)
        assert result.matched is False
        assert result.pattern_name is None

    def test_empty_signal_no_match(self):
        result = diagnose_pattern_match(signal={})
        assert result.matched is False

    def test_custom_pattern_overrides_builtin(self):
        custom = [
            {
                "name": "custom_db_lag",
                "keywords": ["replication", "lag"],
                "thresholds": {},
                "weight": 1.0,
            }
        ]
        signal = {"message": "replication lag detected"}
        result = diagnose_pattern_match(signal=signal, patterns=custom)
        assert result.matched is True
        assert result.pattern_name == "custom_db_lag"

    def test_connection_exhaustion_detected(self):
        signal = {"message": "too many connections", "active_connections": 500}
        result = diagnose_pattern_match(signal=signal)
        assert result.matched is True
        assert result.pattern_name == "connection_exhaustion"

    def test_disk_pressure_detected(self):
        signal = {"message": "disk full warning", "disk_used_percent": 96}
        result = diagnose_pattern_match(signal=signal)
        assert result.matched is True
        assert result.pattern_name == "disk_pressure"

    def test_result_confidence_in_range(self):
        signal = {"message": "memory leak detected", "ram_used_percent": 80}
        result = diagnose_pattern_match(signal=signal)
        assert 0.0 <= result.confidence <= 1.0


# ─── compute_severity_score ──────────────────────────────────────────────────


class TestComputeSeverityScore:
    def test_critical_score_high_error_rate_prod(self):
        # All five factors at max + is_prod to guarantee score >= 80
        signal = {
            "error_rate": 1.0,
            "latency_p99_ms": 5000,
            "affected_users": 10000,
            "resource_used_percent": 100,
            "pattern_confidence": 1.0,
            "is_prod": True,
        }
        result = compute_severity_score(signal=signal)
        assert result.label == "critical"
        assert result.score >= 80

    def test_info_label_empty_signal(self):
        result = compute_severity_score(signal={})
        assert result.label == "info"
        assert result.score == 0.0

    def test_prod_multiplier_increases_score(self):
        base = compute_severity_score(signal={"error_rate": 0.4})
        prod = compute_severity_score(signal={"error_rate": 0.4, "is_prod": True})
        assert prod.score > base.score

    def test_score_capped_at_100(self):
        signal = {
            "error_rate": 1.0,
            "latency_p99_ms": 99999,
            "affected_users": 1000000,
            "resource_used_percent": 100,
            "pattern_confidence": 1.0,
            "is_prod": True,
        }
        result = compute_severity_score(signal=signal)
        assert result.score <= 100.0

    def test_contributing_factors_listed(self):
        signal = {"error_rate": 0.5, "latency_p99_ms": 2000}
        result = compute_severity_score(signal=signal)
        factor_names = [f["factor"] for f in result.contributing_factors]
        assert "error_rate" in factor_names
        assert "latency_p99_ms" in factor_names

    def test_custom_weights_applied(self):
        signal = {"error_rate": 0.5, "latency_p99_ms": 1000}
        default = compute_severity_score(signal=signal)
        custom = compute_severity_score(
            signal=signal, weights={"error_rate": 0.9, "latency_p99_ms": 0.1}
        )
        assert default.score != custom.score

    def test_low_label_for_minor_signal(self):
        signal = {"error_rate": 0.05}
        result = compute_severity_score(signal=signal)
        assert result.label in ("low", "info")

    def test_score_nonnegative(self):
        result = compute_severity_score(signal={"error_rate": -0.5})
        assert result.score >= 0.0


# ─── classify_signal ─────────────────────────────────────────────────────────


class TestClassifySignal:
    def test_infrastructure_cpu(self):
        signal = {"message": "cpu usage spiked", "cpu_used_percent": 95}
        result = classify_signal(signal=signal)
        assert isinstance(result, SignalClassification)
        assert result.signal_class == "infrastructure"

    def test_application_error(self):
        signal = {"message": "5xx errors increasing", "error_rate": 0.3}
        result = classify_signal(signal=signal)
        assert result.signal_class == "application"

    def test_security_auth_failure(self):
        signal = {"message": "unauthorized access attempt brute force"}
        result = classify_signal(signal=signal)
        assert result.signal_class == "security"

    def test_business_payment_failure(self):
        signal = {"message": "payment checkout order failure"}
        result = classify_signal(signal=signal)
        assert result.signal_class == "business"

    def test_unknown_below_threshold(self):
        signal = {"message": "server started"}
        result = classify_signal(signal=signal, min_confidence=0.99)
        assert result.signal_class == "unknown"

    def test_confidence_in_range(self):
        signal = {"message": "memory oom kill", "ram_used_percent": 98}
        result = classify_signal(signal=signal)
        assert 0.0 <= result.confidence <= 1.0

    def test_reasoning_present(self):
        signal = {"message": "disk full", "disk_used_percent": 98}
        result = classify_signal(signal=signal)
        assert isinstance(result.reasoning, str)
        assert len(result.reasoning) > 0

    def test_empty_signal_unknown(self):
        result = classify_signal(signal={})
        assert result.signal_class == "unknown"


# ─── circuit_breaker_check ───────────────────────────────────────────────────


class TestCircuitBreakerCheck:
    def _samples(self, n_fail, n_ok, latency_ms=100):
        return [{"success": False, "latency_ms": latency_ms}] * n_fail + [
            {"success": True, "latency_ms": latency_ms}
        ] * n_ok

    def test_trips_on_high_error_rate(self):
        samples = self._samples(8, 2)
        result = circuit_breaker_check(samples=samples, current_state="closed")
        assert result.state == "open"
        assert result.should_trip is True

    def test_stays_closed_on_low_error_rate(self):
        samples = self._samples(1, 9)
        result = circuit_breaker_check(samples=samples, current_state="closed")
        assert result.state == "closed"
        assert result.should_trip is False

    def test_open_to_half_open_on_recovery(self):
        samples = self._samples(0, 10)  # 0% error rate
        result = circuit_breaker_check(samples=samples, current_state="open")
        assert result.state == "half_open"
        assert result.recovery_possible is True

    def test_half_open_closes_on_clean_probe(self):
        samples = self._samples(0, 10)
        result = circuit_breaker_check(samples=samples, current_state="half_open")
        assert result.state == "closed"

    def test_half_open_retraps_on_errors(self):
        samples = self._samples(8, 2)
        result = circuit_breaker_check(samples=samples, current_state="half_open")
        assert result.state == "open"
        assert result.should_trip is True

    def test_no_state_change_insufficient_samples(self):
        samples = self._samples(2, 0)  # only 2 samples
        result = circuit_breaker_check(
            samples=samples, current_state="closed", thresholds={"min_samples": 5}
        )
        assert result.state == "closed"

    def test_empty_samples_returns_current_state(self):
        result = circuit_breaker_check(samples=[], current_state="open")
        assert result.state == "open"
        assert result.window_samples == 0

    def test_latency_trips_circuit(self):
        samples = [{"success": True, "latency_ms": 9000}] * 10
        result = circuit_breaker_check(
            samples=samples,
            current_state="closed",
            thresholds={"latency_p99_open_ms": 5000, "min_samples": 5},
        )
        assert result.state == "open"

    def test_error_rate_computed_correctly(self):
        samples = self._samples(3, 7)
        result = circuit_breaker_check(samples=samples, current_state="closed")
        assert abs(result.error_rate - 0.3) < 0.01

    def test_reasons_nonempty(self):
        samples = self._samples(5, 5)
        result = circuit_breaker_check(samples=samples, current_state="closed")
        assert len(result.reasons) > 0


# ─── compute_capacity_forecast ───────────────────────────────────────────────


class TestComputeCapacityForecast:
    def test_breach_detected_linear_growth(self):
        samples = [50, 60, 70, 80, 85]
        result = compute_capacity_forecast(
            metric_name="disk_used_percent",
            samples=samples,
            threshold=90.0,
            forecast_steps=5,
        )
        assert isinstance(result, CapacityForecastResult)
        assert result.will_breach_threshold is True
        assert result.breach_at_offset is not None

    def test_no_breach_flat_trend(self):
        samples = [50.0] * 10
        result = compute_capacity_forecast(
            metric_name="cpu_used_percent",
            samples=samples,
            threshold=90.0,
            forecast_steps=5,
        )
        assert result.will_breach_threshold is False

    def test_forecast_steps_count(self):
        samples = [10, 20, 30, 40, 50]
        result = compute_capacity_forecast(
            metric_name="test", samples=samples, threshold=100, forecast_steps=7
        )
        assert len(result.predicted_values) == 7

    def test_declining_trend_no_breach(self):
        samples = [90, 80, 70, 60, 50]
        result = compute_capacity_forecast(
            metric_name="queue_depth",
            samples=samples,
            threshold=95,
            forecast_steps=5,
        )
        assert result.trend_slope < 0
        assert result.will_breach_threshold is False

    def test_empty_samples_returns_gracefully(self):
        result = compute_capacity_forecast(
            metric_name="test", samples=[], threshold=90, forecast_steps=3
        )
        assert result.current_value == 0.0
        assert result.predicted_values == []

    def test_single_sample_handled(self):
        result = compute_capacity_forecast(
            metric_name="test", samples=[75.0], threshold=90, forecast_steps=3
        )
        assert result.current_value == 75.0
        assert len(result.predicted_values) == 3

    def test_recommendation_contains_metric_name(self):
        samples = [10, 20, 30, 40, 50]
        result = compute_capacity_forecast(
            metric_name="disk_inode_used_percent",
            samples=samples,
            threshold=90,
            forecast_steps=5,
        )
        assert "disk_inode_used_percent" in result.recommendation

    def test_llm_fn_called_and_narrative_set(self):
        samples = [50, 60, 70, 80, 85]
        llm_called = []

        def fake_llm(prompt):
            llm_called.append(prompt)
            return "Scale storage before next week."

        result = compute_capacity_forecast(
            metric_name="disk_used_percent",
            samples=samples,
            threshold=90,
            forecast_steps=3,
            llm_fn=fake_llm,
        )
        assert len(llm_called) == 1
        assert result.narrative == "Scale storage before next week."

    def test_llm_fn_failure_does_not_raise(self):
        def bad_llm(prompt):
            raise RuntimeError("LLM down")

        result = compute_capacity_forecast(
            metric_name="test",
            samples=[10, 20, 30],
            threshold=90,
            forecast_steps=3,
            llm_fn=bad_llm,
        )
        assert result.narrative is None
