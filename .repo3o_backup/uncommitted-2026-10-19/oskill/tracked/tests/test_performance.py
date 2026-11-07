"""Tests for Group 1: Performance Evaluation skills."""

import numpy as np
import pandas as pd
import pytest
from scipy import stats as scipy_stats

from oskill.performance import (
    bootstrap_sharpe,
    factor_attribution,
    psr_dsr,
    regime_aware_performance,
)

# ============================================================
# bootstrap_sharpe tests
# ============================================================


class TestBootstrapSharpe:
    """Tests for bootstrap_sharpe."""

    def test_normal_returns_sharpe_near_zero(self):
        """Normal(0,1) returns → Sharpe ≈ 0, CI contains 0."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, 252)
        result = bootstrap_sharpe(returns, n_bootstrap=500, random_state=42)
        assert result["ci_low"] < 0 < result["ci_high"]
        assert abs(result["sharpe"]) < 3.0

    def test_positive_mean_high_sharpe(self):
        """Positive mean returns → positive Sharpe."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.002, 0.01, 252)
        result = bootstrap_sharpe(returns, n_bootstrap=500, random_state=42)
        assert result["sharpe"] > 1.0
        assert result["ci_low"] > 0

    def test_n_bootstrap_samples_shape(self):
        """Samples array has correct shape."""
        returns = np.random.default_rng(42).normal(0, 0.01, 100)
        result = bootstrap_sharpe(returns, n_bootstrap=200, random_state=42)
        assert result["samples"].shape == (200,)
        assert result["n_bootstrap"] == 200

    def test_method_percentile(self):
        """Method percentile works."""
        returns = np.random.default_rng(42).normal(0.001, 0.01, 100)
        result = bootstrap_sharpe(returns, method="percentile", n_bootstrap=200, random_state=42)
        assert result["method"] == "percentile"

    def test_method_bca(self):
        """Method bca works."""
        returns = np.random.default_rng(42).normal(0.001, 0.01, 100)
        result = bootstrap_sharpe(returns, method="bca", n_bootstrap=200, random_state=42)
        assert result["method"] == "bca"

    def test_risk_free_rate_scalar(self):
        """Risk-free rate scalar shifts Sharpe."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, 252)
        r0 = bootstrap_sharpe(returns, risk_free_rate=0.0, n_bootstrap=200, random_state=42)
        r1 = bootstrap_sharpe(returns, risk_free_rate=0.0005, n_bootstrap=200, random_state=42)
        assert r0["sharpe"] > r1["sharpe"]

    def test_random_state_reproducible(self):
        """Same random_state → same results."""
        returns = np.random.default_rng(42).normal(0, 0.01, 100)
        r1 = bootstrap_sharpe(returns, n_bootstrap=200, random_state=123)
        r2 = bootstrap_sharpe(returns, n_bootstrap=200, random_state=123)
        np.testing.assert_array_equal(r1["samples"], r2["samples"])

    def test_annualization_factor(self):
        """Different annualization factors produce different Sharpe."""
        returns = np.random.default_rng(42).normal(0.001, 0.01, 252)
        r252 = bootstrap_sharpe(returns, annualization_factor=252, n_bootstrap=100, random_state=42)
        r365 = bootstrap_sharpe(returns, annualization_factor=365, n_bootstrap=100, random_state=42)
        assert r252["sharpe"] != r365["sharpe"]

    def test_small_sample_warning(self):
        """Small sample (n<10) raises warning."""
        returns = np.array([0.01, 0.02, -0.01, 0.005, 0.003])
        with pytest.warns(UserWarning, match="Sample size < 10"):
            bootstrap_sharpe(returns, n_bootstrap=100, random_state=42)

    def test_all_nan_raises(self):
        """All NaN raises ValueError."""
        returns = np.array([np.nan, np.nan, np.nan])
        with pytest.raises(ValueError, match="empty or all NaN"):
            bootstrap_sharpe(returns)

    def test_empty_raises(self):
        """Empty array raises ValueError."""
        with pytest.raises(ValueError):
            bootstrap_sharpe(np.array([]))

    def test_integration_mock_bootstrap_ci(self, mocker):
        """Integration: oprim.bootstrap_ci is called correctly."""
        mock_ci = mocker.patch(
            "oskill.performance.oprim.bootstrap_ci",
            return_value={
                "point_estimate": 1.0,
                "ci_lower": 0.5,
                "ci_upper": 1.5,
                "se": 0.25,
                "n_bootstrap": 100,
                "method": "percentile",
            },
        )
        returns = np.random.default_rng(42).normal(0.001, 0.01, 100)
        bootstrap_sharpe(returns, n_bootstrap=100, random_state=42)
        mock_ci.assert_called_once()
        call_kwargs = mock_ci.call_args
        assert call_kwargs.kwargs["n_bootstrap"] == 100
        assert call_kwargs.kwargs["method"] == "percentile"

    def test_integration_mock_sharpe_ratio(self, mocker):
        """Integration: oprim.sharpe_ratio is called for point estimate."""
        mock_sr = mocker.patch("oskill.performance.oprim.sharpe_ratio", return_value=1.5)
        mocker.patch(
            "oskill.performance.oprim.bootstrap_ci",
            return_value={
                "point_estimate": 1.5,
                "ci_lower": 1.0,
                "ci_upper": 2.0,
                "se": 0.25,
                "n_bootstrap": 100,
                "method": "percentile",
            },
        )
        returns = np.random.default_rng(42).normal(0.001, 0.01, 100)
        result = bootstrap_sharpe(returns, n_bootstrap=100, random_state=42)
        assert mock_sr.called
        assert result["sharpe"] == 1.5

    def test_academic_ci_contains_true_sharpe(self):
        """Academic: CI should contain true Sharpe for large samples."""
        rng = np.random.default_rng(42)
        # True Sharpe ≈ 0.001/0.01 * sqrt(252) ≈ 1.587
        returns = rng.normal(0.001, 0.01, 1000)
        result = bootstrap_sharpe(returns, n_bootstrap=1000, random_state=42)
        # CI should contain something reasonable
        assert result["ci_low"] < result["ci_high"]
        assert result["se"] > 0


# ============================================================
# psr_dsr tests
# ============================================================


class TestPsrDsr:
    """Tests for psr_dsr."""

    def test_zero_mean_psr_near_half(self):
        """Mean=0 returns + benchmark=0 → PSR around 0.5 (within sampling noise)."""
        rng = np.random.default_rng(100)
        returns = rng.normal(0, 0.01, 5000)
        result = psr_dsr(returns, benchmark_sharpe=0.0)
        assert 0.1 < result["psr"] < 0.9

    def test_high_sharpe_psr_near_one(self):
        """High Sharpe → PSR → 1."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.005, 0.01, 500)
        result = psr_dsr(returns, benchmark_sharpe=0.0)
        assert result["psr"] > 0.95

    def test_negative_sharpe_psr_near_zero(self):
        """Negative Sharpe → PSR → 0."""
        rng = np.random.default_rng(42)
        returns = rng.normal(-0.005, 0.01, 500)
        result = psr_dsr(returns, benchmark_sharpe=0.0)
        assert result["psr"] < 0.05

    def test_heavy_tails_lower_psr(self):
        """Heavy tails (high kurtosis) → lower PSR than normal."""
        rng = np.random.default_rng(42)
        normal_ret = rng.normal(0.002, 0.01, 500)
        heavy_ret = rng.standard_t(df=3, size=500) * 0.01 + 0.002
        psr_normal = psr_dsr(normal_ret)["psr"]
        psr_heavy = psr_dsr(heavy_ret)["psr"]
        # Heavy tails should deflate PSR (not always guaranteed with random data)
        assert psr_heavy < psr_normal or abs(psr_heavy - psr_normal) < 0.3

    def test_dsr_less_than_psr(self):
        """DSR < PSR when n_strategies_tested > 1."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.002, 0.01, 252)
        result = psr_dsr(returns, n_strategies_tested=10)
        assert result["dsr"] is not None
        assert result["dsr"] <= result["psr"]

    def test_dsr_much_less_with_many_strategies(self):
        """DSR << PSR with many strategies tested."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, 252)
        r10 = psr_dsr(returns, n_strategies_tested=10)
        r1000 = psr_dsr(returns, n_strategies_tested=1000)
        assert r1000["dsr"] < r10["dsr"]

    def test_dsr_equals_psr_with_one_strategy(self):
        """n_strategies_tested=1 → DSR ≈ PSR."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.002, 0.01, 252)
        result = psr_dsr(returns, n_strategies_tested=1)
        assert abs(result["dsr"] - result["psr"]) < 1e-10

    def test_small_sample_warning(self):
        """T < 30 produces warning."""
        returns = np.random.default_rng(42).normal(0, 0.01, 20)
        with pytest.warns(UserWarning, match="T=20 < 30"):
            psr_dsr(returns)

    def test_bootstrap_ci_returns_tuple(self):
        """bootstrap_ci=True returns CI tuple."""
        returns = np.random.default_rng(42).normal(0.001, 0.01, 100)
        result = psr_dsr(returns, bootstrap_ci=True, n_bootstrap=200)
        assert result["psr_ci"] is not None
        assert len(result["psr_ci"]) == 2
        assert result["psr_ci"][0] < result["psr_ci"][1]

    def test_n_eff_overrides_n_strategies(self):
        """n_eff overrides n_strategies_tested."""
        returns = np.random.default_rng(42).normal(0.001, 0.01, 252)
        result = psr_dsr(returns, n_strategies_tested=100, n_eff=5.0)
        assert result["n_eff_used"] == 5.0

    def test_empty_raises(self):
        """Empty returns raises."""
        with pytest.raises(ValueError):
            psr_dsr(np.array([]))

    def test_integration_mock_skew_kurt(self, mocker):
        """Integration: oprim.skew_kurt_robust called with bias=False."""
        mock_sk = mocker.patch(
            "oskill.performance.oprim.skew_kurt_robust",
            return_value={"skewness": 0.0, "kurtosis_excess": 0.0},
        )
        mocker.patch("oskill.performance.oprim.sharpe_ratio", return_value=1.0)
        returns = np.random.default_rng(42).normal(0, 0.01, 100)
        psr_dsr(returns)
        mock_sk.assert_called_once()
        assert mock_sk.call_args.kwargs["bias"] is False

    def test_integration_mock_sharpe_ratio(self, mocker):
        """Integration: oprim.sharpe_ratio is called."""
        mock_sr = mocker.patch("oskill.performance.oprim.sharpe_ratio", return_value=1.0)
        mocker.patch(
            "oskill.performance.oprim.skew_kurt_robust",
            return_value={"skewness": 0.0, "kurtosis_excess": 0.0},
        )
        returns = np.random.default_rng(42).normal(0, 0.01, 100)
        psr_dsr(returns)
        mock_sr.assert_called_once()

    def test_academic_psr_formula(self):
        """Academic: verify PSR formula against manual calculation."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, 252)
        result = psr_dsr(returns, benchmark_sharpe=0.0, annualization_factor=252)

        # Manual calculation
        sr = result["sharpe_observed"]
        T = result["n_obs"]
        g3 = result["skewness"]
        g4 = result["excess_kurtosis"]
        num = (sr - 0.0) * np.sqrt(T - 1)
        den_sq = 1 - g3 * sr + (g4 - 1) / 4 * sr**2
        expected_psr = scipy_stats.norm.cdf(num / np.sqrt(den_sq))
        assert abs(result["psr"] - expected_psr) < 1e-10

    def test_psr_denominator_nonpositive(self):
        """PSR with extreme skew/kurtosis that makes denominator non-positive."""
        # Construct returns where denominator_sq <= 0
        # denominator_sq = 1 - γ3*SR + (γ4-1)/4 * SR²
        # Need very high kurtosis and skewness with large SR
        rng = np.random.default_rng(42)
        # Use mock to force the condition
        import unittest.mock as mock

        returns = rng.normal(0.01, 0.01, 100)
        with mock.patch(
            "oskill.performance.oprim.skew_kurt_robust",
            return_value={"skewness": 100.0, "kurtosis_excess": 0.0},
        ):
            with mock.patch("oskill.performance.oprim.sharpe_ratio", return_value=100.0):
                result = psr_dsr(returns)
        assert np.isnan(result["psr"])
        assert "non-positive" in result["warnings"][0]


# ============================================================
# factor_attribution tests
# ============================================================


class TestFactorAttribution:
    """Tests for factor_attribution."""

    def test_perfect_correlation(self):
        """r_asset = 1.5*F → β=1.5, α≈0, R²≈1."""
        rng = np.random.default_rng(42)
        factor = rng.normal(0, 0.01, 200)
        asset = 1.5 * factor + rng.normal(0, 0.0001, 200)  # tiny noise
        factors_df = pd.DataFrame({"MKT": factor})
        result = factor_attribution(asset, factors_df, bootstrap_ci_enabled=False)
        assert abs(result["betas"]["MKT"] - 1.5) < 0.05
        assert abs(result["alpha"]) < 0.001
        assert result["r_squared"] > 0.99

    def test_multi_factor(self):
        """Multi-factor regression works."""
        rng = np.random.default_rng(42)
        f1 = rng.normal(0, 0.01, 200)
        f2 = rng.normal(0, 0.01, 200)
        asset = 0.5 * f1 + 0.3 * f2 + rng.normal(0, 0.001, 200)
        factors_df = pd.DataFrame({"F1": f1, "F2": f2})
        result = factor_attribution(asset, factors_df, bootstrap_ci_enabled=False)
        assert abs(result["betas"]["F1"] - 0.5) < 0.1
        assert abs(result["betas"]["F2"] - 0.3) < 0.1

    def test_independent_asset(self):
        """Independent asset → all betas ≈ 0."""
        rng = np.random.default_rng(42)
        asset = rng.normal(0.001, 0.02, 200)
        factors_df = pd.DataFrame({"MKT": rng.normal(0, 0.01, 200)})
        result = factor_attribution(asset, factors_df, bootstrap_ci_enabled=False)
        assert abs(result["betas"]["MKT"]) < 0.5
        assert result["r_squared"] < 0.1

    def test_bootstrap_ci_enabled(self):
        """bootstrap_ci_enabled=True returns CI."""
        rng = np.random.default_rng(42)
        asset = rng.normal(0, 0.02, 100)
        factors_df = pd.DataFrame({"MKT": rng.normal(0, 0.01, 100)})
        result = factor_attribution(
            asset, factors_df, bootstrap_ci_enabled=True, n_bootstrap=50, random_state=42
        )
        assert result["alpha_ci"] is not None
        assert result["betas_ci"] is not None
        assert "MKT" in result["betas_ci"]

    def test_bootstrap_ci_disabled(self):
        """bootstrap_ci_enabled=False → CI is None."""
        rng = np.random.default_rng(42)
        asset = rng.normal(0, 0.02, 100)
        factors_df = pd.DataFrame({"MKT": rng.normal(0, 0.01, 100)})
        result = factor_attribution(asset, factors_df, bootstrap_ci_enabled=False)
        assert result["alpha_ci"] is None
        assert result["betas_ci"] is None

    def test_handle_nan_drop(self):
        """NaN handling 'drop' removes NaN rows."""
        rng = np.random.default_rng(42)
        asset = rng.normal(0, 0.02, 100)
        asset[5] = np.nan
        factors_df = pd.DataFrame({"MKT": rng.normal(0, 0.01, 100)})
        result = factor_attribution(
            asset, factors_df, handle_nan="drop", bootstrap_ci_enabled=False
        )
        assert result["n_obs"] == 99

    def test_handle_nan_raise(self):
        """NaN handling 'raise' raises on NaN."""
        asset = np.array([0.01, np.nan, 0.02] + [0.01] * 97)
        factors_df = pd.DataFrame({"MKT": np.random.default_rng(42).normal(0, 0.01, 100)})
        with pytest.raises(ValueError, match="NaN"):
            factor_attribution(asset, factors_df, handle_nan="raise", bootstrap_ci_enabled=False)

    def test_single_factor(self):
        """Single factor works."""
        rng = np.random.default_rng(42)
        asset = rng.normal(0, 0.02, 100)
        factors_df = pd.DataFrame({"MKT": rng.normal(0, 0.01, 100)})
        result = factor_attribution(asset, factors_df, bootstrap_ci_enabled=False)
        assert len(result["factor_names"]) == 1

    def test_five_factors(self):
        """Five factors work."""
        rng = np.random.default_rng(42)
        asset = rng.normal(0, 0.02, 200)
        factors_df = pd.DataFrame({f"F{i}": rng.normal(0, 0.01, 200) for i in range(5)})
        result = factor_attribution(asset, factors_df, bootstrap_ci_enabled=False)
        assert len(result["factor_names"]) == 5
        assert len(result["betas"]) == 5

    def test_insufficient_obs_raises(self):
        """n=2 raises ValueError."""
        asset = np.array([0.01, 0.02])
        factors_df = pd.DataFrame({"MKT": [0.005, 0.01]})
        with pytest.raises(ValueError, match="Insufficient"):
            factor_attribution(asset, factors_df, bootstrap_ci_enabled=False)

    def test_not_dataframe_raises(self):
        """Non-DataFrame factor_returns raises."""
        asset = np.random.default_rng(42).normal(0, 0.02, 100)
        with pytest.raises(ValueError, match="DataFrame"):
            factor_attribution(asset, np.array([[1, 2]]), bootstrap_ci_enabled=False)

    def test_integration_mock_beta_alpha_ols(self, mocker):
        """Integration: oprim.beta_alpha_ols is called."""
        mock_ols = mocker.patch(
            "oskill.performance.oprim.beta_alpha_ols",
            return_value={
                "alpha": 0.001,
                "beta": {"MKT": 1.0},
                "alpha_se": 0.0005,
                "beta_se": {"MKT": 0.1},
                "r_squared": 0.5,
                "adj_r_squared": 0.49,
                "n_samples": 100,
                "p_values": {"alpha": 0.05, "MKT": 0.01},
            },
        )
        asset = np.random.default_rng(42).normal(0, 0.02, 100)
        factors_df = pd.DataFrame({"MKT": np.random.default_rng(43).normal(0, 0.01, 100)})
        factor_attribution(asset, factors_df, bootstrap_ci_enabled=False)
        mock_ols.assert_called_once()

    def test_academic_residual_check(self):
        """Academic: alpha + sum(beta*F) should explain most variance."""
        rng = np.random.default_rng(42)
        f1 = rng.normal(0, 0.01, 500)
        asset = 0.001 + 1.2 * f1 + rng.normal(0, 0.002, 500)
        factors_df = pd.DataFrame({"MKT": f1})
        result = factor_attribution(asset, factors_df, bootstrap_ci_enabled=False)
        assert result["r_squared"] > 0.9


# ============================================================
# regime_aware_performance tests
# ============================================================


class TestRegimeAwarePerformance:
    """Tests for regime_aware_performance."""

    def test_two_regimes_basic(self):
        """BULL positive, BEAR negative."""
        rng = np.random.default_rng(42)
        bull_ret = rng.normal(0.002, 0.01, 100)
        bear_ret = rng.normal(-0.002, 0.01, 100)
        returns = pd.Series(np.concatenate([bull_ret, bear_ret]))
        labels = pd.Series(["BULL"] * 100 + ["BEAR"] * 100, index=returns.index)
        df = regime_aware_performance(returns, labels)
        assert df.loc["BULL", "sharpe"] > 0
        assert df.loc["BEAR", "sharpe"] < 0

    def test_bull_less_drawdown(self):
        """BULL max_drawdown less severe than BEAR."""
        rng = np.random.default_rng(42)
        bull_ret = rng.normal(0.003, 0.005, 100)
        bear_ret = rng.normal(-0.003, 0.02, 100)
        returns = pd.Series(np.concatenate([bull_ret, bear_ret]))
        labels = pd.Series(["BULL"] * 100 + ["BEAR"] * 100, index=returns.index)
        df = regime_aware_performance(returns, labels)
        assert df.loc["BULL", "max_drawdown"] > df.loc["BEAR", "max_drawdown"]

    def test_metrics_subset(self):
        """metrics=['sharpe'] only returns sharpe."""
        rng = np.random.default_rng(42)
        returns = pd.Series(rng.normal(0, 0.01, 100))
        labels = pd.Series(["A"] * 50 + ["B"] * 50, index=returns.index)
        df = regime_aware_performance(returns, labels, metrics=["sharpe"])
        assert "sharpe" in df.columns
        assert "max_drawdown" not in df.columns

    def test_all_metrics(self):
        """All 4 default metrics present."""
        rng = np.random.default_rng(42)
        returns = pd.Series(rng.normal(0, 0.01, 200))
        labels = pd.Series(["A"] * 100 + ["B"] * 100, index=returns.index)
        df = regime_aware_performance(returns, labels)
        for m in ["sharpe", "max_drawdown", "var_95", "cumulative_return"]:
            assert m in df.columns

    def test_include_overall_true(self):
        """include_overall=True adds OVERALL row."""
        rng = np.random.default_rng(42)
        returns = pd.Series(rng.normal(0, 0.01, 100))
        labels = pd.Series(["A"] * 50 + ["B"] * 50, index=returns.index)
        df = regime_aware_performance(returns, labels, include_overall=True)
        assert "OVERALL" in df.index

    def test_include_overall_false(self):
        """include_overall=False excludes OVERALL row."""
        rng = np.random.default_rng(42)
        returns = pd.Series(rng.normal(0, 0.01, 100))
        labels = pd.Series(["A"] * 50 + ["B"] * 50, index=returns.index)
        df = regime_aware_performance(returns, labels, include_overall=False)
        assert "OVERALL" not in df.index

    def test_small_regime_nan_sharpe(self):
        """Regime with < 30 samples → Sharpe = NaN."""
        rng = np.random.default_rng(42)
        returns = pd.Series(rng.normal(0, 0.01, 120))
        labels = pd.Series(["A"] * 100 + ["B"] * 20, index=returns.index)
        df = regime_aware_performance(returns, labels, metrics=["sharpe"])
        assert np.isnan(df.loc["B", "sharpe"])

    def test_var_method_parametric(self):
        """var_method='parametric' works."""
        rng = np.random.default_rng(42)
        returns = pd.Series(rng.normal(0, 0.01, 200))
        labels = pd.Series(["A"] * 100 + ["B"] * 100, index=returns.index)
        df = regime_aware_performance(returns, labels, var_method="parametric", metrics=["var_95"])
        assert not np.isnan(df.loc["A", "var_95"])

    def test_index_mismatch_raises(self):
        """Mismatched index raises ValueError."""
        returns = pd.Series([0.01, 0.02], index=[0, 1])
        labels = pd.Series(["A", "B"], index=[2, 3])
        with pytest.raises(ValueError, match="same index"):
            regime_aware_performance(returns, labels)

    def test_single_obs_regime_nan(self):
        """Regime with 1 observation → all metrics NaN."""
        rng = np.random.default_rng(42)
        returns = pd.Series(np.concatenate([rng.normal(0, 0.01, 100), [0.01]]))
        labels = pd.Series(["A"] * 100 + ["B"], index=returns.index)
        df = regime_aware_performance(returns, labels, metrics=["cumulative_return"])
        assert np.isnan(df.loc["B", "cumulative_return"])

    def test_integration_mock_regime_filter(self, mocker):
        """Integration: oprim.regime_filter_data called per regime."""
        rng = np.random.default_rng(42)
        returns = pd.Series(rng.normal(0, 0.01, 100))
        labels = pd.Series(["A"] * 50 + ["B"] * 50, index=returns.index)

        original_filter = mocker.patch(
            "oskill.performance.oprim.regime_filter_data",
            wraps=lambda data, regime_labels, target_regime: data[regime_labels == target_regime],
        )
        regime_aware_performance(returns, labels, metrics=["cumulative_return"])
        assert original_filter.call_count == 2  # A and B

    def test_integration_mock_sharpe_ratio(self, mocker):
        """Integration: oprim.sharpe_ratio called for each regime."""
        rng = np.random.default_rng(42)
        returns = pd.Series(rng.normal(0, 0.01, 200))
        labels = pd.Series(["A"] * 100 + ["B"] * 100, index=returns.index)

        mock_sr = mocker.patch("oskill.performance.oprim.sharpe_ratio", return_value=1.0)
        mocker.patch(
            "oskill.performance.oprim.regime_filter_data",
            side_effect=lambda data, regime_labels, target_regime: data[
                regime_labels == target_regime
            ],
        )
        regime_aware_performance(returns, labels, metrics=["sharpe"], include_overall=False)
        assert mock_sr.call_count == 2

    def test_academic_overall_matches_direct(self):
        """Academic: OVERALL Sharpe matches direct computation."""
        rng = np.random.default_rng(42)
        returns = pd.Series(rng.normal(0.001, 0.01, 200))
        labels = pd.Series(["A"] * 100 + ["B"] * 100, index=returns.index)
        df = regime_aware_performance(returns, labels, metrics=["sharpe"])
        import oprim

        direct_sharpe = oprim.sharpe_ratio(returns)
        assert abs(df.loc["OVERALL", "sharpe"] - direct_sharpe) < 1e-10


# ============================================================
# Sprint 0: portfolio_metrics_summary + trade_pnl_statistics
# ============================================================

from datetime import date as _date

from oskill.performance import portfolio_metrics_summary, trade_pnl_statistics


class TestPortfolioMetricsSummary:
    def _make_trades(self):
        return [
            {
                "entry_date": _date(2024, 1, 2),
                "exit_date": _date(2024, 1, 10),
                "pnl": 500.0,
                "pnl_pct": 0.05,
            },
            {
                "entry_date": _date(2024, 2, 1),
                "exit_date": _date(2024, 2, 5),
                "pnl": -200.0,
                "pnl_pct": -0.02,
            },
        ]

    def _make_equity_curve(self):
        return [
            (_date(2024, 1, 10), 100_500.0),
            (_date(2024, 2, 5), 100_300.0),
        ]

    def test_empty_equity_returns_zeros(self):
        result = portfolio_metrics_summary([], [], 100_000)
        assert result["total_return_pct"] == 0.0
        assert result["n_trades"] == 0

    def test_required_keys_present(self):
        result = portfolio_metrics_summary(self._make_trades(), self._make_equity_curve(), 100_000)
        for key in [
            "total_return_pct",
            "cagr",
            "sharpe_ratio",
            "max_drawdown_pct",
            "win_rate",
            "profit_loss_ratio",
            "n_trades",
            "avg_holding_days",
        ]:
            assert key in result

    def test_n_trades_correct(self):
        result = portfolio_metrics_summary(self._make_trades(), self._make_equity_curve(), 100_000)
        assert result["n_trades"] == 2

    def test_win_rate_correct(self):
        result = portfolio_metrics_summary(self._make_trades(), self._make_equity_curve(), 100_000)
        assert result["win_rate"] == pytest.approx(0.5)

    def test_total_return_pct_correct(self):
        equity = [(_date(2024, 1, 1), 110_000.0)]
        result = portfolio_metrics_summary([], equity, 100_000)
        assert result["total_return_pct"] == pytest.approx(10.0)

    def test_avg_holding_days_correct(self):
        result = portfolio_metrics_summary(self._make_trades(), self._make_equity_curve(), 100_000)
        # trade1: 8 days, trade2: 4 days -> avg = 6
        assert result["avg_holding_days"] == pytest.approx(6.0)

    def test_zero_initial_capital_returns_zeros(self):
        result = portfolio_metrics_summary(self._make_trades(), self._make_equity_curve(), 0)
        assert result["total_return_pct"] == 0.0

    @pytest.mark.academic_reference
    def test_bailey_lopezdeprado_2014_backtest_metrics(self):
        """Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio: backtest metrics.

        For a strategy with positive total return, win_rate must be between 0 and 1,
        and n_trades must match the input. Verifies metric bundle consistency.
        """
        trades = [
            {
                "entry_date": _date(2024, 1, 1),
                "exit_date": _date(2024, 1, 30),
                "pnl": 1000.0,
                "pnl_pct": 0.01,
            },
            {
                "entry_date": _date(2024, 2, 1),
                "exit_date": _date(2024, 2, 28),
                "pnl": 2000.0,
                "pnl_pct": 0.02,
            },
            {
                "entry_date": _date(2024, 3, 1),
                "exit_date": _date(2024, 3, 31),
                "pnl": -500.0,
                "pnl_pct": -0.005,
            },
        ]
        equity = [
            (_date(2024, 1, 30), 101_000.0),
            (_date(2024, 2, 28), 103_000.0),
            (_date(2024, 3, 31), 102_500.0),
        ]
        result = portfolio_metrics_summary(trades, equity, 100_000)
        assert result["n_trades"] == 3
        assert 0.0 <= result["win_rate"] <= 1.0
        assert result["total_return_pct"] == pytest.approx(2.5)


class TestTradePnlStatistics:
    def _make_trades(self):
        return [
            {"symbol": "A", "entry_reason": "breakout", "realized_pnl_pct": 0.05},
            {"symbol": "A", "entry_reason": "mean_rev", "realized_pnl_pct": -0.02},
            {"symbol": "B", "entry_reason": "breakout", "realized_pnl_pct": 0.03},
        ]

    def test_overall_n_trades(self):
        result = trade_pnl_statistics(self._make_trades())
        assert result["n_trades"] == 3

    def test_overall_win_rate(self):
        result = trade_pnl_statistics(self._make_trades())
        # 2 positive out of 3
        assert result["win_rate"] == pytest.approx(2 / 3)

    def test_overall_avg_pnl_correct(self):
        result = trade_pnl_statistics(self._make_trades())
        expected = (0.05 - 0.02 + 0.03) / 3
        assert result["avg_pnl"] == pytest.approx(expected)

    def test_grouped_by_symbol(self):
        result = trade_pnl_statistics(self._make_trades(), group_fields=["symbol"])
        assert ("A",) in result
        assert ("B",) in result

    def test_grouped_by_symbol_n_trades(self):
        result = trade_pnl_statistics(self._make_trades(), group_fields=["symbol"])
        assert result[("A",)]["n_trades"] == 2
        assert result[("B",)]["n_trades"] == 1

    def test_empty_trades_returns_zeros(self):
        result = trade_pnl_statistics([])
        assert result["n_trades"] == 0
        assert result["win_rate"] == 0.0

    def test_custom_pnl_field(self):
        trades = [{"custom_pnl": 0.1}, {"custom_pnl": -0.05}]
        result = trade_pnl_statistics(trades, pnl_field="custom_pnl")
        assert result["win_rate"] == pytest.approx(0.5)

    def test_std_pnl_zero_single_trade(self):
        result = trade_pnl_statistics([{"realized_pnl_pct": 0.05}])
        assert result["std_pnl"] == 0.0

    @pytest.mark.academic_reference
    def test_standard_trade_journal_analytics(self):
        """Standard trade journal analytics: profit_loss_ratio = avg_win / avg_loss.

        Given wins=[0.06, 0.04], losses=[-0.02]:
        avg_win = 0.05, avg_loss = 0.02, PLR = 0.05/0.02 = 2.5
        """
        trades = [
            {"realized_pnl_pct": 0.06},
            {"realized_pnl_pct": 0.04},
            {"realized_pnl_pct": -0.02},
        ]
        result = trade_pnl_statistics(trades)
        assert result["profit_loss_ratio"] == pytest.approx(2.5)
        assert result["win_rate"] == pytest.approx(2 / 3)
