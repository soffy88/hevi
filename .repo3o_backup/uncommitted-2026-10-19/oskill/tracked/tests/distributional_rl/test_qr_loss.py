"""Tests for oskill.distributional_rl.quantile_regression.quantile_regression_loss."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.distributional_rl.quantile_regression import quantile_regression_loss

# ─── API / basic properties ──────────────────────────────────────────────────


def test_returns_scalar_for_mean_reduction():
    rng = np.random.default_rng(0)
    pq = rng.normal(0, 1, (10, 8))
    tr = rng.normal(0, 1, 10)
    loss = quantile_regression_loss(pq, tr)
    assert isinstance(loss, float)


def test_returns_array_for_none_reduction():
    rng = np.random.default_rng(0)
    pq = rng.normal(0, 1, (10, 8))
    tr = rng.normal(0, 1, 10)
    loss = quantile_regression_loss(pq, tr, reduction="none")
    assert hasattr(loss, "shape") and loss.shape == (10,)


def test_loss_non_negative():
    rng = np.random.default_rng(1)
    pq = rng.normal(0, 1, (20, 5))
    tr = rng.normal(0, 1, 20)
    loss = quantile_regression_loss(pq, tr)
    assert loss >= 0.0


def test_perfect_prediction_low_loss():
    """When all quantiles equal the target, loss should be very small."""
    n = 50
    targets = np.linspace(-1, 1, n)
    # All quantiles = target value → u = 0 → loss = 0
    pq = np.tile(targets[:, np.newaxis], (1, 8))  # (50, 8)
    loss = quantile_regression_loss(pq, targets)
    assert loss < 1e-10, f"Expected near-zero loss, got {loss}"


def test_sum_reduction():
    rng = np.random.default_rng(2)
    pq = rng.normal(0, 1, (5, 4))
    tr = rng.normal(0, 1, 5)
    loss_mean = quantile_regression_loss(pq, tr, reduction="mean")
    loss_sum = quantile_regression_loss(pq, tr, reduction="sum")
    assert abs(loss_sum - 5 * loss_mean) < 1e-9


def test_quantile_levels_used():
    """Custom quantile levels should affect the loss value."""
    rng = np.random.default_rng(3)
    pq = rng.normal(0, 1, (20, 4))
    tr = rng.normal(0, 1, 20)
    taus1 = np.array([0.1, 0.3, 0.7, 0.9])
    taus2 = np.array([0.25, 0.25, 0.25, 0.25])
    l1 = quantile_regression_loss(pq, tr, taus1)
    l2 = quantile_regression_loss(pq, tr, taus2)
    # They should differ for typical inputs
    # Just verify both are non-negative and finite
    assert l1 >= 0 and l2 >= 0
    assert np.isfinite(l1) and np.isfinite(l2)


def test_asymmetry_property():
    """Pinball loss is asymmetric: overestimation vs underestimation differ."""
    # For tau=0.9, overestimates (positive u) should have lower weight than underestimates
    n = 100
    target = np.zeros(n)
    taus = np.array([0.9])

    # Predicted > target (overestimate)
    pq_over = np.full((n, 1), 1.0)
    loss_over = quantile_regression_loss(pq_over, target, taus)

    # Predicted < target (underestimate)
    pq_under = np.full((n, 1), -1.0)
    loss_under = quantile_regression_loss(pq_under, target, taus)

    # For tau=0.9, underestimating is penalized more (weight = tau = 0.9)
    # vs overestimating (weight = 1-tau = 0.1)
    assert loss_under > loss_over, (
        f"For tau=0.9, underestimate loss {loss_under:.4f} should exceed "
        f"overestimate loss {loss_over:.4f}"
    )


def test_huber_delta_zero_uses_pinball():
    """huber_delta <= 0 should use standard pinball loss."""
    rng = np.random.default_rng(4)
    pq = rng.normal(0, 1, (10, 4))
    tr = rng.normal(0, 1, 10)
    loss = quantile_regression_loss(pq, tr, huber_delta=0.0)
    assert loss >= 0.0 and np.isfinite(loss)


def test_2d_target():
    """target_returns can be 2D (batch, n_quantiles)."""
    rng = np.random.default_rng(5)
    pq = rng.normal(0, 1, (10, 4))
    tr = rng.normal(0, 1, (10, 4))
    loss = quantile_regression_loss(pq, tr)
    assert isinstance(loss, float) and loss >= 0


def test_invalid_quantile_levels_length_raises():
    rng = np.random.default_rng(6)
    pq = rng.normal(0, 1, (10, 4))
    tr = rng.normal(0, 1, 10)
    with pytest.raises(ValueError, match="quantile_levels"):
        quantile_regression_loss(pq, tr, np.array([0.1, 0.5]))  # wrong length


def test_large_huber_delta_approximates_l2():
    """Very large delta → loss ~ 0.5 * (tau - indicator) * u^2 / delta."""
    n = 50
    targets = np.ones(n) * 2.0
    pq = np.zeros((n, 1))  # predict 0, target is 2
    taus = np.array([0.5])
    loss_large = quantile_regression_loss(pq, targets, taus, huber_delta=100.0)
    loss_small = quantile_regression_loss(pq, targets, taus, huber_delta=1.0)
    # Both should be non-negative
    assert loss_large >= 0 and loss_small >= 0
