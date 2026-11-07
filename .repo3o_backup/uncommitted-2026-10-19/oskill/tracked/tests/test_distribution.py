"""Tests for Group 3: Distribution & Anomaly skills."""

import numpy as np
import pandas as pd
import pytest

from oskill.distribution import (
    bootstrap_distribution,
    detect_outliers_robust,
    distribution_shift_test,
)

# ============================================================
# distribution_shift_test tests
# ============================================================


class TestDistributionShiftTest:
    """Tests for distribution_shift_test."""

    def test_same_distribution_no_shift(self):
        """Two N(0,1) samples → no shift detected."""
        rng = np.random.default_rng(42)
        a = rng.normal(0, 1, 500)
        b = rng.normal(0, 1, 500)
        result = distribution_shift_test(a, b)
        assert result["shift_detected"] is False

    def test_different_distribution_shift(self):
        """N(0,1) vs N(5,1) → shift detected."""
        rng = np.random.default_rng(42)
        a = rng.normal(0, 1, 200)
        b = rng.normal(5, 1, 200)
        result = distribution_shift_test(a, b)
        assert result["shift_detected"] is True

    def test_subtle_shift_large_sample(self):
        """Subtle shift with large sample → detected."""
        rng = np.random.default_rng(42)
        a = rng.normal(0, 1, 2000)
        b = rng.normal(0.3, 1, 2000)
        result = distribution_shift_test(a, b)
        assert result["votes"]["ks"] is True  # KS should detect with large n

    def test_methods_ks_only(self):
        """methods=['ks'] only uses KS."""
        rng = np.random.default_rng(42)
        a = rng.normal(0, 1, 100)
        b = rng.normal(0, 1, 100)
        result = distribution_shift_test(a, b, methods=["ks"])
        assert "ks" in result["votes"]
        assert "wasserstein" not in result["votes"]

    def test_methods_subset(self):
        """methods=['ks', 'wasserstein'] uses two methods."""
        rng = np.random.default_rng(42)
        a = rng.normal(0, 1, 100)
        b = rng.normal(0, 1, 100)
        result = distribution_shift_test(a, b, methods=["ks", "wasserstein"])
        assert len(result["votes"]) == 2

    def test_voting_any(self):
        """voting='any': one detect → shift."""
        rng = np.random.default_rng(42)
        a = rng.normal(0, 1, 200)
        b = rng.normal(0.5, 1, 200)
        result = distribution_shift_test(a, b, voting="any")
        if any(result["votes"].values()):
            assert result["shift_detected"] is True

    def test_voting_all(self):
        """voting='all': all must detect."""
        rng = np.random.default_rng(42)
        a = rng.normal(0, 1, 100)
        b = rng.normal(0, 1, 100)
        result = distribution_shift_test(a, b, voting="all")
        if not all(result["votes"].values()):
            assert result["shift_detected"] is False

    def test_voting_majority(self):
        """voting='majority': majority must detect."""
        rng = np.random.default_rng(42)
        a = rng.normal(0, 1, 200)
        b = rng.normal(5, 1, 200)
        result = distribution_shift_test(a, b, voting="majority")
        assert result["shift_detected"] is True

    def test_compute_summary_true(self):
        """compute_summary=True returns summaries."""
        rng = np.random.default_rng(42)
        a = rng.normal(0, 1, 100)
        b = rng.normal(0, 1, 100)
        result = distribution_shift_test(a, b, compute_summary=True)
        assert result["sample_a_summary"] is not None
        assert result["sample_b_summary"] is not None

    def test_compute_summary_false(self):
        """compute_summary=False returns None summaries."""
        rng = np.random.default_rng(42)
        a = rng.normal(0, 1, 100)
        b = rng.normal(0, 1, 100)
        result = distribution_shift_test(a, b, compute_summary=False)
        assert result["sample_a_summary"] is None

    def test_small_sample_warning(self):
        """Sample < 20 warns."""
        a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        b = np.array([6.0, 7.0, 8.0, 9.0, 10.0])
        with pytest.warns(UserWarning, match="Sample size < 20"):
            distribution_shift_test(a, b)

    def test_wasserstein_threshold_ratio(self):
        """wasserstein_threshold_ratio controls detection sensitivity."""
        rng = np.random.default_rng(42)
        a = rng.normal(0, 1, 200)
        b = rng.normal(0.2, 1, 200)  # slight shift
        # Loose threshold → no detection
        r_loose = distribution_shift_test(
            a, b, methods=["wasserstein"], wasserstein_threshold_ratio=1.0
        )
        # Tight threshold → detection
        r_tight = distribution_shift_test(
            a, b, methods=["wasserstein"], wasserstein_threshold_ratio=0.01
        )
        assert r_loose["votes"]["wasserstein"] is False or not r_loose["votes"]["wasserstein"]
        assert r_tight["votes"]["wasserstein"] is True or r_tight["votes"]["wasserstein"]

    def test_empty_raises(self):
        """Empty sample raises."""
        with pytest.raises(ValueError):
            distribution_shift_test(np.array([]), np.array([1, 2, 3]))

    def test_integration_mock_ks(self, mocker):
        """Integration: oprim.kolmogorov_smirnov_test called for 'ks'."""
        mock_ks = mocker.patch(
            "oskill.distribution.oprim.kolmogorov_smirnov_test",
            return_value={"statistic": 0.1, "p_value": 0.5, "n_a": 100, "n_b": 100},
        )
        mocker.patch("oskill.distribution.oprim.distribution_summary", return_value={})
        a = np.random.default_rng(42).normal(0, 1, 100)
        b = np.random.default_rng(43).normal(0, 1, 100)
        distribution_shift_test(a, b, methods=["ks"])
        mock_ks.assert_called_once()

    def test_integration_mock_wasserstein(self, mocker):
        """Integration: oprim.wasserstein_distance called for 'wasserstein'."""
        mock_w = mocker.patch("oskill.distribution.oprim.wasserstein_distance", return_value=0.01)
        mocker.patch("oskill.distribution.oprim.distribution_summary", return_value={})
        a = np.random.default_rng(42).normal(0, 1, 100)
        b = np.random.default_rng(43).normal(0, 1, 100)
        distribution_shift_test(a, b, methods=["wasserstein"])
        mock_w.assert_called_once()

    def test_integration_mock_jsd(self, mocker):
        """Integration: oprim.symmetric_kl_divergence called for 'jsd'."""
        mock_jsd = mocker.patch(
            "oskill.distribution.oprim.symmetric_kl_divergence", return_value=0.01
        )
        mocker.patch("oskill.distribution.oprim.distribution_summary", return_value={})
        a = np.random.default_rng(42).normal(0, 1, 100)
        b = np.random.default_rng(43).normal(0, 1, 100)
        distribution_shift_test(a, b, methods=["jsd"])
        mock_jsd.assert_called_once()


# ============================================================
# detect_outliers_robust tests
# ============================================================


class TestDetectOutliersRobust:
    """Tests for detect_outliers_robust."""

    def test_obvious_outlier(self):
        """[1,2,3,4,5,100] → last is outlier."""
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 100.0])
        result = detect_outliers_robust(data)
        assert result["outlier_mask"][-1] is True or result["outlier_mask"][-1]

    def test_no_outliers(self):
        """Normal data → few/no outliers."""
        data = np.random.default_rng(42).normal(0, 1, 100)
        result = detect_outliers_robust(data)
        assert result["n_outliers"] < 10

    def test_custom_threshold(self):
        """Custom zscore threshold=2.0 is stricter."""
        rng = np.random.default_rng(42)
        data = rng.normal(0, 1, 200)
        r_default = detect_outliers_robust(data, methods=["zscore"])
        r_strict = detect_outliers_robust(data, methods=["zscore"], thresholds={"zscore": 2.0})
        assert r_strict["n_outliers"] >= r_default["n_outliers"]

    def test_voting_any(self):
        """voting='any': any method flags → outlier."""
        data = np.concatenate([np.zeros(50), [10.0]])
        result = detect_outliers_robust(data, voting="any")
        assert result["outlier_mask"][-1]

    def test_voting_all(self):
        """voting='all': all methods must flag."""
        data = np.concatenate([np.random.default_rng(42).normal(0, 1, 100), [5.0]])
        r_any = detect_outliers_robust(data, voting="any")
        r_all = detect_outliers_robust(data, voting="all")
        assert r_all["n_outliers"] <= r_any["n_outliers"]

    def test_voting_majority(self):
        """voting='majority' between any and all."""
        data = np.concatenate([np.random.default_rng(42).normal(0, 1, 100), [10.0]])
        r_any = detect_outliers_robust(data, voting="any")
        r_maj = detect_outliers_robust(data, voting="majority")
        r_all = detect_outliers_robust(data, voting="all")
        assert r_all["n_outliers"] <= r_maj["n_outliers"] <= r_any["n_outliers"]

    def test_methods_zscore_only(self):
        """methods=['zscore'] only uses zscore."""
        data = np.random.default_rng(42).normal(0, 1, 50)
        result = detect_outliers_robust(data, methods=["zscore"])
        assert "zscore" in result["votes"]
        assert "iqr" not in result["votes"]

    def test_2d_data(self):
        """2D data with mahalanobis."""
        rng = np.random.default_rng(42)
        data = np.column_stack([rng.normal(0, 1, 100), rng.normal(0, 1, 100)])
        data = np.vstack([data, [10, 10]])  # outlier
        result = detect_outliers_robust(data, methods=["zscore", "iqr", "mahalanobis"])
        assert result["outlier_mask"][-1]

    def test_all_nan_raises(self):
        """All NaN raises."""
        with pytest.raises(ValueError, match="all NaN"):
            detect_outliers_robust(np.array([np.nan, np.nan]))

    def test_empty_raises(self):
        """Empty raises."""
        with pytest.raises(ValueError, match="empty"):
            detect_outliers_robust(np.array([]))

    def test_single_element_raises(self):
        """Single element raises."""
        with pytest.raises(ValueError, match="at least 2"):
            detect_outliers_robust(np.array([1.0]))

    def test_integration_mock_zscore(self, mocker):
        """Integration: oprim.zscore_normalize called for zscore method."""
        mock_zs = mocker.patch(
            "oskill.distribution.oprim.zscore_normalize",
            return_value=pd.DataFrame(np.zeros((10, 1))),
        )
        mocker.patch(
            "oskill.distribution.oprim.distribution_summary",
            return_value={"q_0.25": -0.5, "q_0.75": 0.5},
        )
        data = np.random.default_rng(42).normal(0, 1, 10)
        detect_outliers_robust(data, methods=["zscore"])
        mock_zs.assert_called_once()

    def test_integration_mock_distribution_summary(self, mocker):
        """Integration: oprim.distribution_summary called for IQR."""
        mock_ds = mocker.patch(
            "oskill.distribution.oprim.distribution_summary",
            return_value={"q_0.25": -0.67, "q_0.75": 0.67},
        )
        mocker.patch(
            "oskill.distribution.oprim.zscore_normalize",
            return_value=pd.DataFrame(np.zeros((10, 1))),
        )
        data = np.random.default_rng(42).normal(0, 1, 10)
        detect_outliers_robust(data, methods=["iqr"])
        mock_ds.assert_called()

    def test_academic_zscore_matches_manual(self):
        """Academic: zscore method matches manual z-score computation."""
        rng = np.random.default_rng(42)
        data = np.concatenate([rng.normal(0, 1, 100), [5.0]])
        result = detect_outliers_robust(data, methods=["zscore"], thresholds={"zscore": 3.0})
        # Manual: z = |5 - mean| / std
        mean = np.mean(data)
        std = np.std(data, ddof=1)
        z_last = abs(5.0 - mean) / std
        assert (z_last > 3.0) == result["outlier_mask"][-1]


# ============================================================
# bootstrap_distribution tests
# ============================================================


class TestBootstrapDistribution:
    """Tests for bootstrap_distribution."""

    def test_mean_statistic(self):
        """statistic=np.mean, normal data: point_estimate ≈ true mean."""
        rng = np.random.default_rng(42)
        data = rng.normal(5, 1, 200)
        result = bootstrap_distribution(data, np.mean, n_bootstrap=500, random_state=42)
        assert abs(result["point_estimate"] - 5.0) < 0.5

    def test_median_statistic(self):
        """statistic=np.median works."""
        rng = np.random.default_rng(42)
        data = rng.normal(3, 1, 200)
        result = bootstrap_distribution(data, np.median, n_bootstrap=500, random_state=42)
        assert abs(result["point_estimate"] - 3.0) < 0.5

    def test_std_statistic(self):
        """statistic=np.std works."""
        rng = np.random.default_rng(42)
        data = rng.normal(0, 2, 200)
        result = bootstrap_distribution(data, np.std, n_bootstrap=500, random_state=42)
        assert abs(result["point_estimate"] - 2.0) < 0.5

    def test_include_density_true(self):
        """include_density=True returns density dict."""
        data = np.random.default_rng(42).normal(0, 1, 100)
        result = bootstrap_distribution(
            data, np.mean, n_bootstrap=200, include_density=True, random_state=42
        )
        assert result["density"] is not None
        assert "x" in result["density"]
        assert "density" in result["density"]

    def test_include_density_false(self):
        """include_density=False returns None."""
        data = np.random.default_rng(42).normal(0, 1, 100)
        result = bootstrap_distribution(
            data, np.mean, n_bootstrap=200, include_density=False, random_state=42
        )
        assert result["density"] is None

    def test_method_percentile(self):
        """method='percentile' works."""
        data = np.random.default_rng(42).normal(0, 1, 100)
        result = bootstrap_distribution(
            data, np.mean, method="percentile", n_bootstrap=200, random_state=42
        )
        assert result["method"] == "percentile"

    def test_method_bca(self):
        """method='bca' works."""
        data = np.random.default_rng(42).normal(0, 1, 100)
        result = bootstrap_distribution(
            data, np.mean, method="bca", n_bootstrap=200, random_state=42
        )
        assert result["method"] == "bca"

    def test_random_state_reproducible(self):
        """Same random_state → same samples."""
        data = np.random.default_rng(42).normal(0, 1, 100)
        r1 = bootstrap_distribution(data, np.mean, n_bootstrap=200, random_state=123)
        r2 = bootstrap_distribution(data, np.mean, n_bootstrap=200, random_state=123)
        np.testing.assert_array_equal(r1["samples"], r2["samples"])

    def test_samples_shape(self):
        """samples shape == (n_bootstrap,)."""
        data = np.random.default_rng(42).normal(0, 1, 100)
        result = bootstrap_distribution(data, np.mean, n_bootstrap=300, random_state=42)
        assert result["samples"].shape == (300,)

    def test_summary_present(self):
        """summary dict is present and has expected keys."""
        data = np.random.default_rng(42).normal(0, 1, 100)
        result = bootstrap_distribution(data, np.mean, n_bootstrap=200, random_state=42)
        assert "mean" in result["summary"]
        assert "std" in result["summary"]

    def test_empty_raises(self):
        """Empty data raises."""
        with pytest.raises(ValueError):
            bootstrap_distribution(np.array([]), np.mean)

    def test_integration_mock_bootstrap_ci(self, mocker):
        """Integration: oprim.bootstrap_ci called for bca method."""
        mock_ci = mocker.patch(
            "oskill.distribution.oprim.bootstrap_ci",
            return_value={
                "point_estimate": 0.0,
                "ci_lower": -0.5,
                "ci_upper": 0.5,
                "se": 0.1,
                "n_bootstrap": 200,
                "method": "bca",
            },
        )
        mocker.patch("oskill.distribution.oprim.distribution_summary", return_value={"mean": 0})
        data = np.random.default_rng(42).normal(0, 1, 100)
        bootstrap_distribution(data, np.mean, n_bootstrap=200, method="bca", random_state=42)
        mock_ci.assert_called_once()

    def test_integration_mock_distribution_summary(self, mocker):
        """Integration: oprim.distribution_summary called on samples."""
        mocker.patch(
            "oskill.distribution.oprim.bootstrap_ci",
            return_value={
                "point_estimate": 0.0,
                "ci_lower": -0.5,
                "ci_upper": 0.5,
                "se": 0.1,
                "n_bootstrap": 200,
                "method": "percentile",
            },
        )
        mock_ds = mocker.patch(
            "oskill.distribution.oprim.distribution_summary", return_value={"mean": 0}
        )
        data = np.random.default_rng(42).normal(0, 1, 100)
        bootstrap_distribution(data, np.mean, n_bootstrap=200, random_state=42)
        mock_ds.assert_called_once()

    def test_integration_mock_kde_density(self, mocker):
        """Integration: oprim.kde_density called when include_density=True."""
        mocker.patch(
            "oskill.distribution.oprim.bootstrap_ci",
            return_value={
                "point_estimate": 0.0,
                "ci_lower": -0.5,
                "ci_upper": 0.5,
                "se": 0.1,
                "n_bootstrap": 200,
                "method": "percentile",
            },
        )
        mocker.patch("oskill.distribution.oprim.distribution_summary", return_value={"mean": 0})
        mock_kde = mocker.patch(
            "oskill.distribution.oprim.kde_density",
            return_value={"x": np.zeros(10), "density": np.ones(10)},
        )
        data = np.random.default_rng(42).normal(0, 1, 100)
        bootstrap_distribution(
            data, np.mean, n_bootstrap=200, include_density=True, random_state=42
        )
        mock_kde.assert_called_once()

    def test_bootstrap_distribution_percentile_method(self):
        """method='percentile' computes CI directly from bootstrap samples."""
        rng = np.random.default_rng(5)
        data = rng.normal(3.0, 1.0, 200)
        result = bootstrap_distribution(
            data, np.mean, method="percentile", n_bootstrap=500, random_state=5
        )
        assert result["method"] == "percentile"
        assert result["ci_low"] < result["ci_high"]
        # CI should contain the true mean ≈ 3.0
        assert result["ci_low"] < 3.0 < result["ci_high"]

    def test_bootstrap_distribution_basic_method(self):
        """method='basic' (reflection CI) computes ci without crashing."""
        rng = np.random.default_rng(6)
        data = rng.normal(2.0, 1.0, 200)
        result = bootstrap_distribution(
            data, np.mean, method="basic", n_bootstrap=500, random_state=6
        )
        assert result["method"] == "basic"
        assert result["ci_low"] < result["ci_high"]

    def test_academic_samples_mean_near_point_estimate(self):
        """Academic: mean of bootstrap samples ≈ point_estimate."""
        rng = np.random.default_rng(42)
        data = rng.normal(5, 1, 500)
        result = bootstrap_distribution(data, np.mean, n_bootstrap=2000, random_state=42)
        assert abs(np.mean(result["samples"]) - result["point_estimate"]) < 0.1
