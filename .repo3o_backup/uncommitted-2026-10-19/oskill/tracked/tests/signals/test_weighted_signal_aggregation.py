"""Tests for oskill.signals.aggregation.weighted_signal_aggregation."""

import numpy as np
import pandas as pd
import pytest

from oskill.signals.aggregation import weighted_signal_aggregation


def _identity_corr(n: int) -> np.ndarray:
    """Identity correlation matrix (no correlation)."""
    return np.eye(n)


# ── Happy path ──────────────────────────────────────────────────────────────


def test_weighted_aggregation_returns_dict_with_three_keys():
    s1 = np.array([0.3, 0.5])
    s2 = np.array([0.1, -0.2])
    result = weighted_signal_aggregation({"a": s1, "b": s2}, {"a": 1.0, "b": 1.0})
    assert set(result.keys()) == {"combined", "shrunk_weights", "fdm"}


def test_weighted_aggregation_no_shrinkage():
    """shrinkage=0 uses normalized raw weights without shrinkage."""
    s1 = np.array([1.0, 0.0])
    s2 = np.array([0.0, 1.0])
    corr = _identity_corr(2)
    result = weighted_signal_aggregation(
        {"a": s1, "b": s2},
        {"a": 3.0, "b": 1.0},
        shrinkage=0.0,
        correlation_matrix=corr,
        apply_fdm=False,
    )
    # normalized: a=0.75, b=0.25; no shrinkage, no fdm
    # combined = [0.75, 0.25]
    expected = np.array([0.75, 0.25])
    np.testing.assert_allclose(result["combined"], expected, atol=1e-12)
    assert result["shrunk_weights"]["a"] == pytest.approx(0.75)
    assert result["shrunk_weights"]["b"] == pytest.approx(0.25)


def test_weighted_aggregation_full_shrinkage():
    """shrinkage=1 → equal weights regardless of raw_weights."""
    s1 = np.array([0.6, 0.0])
    s2 = np.array([0.0, 0.6])
    corr = _identity_corr(2)
    result = weighted_signal_aggregation(
        {"a": s1, "b": s2},
        {"a": 100.0, "b": 1.0},
        shrinkage=1.0,
        correlation_matrix=corr,
        apply_fdm=False,
    )
    # Full shrinkage → equal weights 0.5, 0.5
    expected = np.array([0.3, 0.3])
    np.testing.assert_allclose(result["combined"], expected, atol=1e-12)
    assert result["shrunk_weights"]["a"] == pytest.approx(0.5)
    assert result["shrunk_weights"]["b"] == pytest.approx(0.5)


def test_weighted_aggregation_default_carver_70percent():
    """Default shrinkage=0.7: 30% raw + 70% equal."""
    s1 = np.array([1.0])
    s2 = np.array([0.0])
    corr = _identity_corr(2)
    result = weighted_signal_aggregation(
        {"a": s1, "b": s2},
        {"a": 1.0, "b": 0.0},
        shrinkage=0.7,
        correlation_matrix=corr,
        apply_fdm=False,
    )
    # raw normalized: a=1.0, b=0.0 (but b=0 will make w_sum=1, so raw a=1, b=0)
    # shrunk a = 0.3*1 + 0.7*0.5 = 0.3 + 0.35 = 0.65
    # shrunk b = 0.3*0 + 0.7*0.5 = 0.35
    # renorm: a=0.65/(0.65+0.35)=0.65, b=0.35
    combined = 0.65 * 1.0 + 0.35 * 0.0
    np.testing.assert_allclose(result["combined"][0], combined, atol=1e-12)


def test_weighted_aggregation_fdm_computation():
    """FDM = 1/sqrt(w^T Sigma w); identity corr gives fdm=1/sqrt(sum(w_i^2))."""
    s1 = np.array([0.5, 0.5])
    s2 = np.array([0.5, 0.5])
    corr = _identity_corr(2)
    result = weighted_signal_aggregation(
        {"a": s1, "b": s2},
        {"a": 1.0, "b": 1.0},
        shrinkage=0.0,
        correlation_matrix=corr,
        apply_fdm=True,
    )
    # w = [0.5, 0.5], sigma = I
    # quad = 0.25 + 0.25 = 0.5
    # FDM = 1/sqrt(0.5) = sqrt(2)
    expected_fdm = 1.0 / np.sqrt(0.5)
    assert result["fdm"] == pytest.approx(expected_fdm, rel=1e-8)


def test_weighted_aggregation_no_fdm():
    """apply_fdm=False → fdm=1.0, combined unchanged by fdm."""
    s1 = np.array([0.5])
    s2 = np.array([0.3])
    result = weighted_signal_aggregation(
        {"a": s1, "b": s2},
        {"a": 1.0, "b": 1.0},
        shrinkage=0.0,
        correlation_matrix=_identity_corr(2),
        apply_fdm=False,
    )
    assert result["fdm"] == pytest.approx(1.0)


def test_weighted_aggregation_correlation_from_signals():
    """When correlation_matrix=None, estimates from signal data via pandas .corr()."""
    rng = np.random.default_rng(42)
    s1 = rng.uniform(-1, 1, 50)
    s2 = rng.uniform(-1, 1, 50)
    result = weighted_signal_aggregation(
        {"a": s1, "b": s2},
        {"a": 1.0, "b": 1.0},
        shrinkage=0.0,
        correlation_matrix=None,
        apply_fdm=True,
    )
    # Just verify we get a valid result without error
    assert isinstance(result["fdm"], float)
    assert result["fdm"] > 0
    assert len(result["combined"]) == 50


def test_weighted_aggregation_correlation_provided():
    """Provided correlation matrix is used directly."""
    s1 = np.array([0.5, 0.6])
    s2 = np.array([0.3, 0.4])
    # Perfect correlation
    corr = np.array([[1.0, 1.0], [1.0, 1.0]])
    result = weighted_signal_aggregation(
        {"a": s1, "b": s2},
        {"a": 1.0, "b": 1.0},
        shrinkage=0.0,
        correlation_matrix=corr,
        apply_fdm=True,
    )
    # w=[0.5, 0.5], Sigma=[[1,1],[1,1]], quad = 0.5*0.5*4 = 1 → FDM=1
    assert result["fdm"] == pytest.approx(1.0, rel=1e-8)


def test_weighted_aggregation_clips_to_minus_two_two():
    """Combined output is clipped to [-2, 2]."""
    s1 = np.array([5.0, -5.0])
    s2 = np.array([5.0, -5.0])
    result = weighted_signal_aggregation(
        {"a": s1, "b": s2},
        {"a": 1.0, "b": 1.0},
        shrinkage=0.0,
        correlation_matrix=_identity_corr(2),
        apply_fdm=False,
    )
    combined = result["combined"]
    assert (combined <= 2.0).all()
    assert (combined >= -2.0).all()


def test_weighted_aggregation_preserves_pandas_series():
    """Returns pd.Series with original index when inputs are pd.Series."""
    idx = pd.date_range("2024-01-01", periods=3)
    s1 = pd.Series([0.1, 0.2, 0.3], index=idx)
    s2 = pd.Series([0.3, 0.2, 0.1], index=idx)
    result = weighted_signal_aggregation(
        {"a": s1, "b": s2},
        {"a": 1.0, "b": 1.0},
        correlation_matrix=_identity_corr(2),
        apply_fdm=False,
    )
    assert isinstance(result["combined"], pd.Series)
    assert result["combined"].index.equals(idx)


# ── Exception cases ──────────────────────────────────────────────────────────


def test_weighted_aggregation_invalid_shrinkage_raises():
    with pytest.raises(ValueError, match="shrinkage"):
        weighted_signal_aggregation(
            {"a": np.array([0.5])},
            {"a": 1.0},
            shrinkage=1.5,
        )


def test_weighted_aggregation_invalid_shrinkage_negative_raises():
    with pytest.raises(ValueError, match="shrinkage"):
        weighted_signal_aggregation(
            {"a": np.array([0.5])},
            {"a": 1.0},
            shrinkage=-0.1,
        )


def test_weighted_aggregation_non_psd_correlation_raises():
    """Non-PSD correlation matrix raises ValueError."""
    s1 = np.array([0.5])
    s2 = np.array([0.3])
    bad_corr = np.array([[1.0, 2.0], [2.0, 1.0]])  # eigenvalues: 3, -1
    with pytest.raises(ValueError, match="positive semi-definite"):
        weighted_signal_aggregation(
            {"a": s1, "b": s2},
            {"a": 1.0, "b": 1.0},
            correlation_matrix=bad_corr,
        )


def test_weighted_aggregation_wrong_corr_shape_raises():
    s1 = np.array([0.5])
    s2 = np.array([0.3])
    bad_corr = np.eye(3)  # 3x3 but only 2 signals
    with pytest.raises(ValueError, match="shape"):
        weighted_signal_aggregation(
            {"a": s1, "b": s2},
            {"a": 1.0, "b": 1.0},
            correlation_matrix=bad_corr,
        )


def test_weighted_aggregation_asymmetric_corr_raises():
    s1 = np.array([0.5])
    s2 = np.array([0.3])
    bad_corr = np.array([[1.0, 0.8], [0.2, 1.0]])
    with pytest.raises(ValueError, match="symmetric"):
        weighted_signal_aggregation(
            {"a": s1, "b": s2},
            {"a": 1.0, "b": 1.0},
            correlation_matrix=bad_corr,
        )


def test_weighted_aggregation_missing_weight_raises():
    with pytest.raises(ValueError, match="Missing weight"):
        weighted_signal_aggregation(
            {"a": np.array([0.5]), "b": np.array([0.3])},
            {"a": 1.0},
        )


def test_weighted_aggregation_negative_weight_raises():
    with pytest.raises(ValueError, match="non-negative"):
        weighted_signal_aggregation(
            {"a": np.array([0.5])},
            {"a": -1.0},
        )


# ── Academic reference ────────────────────────────────────────────────────────


@pytest.mark.academic_reference
def test_weighted_aggregation_carver_example():
    """Carver (2015) Systematic Trading Ch.8: 3-layer combination.

    Two signals momentum (weight 2) and carry (weight 1).
    Shrinkage 0.7 toward equal weights. No FDM for reference comparison.
    Reference: Carver (2015), "Systematic Trading", Chapter 8.
    rtol=1e-8 for floating-point determinism.
    """
    # Carver's example: 2 signals
    momentum = np.array([0.6])
    carry = np.array([0.2])

    # raw normalized: momentum=2/3, carry=1/3
    # shrunk: momentum = 0.3*(2/3) + 0.7*0.5 = 0.2 + 0.35 = 0.55
    #         carry    = 0.3*(1/3) + 0.7*0.5 = 0.1 + 0.35 = 0.45
    # sum = 1.0 (already normalized)
    # combined = 0.55*0.6 + 0.45*0.2 = 0.33 + 0.09 = 0.42

    result = weighted_signal_aggregation(
        {"momentum": momentum, "carry": carry},
        {"momentum": 2.0, "carry": 1.0},
        shrinkage=0.7,
        correlation_matrix=_identity_corr(2),
        apply_fdm=False,
    )

    expected_momentum_w = 0.3 * (2.0 / 3.0) + 0.7 * 0.5
    expected_carry_w = 0.3 * (1.0 / 3.0) + 0.7 * 0.5
    expected_combined = expected_momentum_w * 0.6 + expected_carry_w * 0.2

    np.testing.assert_allclose(result["combined"][0], expected_combined, rtol=1e-8)
    assert result["shrunk_weights"]["momentum"] == pytest.approx(expected_momentum_w, rel=1e-8)
    assert result["shrunk_weights"]["carry"] == pytest.approx(expected_carry_w, rel=1e-8)
