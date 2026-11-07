"""Tests for fama_french_5_factor_model."""

import numpy as np
import pandas as pd
import pytest

from oskill.factor.fama_french import fama_french_5_factor_model


def _make_ff5_data(rng: np.random.Generator, T: int = 120):
    """Generate synthetic FF5 factor returns and asset returns."""
    factor_data = {
        "MKT": rng.normal(0.005, 0.04, T),
        "SMB": rng.normal(0.001, 0.02, T),
        "HML": rng.normal(0.002, 0.02, T),
        "RMW": rng.normal(0.001, 0.015, T),
        "CMA": rng.normal(0.001, 0.015, T),
    }
    factor_returns = pd.DataFrame(factor_data)
    # Known betas: alpha=0.001, MKT=1.2, SMB=0.3, HML=0.1, RMW=0.2, CMA=-0.1
    alpha = 0.001
    betas = [1.2, 0.3, 0.1, 0.2, -0.1]
    X = factor_returns.values
    asset_ret = alpha + X @ betas + rng.normal(0, 0.005, T)
    return pd.Series(asset_ret), factor_returns, betas, alpha


class TestFamaFrench5Factor:
    """Tests for fama_french_5_factor_model."""

    def test_returns_required_keys(self):
        """Result must contain all required keys."""
        rng = np.random.default_rng(1)
        asset_ret, factor_returns, _, _ = _make_ff5_data(rng)
        result = fama_french_5_factor_model(asset_ret, factor_returns)
        for key in [
            "alpha",
            "betas",
            "beta_t_stats",
            "alpha_t_stat",
            "r_squared",
            "adjusted_r_squared",
            "residual_std",
            "n_obs",
        ]:
            assert key in result

    def test_known_betas_recovered(self):
        """With clean data, should recover approximately known betas."""
        rng = np.random.default_rng(42)
        asset_ret, factor_returns, true_betas, true_alpha = _make_ff5_data(rng, T=500)
        result = fama_french_5_factor_model(asset_ret, factor_returns)
        factors = ["MKT", "SMB", "HML", "RMW", "CMA"]
        for i, f in enumerate(factors):
            assert abs(result["betas"][f] - true_betas[i]) < 0.2, (
                f"Beta {f}: expected ~{true_betas[i]:.2f}, got {result['betas'][f]:.2f}"
            )
        assert abs(result["alpha"] - true_alpha) < 0.002

    def test_r_squared_range(self):
        """R-squared should be in [0, 1]."""
        rng = np.random.default_rng(3)
        asset_ret, factor_returns, _, _ = _make_ff5_data(rng)
        result = fama_french_5_factor_model(asset_ret, factor_returns)
        assert 0.0 <= result["r_squared"] <= 1.0

    def test_high_r_squared_with_clean_data(self):
        """Very clean factor model data should give high R-squared."""
        rng = np.random.default_rng(4)
        T = 200
        factor_data = {
            "MKT": rng.normal(0.005, 0.04, T),
            "SMB": rng.normal(0.001, 0.02, T),
            "HML": rng.normal(0.002, 0.02, T),
            "RMW": rng.normal(0.001, 0.015, T),
            "CMA": rng.normal(0.001, 0.015, T),
        }
        factor_returns = pd.DataFrame(factor_data)
        betas = [1.0, 0.5, 0.3, 0.2, -0.2]
        asset_ret = factor_returns.values @ betas + rng.normal(0, 0.001, T)
        result = fama_french_5_factor_model(pd.Series(asset_ret), factor_returns)
        assert result["r_squared"] > 0.95

    def test_n_obs_correct(self):
        """n_obs should match length of asset_returns."""
        rng = np.random.default_rng(5)
        T = 150
        asset_ret, factor_returns, _, _ = _make_ff5_data(rng, T=T)
        result = fama_french_5_factor_model(asset_ret, factor_returns)
        assert result["n_obs"] == T

    def test_betas_dict_has_all_factors(self):
        """betas dict should have an entry for each factor."""
        rng = np.random.default_rng(6)
        asset_ret, factor_returns, _, _ = _make_ff5_data(rng)
        result = fama_french_5_factor_model(asset_ret, factor_returns)
        for f in ["MKT", "SMB", "HML", "RMW", "CMA"]:
            assert f in result["betas"]

    def test_missing_factor_raises(self):
        """Missing required factor should raise ValueError."""
        rng = np.random.default_rng(7)
        asset_ret, factor_returns, _, _ = _make_ff5_data(rng)
        factor_returns_missing = factor_returns.drop(columns=["CMA"])
        with pytest.raises(ValueError, match="CMA"):
            fama_french_5_factor_model(asset_ret, factor_returns_missing)
