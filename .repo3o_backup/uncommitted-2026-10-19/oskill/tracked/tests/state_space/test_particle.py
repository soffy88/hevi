"""Tests for particle_filter_pipeline."""

import numpy as np
import pytest

from oskill.state_space.particle import particle_filter_pipeline


def make_tracking_problem(seed: int = 0, T: int = 50):
    """Create a simple random walk tracking problem."""
    rng = np.random.default_rng(seed)
    states = np.cumsum(rng.normal(0, 0.5, T))
    obs = states + rng.normal(0, 1.0, T)
    return states, obs


def trans_fn(particles, params):
    return particles + np.random.normal(0, params.get("sigma_q", 0.5), len(particles))


def like_fn(particles, obs_t, params):
    sigma_r = params.get("sigma_r", 1.0)
    return np.exp(-0.5 * ((particles - obs_t) / sigma_r) ** 2)


def init_fn(n, params):
    return np.random.normal(0, 1, n)


class TestParticleFilterPipeline:
    def test_basic_shape(self):
        states, obs = make_tracking_problem()
        r = particle_filter_pipeline(
            obs,
            trans_fn,
            like_fn,
            init_fn,
            n_particles=200,
            transition_params={"sigma_q": 0.5},
            likelihood_params={"sigma_r": 1.0},
            seed=42,
        )
        assert r["filtered_states_mean"].shape == (50,)

    def test_returns_all_keys(self):
        _, obs = make_tracking_problem()
        r = particle_filter_pipeline(obs, trans_fn, like_fn, init_fn, n_particles=100, seed=0)
        required = {
            "filtered_states_mean",
            "filtered_states_quantiles",
            "effective_sample_size",
            "log_likelihood",
            "resampling_count",
            "particles_history",
        }
        assert required.issubset(set(r.keys()))

    def test_tracks_random_walk(self):
        """Particle filter should track a random walk (moderate correlation)."""
        states, obs = make_tracking_problem(seed=0, T=50)
        r = particle_filter_pipeline(
            obs,
            trans_fn,
            like_fn,
            init_fn,
            n_particles=500,
            transition_params={"sigma_q": 0.5},
            likelihood_params={"sigma_r": 1.0},
            seed=42,
        )
        corr = np.corrcoef(r["filtered_states_mean"], states)[0, 1]
        assert corr > 0.5

    def test_quantiles_shape(self):
        _, obs = make_tracking_problem()
        r = particle_filter_pipeline(obs, trans_fn, like_fn, init_fn, n_particles=100, seed=1)
        assert r["filtered_states_quantiles"].shape == (50, 5)

    def test_quantiles_ordered(self):
        """5th percentile <= 25th <= 50th <= 75th <= 95th."""
        _, obs = make_tracking_problem()
        r = particle_filter_pipeline(obs, trans_fn, like_fn, init_fn, n_particles=200, seed=2)
        q = r["filtered_states_quantiles"]
        for t in range(50):
            assert q[t, 0] <= q[t, 1] <= q[t, 2] <= q[t, 3] <= q[t, 4]

    def test_ess_positive(self):
        _, obs = make_tracking_problem()
        r = particle_filter_pipeline(obs, trans_fn, like_fn, init_fn, n_particles=200, seed=3)
        assert np.all(r["effective_sample_size"] > 0)

    def test_ess_bounded_by_n_particles(self):
        n = 200
        _, obs = make_tracking_problem()
        r = particle_filter_pipeline(obs, trans_fn, like_fn, init_fn, n_particles=n, seed=4)
        assert np.all(r["effective_sample_size"] <= n + 1e-6)

    def test_seed_reproducibility(self):
        """Same seed → identical results."""
        _, obs = make_tracking_problem()
        r1 = particle_filter_pipeline(obs, trans_fn, like_fn, init_fn, n_particles=100, seed=99)
        r2 = particle_filter_pipeline(obs, trans_fn, like_fn, init_fn, n_particles=100, seed=99)
        np.testing.assert_array_equal(r1["filtered_states_mean"], r2["filtered_states_mean"])

    def test_systematic_resampling(self):
        _, obs = make_tracking_problem()
        r = particle_filter_pipeline(
            obs, trans_fn, like_fn, init_fn, n_particles=200, resampling="systematic", seed=5
        )
        assert "resampling_count" in r

    def test_multinomial_resampling(self):
        _, obs = make_tracking_problem()
        r = particle_filter_pipeline(
            obs, trans_fn, like_fn, init_fn, n_particles=200, resampling="multinomial", seed=6
        )
        assert "resampling_count" in r

    def test_stratified_resampling(self):
        _, obs = make_tracking_problem()
        r = particle_filter_pipeline(
            obs, trans_fn, like_fn, init_fn, n_particles=200, resampling="stratified", seed=7
        )
        assert "resampling_count" in r

    def test_invalid_resampling_raises(self):
        _, obs = make_tracking_problem()
        with pytest.raises(ValueError, match="Unknown resampling"):
            particle_filter_pipeline(
                obs, trans_fn, like_fn, init_fn, n_particles=100, resampling="bad_method", seed=0
            )
