"""Tests for oskill.signals.ensemble.signal_ensemble."""

import numpy as np
import pandas as pd
import pytest

from oskill.signals.ensemble import signal_ensemble

# ── Happy path ──────────────────────────────────────────────────────────────


def test_signal_ensemble_linear_basic():
    """2 signals equal weights → weighted mean."""
    s1 = np.array([0.4, 0.6, -0.2])
    s2 = np.array([0.2, 0.4, 0.8])
    result = signal_ensemble({"a": s1, "b": s2}, {"a": 1.0, "b": 1.0})
    expected = np.array([0.3, 0.5, 0.3])
    np.testing.assert_allclose(result, expected, atol=1e-12)


def test_signal_ensemble_linear_unequal_weights():
    """Unequal weights produce correct normalized average."""
    s1 = np.array([1.0, 0.0])
    s2 = np.array([0.0, 1.0])
    result = signal_ensemble({"a": s1, "b": s2}, {"a": 3.0, "b": 1.0})
    expected = np.array([0.75, 0.25])
    np.testing.assert_allclose(result, expected, atol=1e-12)


def test_signal_ensemble_geometric_basic():
    """Geometric aggregation of equal signals returns same signal."""
    vals = np.array([0.5, -0.3, 0.1])
    result = signal_ensemble({"a": vals, "b": vals}, {"a": 1.0, "b": 1.0}, aggregation="geometric")
    np.testing.assert_allclose(result, vals, atol=1e-10)


def test_signal_ensemble_geometric_two_signals():
    """Geometric mean of [0, 0] is 0; of [0.5, 0.5] is 0.5."""
    s1 = np.array([0.0, 0.5])
    s2 = np.array([0.0, 0.5])
    result = signal_ensemble({"a": s1, "b": s2}, {"a": 1.0, "b": 1.0}, aggregation="geometric")
    # prod((s+1)^0.5)^(1/1) - 1
    # [0]: (1^0.5 * 1^0.5)^1 - 1 = 1 - 1 = 0
    # [1]: (1.5^0.5 * 1.5^0.5)^1 - 1 = 1.5 - 1 = 0.5
    np.testing.assert_allclose(result, np.array([0.0, 0.5]), atol=1e-10)


def test_signal_ensemble_harmonic_basic():
    """Harmonic mean of equal signals returns same signal."""
    vals = np.array([0.5, 0.8, -0.4])
    result = signal_ensemble({"a": vals, "b": vals}, {"a": 1.0, "b": 1.0}, aggregation="harmonic")
    np.testing.assert_allclose(result, vals, atol=1e-10)


def test_signal_ensemble_with_decay_fn():
    """Custom decay_fn multiplies combined signal by time-based factor."""
    # decay_fn: most recent (lag=0) → 1.0, oldest (lag=n-1) → near 0
    n = 5
    vals = np.ones(n) * 0.5

    def decay(lag):
        return 1.0 - lag / (n - 1)

    result = signal_ensemble({"a": vals}, {"a": 1.0}, decay_fn=decay)
    # t=0 is oldest (lag=4), t=4 is most recent (lag=0)
    expected_factors = [1.0 - (n - 1 - t) / (n - 1) for t in range(n)]
    expected = np.clip(np.array(expected_factors) * 0.5, -1, 1)
    np.testing.assert_allclose(result, expected, atol=1e-12)


def test_signal_ensemble_decay_lookback():
    """decay_lookback triggers linear decay automatically."""
    n = 5
    vals = np.ones(n) * 1.0
    result = signal_ensemble({"a": vals}, {"a": 1.0}, decay_lookback=n - 1)
    # lag = n-1-t, weight = max(0, 1 - lag/(n-1))
    expected = np.array([1.0 - (n - 1 - t) / (n - 1) for t in range(n)])
    expected = np.clip(expected, -1, 1)
    np.testing.assert_allclose(result, expected, atol=1e-12)


def test_signal_ensemble_default_no_decay():
    """No decay: full weight applied uniformly."""
    s1 = np.array([0.5, 0.5, 0.5])
    result = signal_ensemble({"a": s1}, {"a": 1.0})
    np.testing.assert_allclose(result, s1, atol=1e-12)


def test_signal_ensemble_clips_to_minus_one_one():
    """Clips output to [-1, 1] even for large raw inputs."""
    s1 = np.array([2.0, -3.0, 0.5])
    result = signal_ensemble({"a": s1}, {"a": 1.0})
    assert (result <= 1.0).all()
    assert (result >= -1.0).all()


def test_signal_ensemble_preserves_pandas_index():
    """Output is pd.Series with same index as input."""
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    s1 = pd.Series([0.1, 0.2, 0.3, 0.4], index=idx)
    s2 = pd.Series([0.4, 0.3, 0.2, 0.1], index=idx)
    result = signal_ensemble({"a": s1, "b": s2}, {"a": 1.0, "b": 1.0})
    assert isinstance(result, pd.Series)
    assert result.index.equals(idx)


# ── Edge cases ───────────────────────────────────────────────────────────────


def test_signal_ensemble_single_signal():
    """Single signal returned as-is (after clip)."""
    vals = np.array([0.3, -0.7, 0.9])
    result = signal_ensemble({"x": vals}, {"x": 5.0})
    np.testing.assert_allclose(result, vals, atol=1e-12)


def test_signal_ensemble_harmonic_all_zeros_gives_zero():
    """All-zero signals in harmonic mean produce 0 (no divide-by-zero error)."""
    s1 = np.array([0.0, 0.5])
    s2 = np.array([0.0, 0.5])
    result = signal_ensemble({"a": s1, "b": s2}, {"a": 1.0, "b": 1.0}, aggregation="harmonic")
    assert result[0] == pytest.approx(0.0)
    assert result[1] == pytest.approx(0.5)


# ── Exception cases ──────────────────────────────────────────────────────────


def test_signal_ensemble_empty_signals_raises():
    with pytest.raises(ValueError, match="empty"):
        signal_ensemble({}, {})


def test_signal_ensemble_misaligned_signals_raises():
    with pytest.raises(ValueError, match="length"):
        signal_ensemble(
            {"a": np.array([1.0, 2.0]), "b": np.array([1.0])},
            {"a": 1.0, "b": 1.0},
        )


def test_signal_ensemble_missing_weight_raises():
    with pytest.raises(ValueError, match="Missing weight"):
        signal_ensemble(
            {"a": np.array([1.0]), "b": np.array([2.0])},
            {"a": 1.0},
        )


def test_signal_ensemble_extra_weight_key_raises():
    with pytest.raises(ValueError, match="not found in signals"):
        signal_ensemble(
            {"a": np.array([1.0])},
            {"a": 1.0, "b": 0.5},
        )


def test_signal_ensemble_negative_weight_raises():
    with pytest.raises(ValueError, match="non-negative"):
        signal_ensemble(
            {"a": np.array([1.0])},
            {"a": -1.0},
        )


def test_signal_ensemble_zero_weight_sum_raises():
    with pytest.raises(ValueError, match="Sum of weights"):
        signal_ensemble(
            {"a": np.array([1.0])},
            {"a": 0.0},
        )


def test_signal_ensemble_mismatched_pandas_index_raises():
    idx1 = pd.date_range("2024-01-01", periods=3)
    idx2 = pd.date_range("2024-01-02", periods=3)
    s1 = pd.Series([1.0, 2.0, 3.0], index=idx1)
    s2 = pd.Series([1.0, 2.0, 3.0], index=idx2)
    with pytest.raises(ValueError, match="different pandas index"):
        signal_ensemble({"a": s1, "b": s2}, {"a": 1.0, "b": 1.0})


def test_signal_ensemble_unknown_aggregation_raises():
    with pytest.raises(ValueError, match="Unknown aggregation"):
        signal_ensemble({"a": np.array([0.5])}, {"a": 1.0}, aggregation="median")  # type: ignore


# ── Academic reference ────────────────────────────────────────────────────────


@pytest.mark.academic_reference
def test_signal_ensemble_carver_textbook_example():
    """Carver (2015) Systematic Trading Ch.10: linear weighted ensemble.

    Two signals with weights 2:1. Expected result is weighted mean.
    Reference: Carver (2015), "Systematic Trading", Chapter 10.
    Tolerance: rtol=1e-8 for floating-point determinism.
    """
    # From Carver's worked example: two forecasts, weights 2:1
    # momentum signal: 0.5, carry signal: 0.2
    # Expected combined = (2 * 0.5 + 1 * 0.2) / 3 = 1.2/3 = 0.4
    momentum = np.array([0.5])
    carry = np.array([0.2])
    result = signal_ensemble(
        {"momentum": momentum, "carry": carry},
        {"momentum": 2.0, "carry": 1.0},
        aggregation="linear",
    )
    expected = np.array([0.4])
    np.testing.assert_allclose(result, expected, rtol=1e-8)
