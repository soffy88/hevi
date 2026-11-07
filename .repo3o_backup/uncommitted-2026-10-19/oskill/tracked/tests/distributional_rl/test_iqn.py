"""Tests for oskill.distributional_rl.iqn.implicit_quantile_loss."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.distributional_rl.iqn import implicit_quantile_loss


def _make_inputs(batch=10, n_sample=8, n_target=8, seed=0):
    rng = np.random.default_rng(seed)
    pq = rng.normal(0, 1, (batch, n_sample))
    tq = rng.normal(0, 1, (batch, n_target))
    st = rng.uniform(0, 1, (batch, n_sample))
    return pq, tq, st


# ─── API / basic properties ──────────────────────────────────────────────────


def test_returns_scalar_mean_reduction():
    pq, tq, st = _make_inputs()
    loss = implicit_quantile_loss(pq, tq, st)
    assert isinstance(loss, float)


def test_returns_array_none_reduction():
    pq, tq, st = _make_inputs(batch=10)
    loss = implicit_quantile_loss(pq, tq, st, reduction="none")
    assert hasattr(loss, "shape") and loss.shape == (10,)


def test_loss_non_negative():
    pq, tq, st = _make_inputs()
    loss = implicit_quantile_loss(pq, tq, st)
    assert loss >= 0.0


def test_perfect_prediction_zero_loss():
    """When predicted == target at every quantile, loss ~ 0."""
    n = 20
    target = np.linspace(-1, 1, n)
    pq = np.tile(target[:, np.newaxis], (1, 5))
    tq = np.tile(target[:, np.newaxis], (1, 5))
    st = np.tile(np.linspace(0.1, 0.9, 5)[np.newaxis, :], (n, 1))
    loss = implicit_quantile_loss(pq, tq, st)
    assert loss < 1e-10, f"Expected near-zero, got {loss}"


def test_sum_reduction():
    pq, tq, st = _make_inputs(batch=6)
    loss_mean = implicit_quantile_loss(pq, tq, st, reduction="mean")
    loss_sum = implicit_quantile_loss(pq, tq, st, reduction="sum")
    assert abs(loss_sum - 6 * loss_mean) < 1e-8


def test_1d_target():
    """1-D target (returns) should work."""
    rng = np.random.default_rng(1)
    batch = 10
    pq = rng.normal(0, 1, (batch, 5))
    tq = rng.normal(0, 1, batch)
    st = rng.uniform(0, 1, (batch, 5))
    loss = implicit_quantile_loss(pq, tq, st)
    assert isinstance(loss, float) and loss >= 0


def test_huber_delta_zero():
    pq, tq, st = _make_inputs()
    loss = implicit_quantile_loss(pq, tq, st, huber_delta=0.0)
    assert loss >= 0.0 and np.isfinite(loss)


def test_wrong_sample_taus_shape_raises():
    pq, tq, st = _make_inputs(batch=10, n_sample=8)
    bad_st = np.random.default_rng(0).uniform(0, 1, (10, 5))  # wrong n_sample
    with pytest.raises(ValueError, match="sample_taus"):
        implicit_quantile_loss(pq, tq, bad_st)


def test_finite_output():
    pq, tq, st = _make_inputs(seed=99)
    loss = implicit_quantile_loss(pq, tq, st)
    assert np.isfinite(loss)
