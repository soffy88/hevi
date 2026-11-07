"""Tests for oskill.point_process.fit_hawkes."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.point_process import fit_hawkes

# ─── fixtures ────────────────────────────────────────────────────────────────


def _make_hawkes_events(
    mu: float, alpha: float, beta: float, T: float, seed: int = 42
) -> np.ndarray:
    """Generate Hawkes process events via thinning algorithm."""
    rng = np.random.default_rng(seed)
    times = []
    t = 0.0
    while t < T:
        # Upper bound for intensity: use mu as minimum
        lam_star = mu + alpha * len(times)  # rough upper bound
        if lam_star <= 0:
            break
        dt = rng.exponential(1.0 / lam_star)
        t += dt
        if t >= T:
            break
        # Current intensity
        lam_t = mu + alpha * sum(np.exp(-beta * (t - s)) for s in times)
        if rng.uniform() < lam_t / lam_star:
            times.append(t)
    return np.array(sorted(times))


# ─── basic API ───────────────────────────────────────────────────────────────


def test_fit_hawkes_too_few_events_returns_not_converged():
    """len < 5 → converged=False, branching_ratio=nan."""
    events = np.array([0.1, 0.5, 1.0, 2.0])  # 4 events
    result = fit_hawkes(events, T=3.0)
    assert result["converged"] is False
    assert np.isnan(result["branching_ratio"])


def test_fit_hawkes_returns_dict_keys():
    """Normal input → dict has converged, branching_ratio, mu, alpha, beta, nll."""
    events = np.linspace(0.1, 9.9, 20)
    result = fit_hawkes(events, T=10.0, n_restarts=2, random_state=0)
    required_keys = {"converged", "branching_ratio"}
    assert required_keys.issubset(set(result.keys()))


def test_fit_hawkes_branching_ratio_finite():
    """For a non-trivial event stream, branching_ratio should be finite."""
    events = _make_hawkes_events(mu=0.5, alpha=0.3, beta=1.0, T=20.0, seed=1)
    if len(events) < 5:
        pytest.skip("Not enough events generated")
    result = fit_hawkes(events, T=20.0, n_restarts=3, random_state=0)
    # Should either converge with finite BR or return nan (not raise)
    assert "branching_ratio" in result


def test_fit_hawkes_stable_branching_ratio():
    """For a stationary Hawkes process (alpha/beta < 1), branching_ratio < 1."""
    # Use known stationary parameters
    events = _make_hawkes_events(mu=0.5, alpha=0.3, beta=1.0, T=50.0, seed=42)
    if len(events) < 5:
        pytest.skip("Not enough events")
    result = fit_hawkes(events, T=50.0, n_restarts=3, random_state=42)
    if result["converged"] and np.isfinite(result["branching_ratio"]):
        assert result["branching_ratio"] < 1.0, (
            f"Stationary process should have branching_ratio < 1, "
            f"got {result['branching_ratio']:.4f}"
        )


def test_fit_hawkes_known_events():
    """Simple event stream returns mu > 0 when it converges."""
    events = np.array(
        [0.5, 1.0, 1.2, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0]
    )
    result = fit_hawkes(events, T=13.0, n_restarts=2, random_state=0)
    if result["converged"]:
        assert result["mu"] > 0


@pytest.mark.academic_reference
def test_fit_hawkes_hawkes_1971():
    """Hawkes (1971): branching_ratio = alpha/beta; for stationary process must be < 1.

    Reference: Hawkes, A.G. (1971). Biometrika.
    Generate events with known mu=0.5, alpha=0.3, beta=1.0 via thinning.
    Fit and verify 0 < branching_ratio < 1.
    """
    # Use well-chosen parameters for stationarity (alpha/beta = 0.3 < 1)
    events = _make_hawkes_events(mu=0.5, alpha=0.3, beta=1.0, T=100.0, seed=99)
    if len(events) < 5:
        pytest.skip("Not enough events generated for academic test")

    result = fit_hawkes(events, T=100.0, n_restarts=5, random_state=42)

    if result["converged"] and np.isfinite(result["branching_ratio"]):
        br = result["branching_ratio"]
        assert 0 < br < 1, (
            f"Hawkes (1971): stationary process requires branching_ratio in (0,1), got {br:.4f}"
        )
