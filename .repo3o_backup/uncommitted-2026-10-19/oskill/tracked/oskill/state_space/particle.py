"""Sequential Monte Carlo (particle filter) pipeline."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np


def _systematic_resample(weights: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """Systematic resampling."""
    positions = (rng.uniform(0, 1) + np.arange(n)) / n
    cumsum = np.cumsum(weights)
    indices = np.searchsorted(cumsum, positions)
    return np.clip(indices, 0, n - 1)


def _multinomial_resample(weights: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """Multinomial resampling."""
    return rng.choice(n, size=n, replace=True, p=weights)


def _stratified_resample(weights: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """Stratified resampling."""
    positions = (rng.uniform(size=n) + np.arange(n)) / n
    cumsum = np.cumsum(weights)
    indices = np.searchsorted(cumsum, positions)
    return np.clip(indices, 0, n - 1)


def particle_filter_pipeline(
    observations: np.ndarray,
    transition_fn: Callable,
    likelihood_fn: Callable,
    initial_particle_fn: Callable,
    *,
    n_particles: int = 1000,
    transition_params: dict[str, Any] | None = None,
    likelihood_params: dict[str, Any] | None = None,
    resampling: str = "systematic",
    seed: int | None = None,
) -> dict[str, Any]:
    """Sequential Monte Carlo (SMC) particle filter.

    Algorithm:
    1. Initialize N particles from initial_particle_fn(n_particles, params).
    2. For each observation t:
       a. Propagate: particles = transition_fn(particles, params).
       b. Weights: w_i = likelihood_fn(particles_i, obs_t, params).
       c. Normalize weights.
       d. ESS = 1 / sum(w^2); if ESS < N/2: resample.
    3. State estimate = weighted mean of particles.

    Parameters
    ----------
    observations : np.ndarray
        1-D observation sequence of length T.
    transition_fn : Callable
        f(particles, params) -> propagated particles array (n_particles,).
    likelihood_fn : Callable
        f(particles, obs_t, params) -> unnormalized weights array (n_particles,).
    initial_particle_fn : Callable
        f(n_particles, params) -> initial particles array (n_particles,).
    n_particles : int
        Number of particles.
    transition_params : dict, optional
        Parameters passed to transition_fn.
    likelihood_params : dict, optional
        Parameters passed to likelihood_fn.
    resampling : str
        'systematic', 'multinomial', or 'stratified'.
    seed : int, optional
        Random seed for reproducibility.

    Returns
    -------
    dict with keys:
        'filtered_states_mean': np.ndarray (T,) — weighted mean state estimate
        'filtered_states_quantiles': np.ndarray (T, 5) — 5/25/50/75/95 percentile estimates
        'effective_sample_size': np.ndarray (T,) — ESS at each time step
        'log_likelihood': float — total approximate log-likelihood
        'resampling_count': int — number of resampling steps performed
        'particles_history': np.ndarray (T, n_particles) — all particle trajectories
    """
    observations = np.asarray(observations, dtype=float)
    T = len(observations)

    rng = np.random.default_rng(seed)
    # Monkey-patch global numpy random to match (for transition/likelihood fns that use np.random)
    if seed is not None:
        np.random.seed(seed)

    tp = transition_params or {}
    lp = likelihood_params or {}

    # Select resampling method
    resamplers = {
        "systematic": _systematic_resample,
        "multinomial": _multinomial_resample,
        "stratified": _stratified_resample,
    }
    if resampling not in resamplers:
        raise ValueError(f"Unknown resampling '{resampling}'. Use: {list(resamplers.keys())}")
    resample_fn = resamplers[resampling]

    # Initialize particles
    particles = initial_particle_fn(n_particles, tp)
    particles = np.asarray(particles, dtype=float)
    weights = np.full(n_particles, 1.0 / n_particles)

    # Storage
    filtered_means = np.zeros(T)
    filtered_quantiles = np.zeros((T, 5))
    ess_history = np.zeros(T)
    log_lik = 0.0
    resampling_count = 0
    particles_history = np.zeros((T, n_particles))

    quantile_levels = [5, 25, 50, 75, 95]

    for t in range(T):
        # --- Propagate ---
        particles = transition_fn(particles, tp)
        particles = np.asarray(particles, dtype=float)

        # --- Weighting ---
        w = likelihood_fn(particles, observations[t], lp)
        w = np.asarray(w, dtype=float)
        w = np.where(np.isfinite(w) & (w > 0), w, 1e-300)
        w_sum = w.sum()

        # Accumulate log-likelihood
        log_lik += np.log(w_sum / n_particles) if w_sum > 0 else -1e10

        # Normalize
        weights = w / w_sum

        # --- State estimate ---
        filtered_means[t] = np.dot(weights, particles)
        # Weighted quantiles (approximate via sorted weighted particles)
        sort_idx = np.argsort(particles)
        sorted_p = particles[sort_idx]
        sorted_w = weights[sort_idx]
        cumw = np.cumsum(sorted_w)
        for qi, ql in enumerate(quantile_levels):
            q_frac = ql / 100.0
            idx = np.searchsorted(cumw, q_frac)
            filtered_quantiles[t, qi] = sorted_p[min(idx, n_particles - 1)]

        particles_history[t] = particles

        # --- ESS ---
        ess = 1.0 / np.sum(weights**2)
        ess_history[t] = ess

        # --- Resample if ESS < N/2 ---
        if ess < n_particles / 2:
            indices = resample_fn(weights, n_particles, rng)
            particles = particles[indices]
            weights = np.full(n_particles, 1.0 / n_particles)
            resampling_count += 1

    return {
        "filtered_states_mean": filtered_means,
        "filtered_states_quantiles": filtered_quantiles,
        "effective_sample_size": ess_history,
        "log_likelihood": log_lik,
        "resampling_count": resampling_count,
        "particles_history": particles_history,
    }
