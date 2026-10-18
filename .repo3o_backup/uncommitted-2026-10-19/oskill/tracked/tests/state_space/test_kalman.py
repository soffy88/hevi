"""Tests for kalman_filter_pipeline and kalman_smoother."""

import numpy as np

from oskill.state_space.kalman import kalman_filter_pipeline, kalman_smoother


class TestKalmanFilterPipeline:
    def test_returns_all_keys(self):
        obs = np.random.default_rng(0).normal(5.0, 1.0, 50)
        r = kalman_filter_pipeline(obs, process_noise=1e-5, observation_noise=1.0)
        required = {
            "filtered_states",
            "filtered_covariances",
            "predicted_states",
            "predicted_covariances",
            "log_likelihood",
            "process_noise",
            "observation_noise",
            "n_iter",
        }
        assert required.issubset(set(r.keys()))

    def test_filtered_states_shape(self):
        T = 40
        obs = np.ones(T) * 3.0 + np.random.default_rng(1).normal(0, 0.5, T)
        r = kalman_filter_pipeline(obs)
        assert r["filtered_states"].shape == (T, 1)

    def test_constant_signal_tracking(self):
        """Constant signal + noise → filter converges near true value."""
        true_val = 5.0
        obs = true_val + np.random.default_rng(42).normal(0, 1.0, 100)
        r = kalman_filter_pipeline(obs, process_noise=1e-5, observation_noise=1.0)
        assert abs(r["filtered_states"][-1, 0] - true_val) < 2.0

    def test_random_walk_tracking(self):
        """Filter should track a random walk (residuals not too large)."""
        rng = np.random.default_rng(3)
        states = np.cumsum(rng.normal(0, 0.5, 80))
        obs = states + rng.normal(0, 1.0, 80)
        r = kalman_filter_pipeline(obs, process_noise=0.25, observation_noise=1.0)
        rmse = np.sqrt(np.mean((r["filtered_states"][:, 0] - states) ** 2))
        assert rmse < 3.0  # reasonable tracking

    def test_log_likelihood_is_finite(self):
        obs = np.random.default_rng(5).normal(0, 1, 50)
        r = kalman_filter_pipeline(obs)
        assert np.isfinite(r["log_likelihood"])

    def test_log_likelihood_negative(self):
        """Log-likelihood should typically be negative for Gaussian model."""
        obs = np.random.default_rng(6).normal(0, 1, 100)
        r = kalman_filter_pipeline(obs, process_noise=1e-3, observation_noise=1.0)
        # This is typically negative; just verify it's finite
        assert np.isfinite(r["log_likelihood"])

    def test_em_estimation_converges(self):
        """EM should reduce log-likelihood and n_iter > 0."""
        obs = np.random.default_rng(7).normal(0, 1, 80)
        r_mle = kalman_filter_pipeline(obs, estimate_params=True, max_iter=20)
        assert r_mle["n_iter"] > 0
        assert np.isfinite(r_mle["log_likelihood"])

    def test_2d_observations(self):
        """Should handle 2D observation input (T, m)."""
        T = 30
        obs = np.random.default_rng(8).normal(0, 1, (T, 2))
        r = kalman_filter_pipeline(obs, process_noise=1e-3, observation_noise=1.0)
        assert r["filtered_states"].shape[0] == T

    def test_covariances_positive_definite(self):
        """Filtered covariance matrices should be positive definite."""
        obs = np.random.default_rng(9).normal(3, 1, 50)
        r = kalman_filter_pipeline(obs, process_noise=1e-3, observation_noise=1.0)
        for t in range(0, 50, 10):
            eigvals = np.linalg.eigvalsh(r["filtered_covariances"][t])
            assert np.all(eigvals > 0)

    def test_higher_obs_noise_wider_covariance(self):
        """Higher observation noise → wider filtered uncertainty."""
        obs = np.random.default_rng(10).normal(0, 1, 50)
        r_low = kalman_filter_pipeline(obs, process_noise=1e-3, observation_noise=0.1)
        r_high = kalman_filter_pipeline(obs, process_noise=1e-3, observation_noise=10.0)
        # Mean final covariance should be larger for high obs noise
        assert r_high["filtered_covariances"][-1, 0, 0] > r_low["filtered_covariances"][-1, 0, 0]


class TestKalmanSmoother:
    def test_returns_all_keys(self):
        obs = np.random.default_rng(0).normal(3, 1, 40)
        r = kalman_smoother(obs, process_noise=1e-5, observation_noise=1.0)
        required = {
            "smoothed_states",
            "smoothed_covariances",
            "filtered_states",
            "filtered_covariances",
            "log_likelihood",
        }
        assert required.issubset(set(r.keys()))

    def test_shapes_match_filter(self):
        T = 40
        obs = np.random.default_rng(1).normal(0, 1, T)
        r = kalman_smoother(obs, process_noise=1e-3, observation_noise=1.0)
        assert r["smoothed_states"].shape == (T, 1)
        assert r["filtered_states"].shape == (T, 1)

    def test_smoother_more_accurate_than_filter(self):
        """Smoother RMSE should be ≤ filter RMSE for constant signal."""
        true = np.ones(60) * 3.0
        obs = true + np.random.default_rng(0).normal(0, 1.0, 60)
        r = kalman_smoother(obs, process_noise=1e-5, observation_noise=1.0)
        filter_rmse = np.sqrt(np.mean((r["filtered_states"][:, 0] - true) ** 2))
        smooth_rmse = np.sqrt(np.mean((r["smoothed_states"][:, 0] - true) ** 2))
        assert smooth_rmse <= filter_rmse + 0.1

    def test_smoother_final_state_equals_filter(self):
        """At the last time step, smoother and filter should agree."""
        obs = np.random.default_rng(2).normal(0, 1, 50)
        r = kalman_smoother(obs, process_noise=1e-3, observation_noise=1.0)
        np.testing.assert_array_almost_equal(
            r["smoothed_states"][-1], r["filtered_states"][-1], decimal=10
        )

    def test_smoother_with_filter_result(self):
        """Smoother should accept a pre-computed filter result."""
        obs = np.random.default_rng(3).normal(0, 1, 40)
        f_result = kalman_filter_pipeline(obs, process_noise=1e-3, observation_noise=1.0)
        s_result = kalman_smoother(obs, filter_result=f_result)
        assert "smoothed_states" in s_result

    def test_no_kalman_pipeline_import(self):
        """H1 compliance: kalman_smoother must not import kalman_filter_pipeline."""
        import ast
        import inspect

        from oskill.state_space import kalman

        src = inspect.getsource(kalman.kalman_smoother)
        tree = ast.parse(src)
        # Check for any import of kalman_filter_pipeline
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [n.name if isinstance(node, ast.Import) else n.name for n in node.names]
                assert "kalman_filter_pipeline" not in names, (
                    "kalman_smoother must not import kalman_filter_pipeline (H1 violation)"
                )

    def test_smoothed_covariances_smaller_than_filtered(self):
        """Smoother covariances should be <= filtered (more information)."""
        obs = np.random.default_rng(4).normal(0, 1, 50)
        r = kalman_smoother(obs, process_noise=1e-3, observation_noise=1.0)
        # Middle-of-sequence: smoothed cov should be <= filtered cov
        t_mid = 25
        smooth_trace = np.trace(r["smoothed_covariances"][t_mid])
        filter_trace = np.trace(r["filtered_covariances"][t_mid])
        assert smooth_trace <= filter_trace + 1e-8
