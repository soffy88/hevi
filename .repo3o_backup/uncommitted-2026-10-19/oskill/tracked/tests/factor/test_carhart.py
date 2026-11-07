"""Tests for carhart_4_factor_model."""

import numpy as np
import pandas as pd
import pytest

from oskill.factor.carhart import carhart_4_factor_model


def _make_carhart_data(rng: np.random.Generator, T: int = 120):
    """Generate synthetic Carhart 4-factor data."""
    factor_data = {
        "MKT": rng.normal(0.006, 0.04, T),
        "SMB": rng.normal(0.001, 0.02, T),
        "HML": rng.normal(0.002, 0.02, T),
        "MOM": rng.normal(0.003, 0.025, T),
    }
    factor_returns = pd.DataFrame(factor_data)
    # Known: alpha=0.0005, MKT=1.1, SMB=0.4, HML=0.2, MOM=0.3
    alpha = 0.0005
    betas = [1.1, 0.4, 0.2, 0.3]
    X = factor_returns.values
    asset_ret = alpha + X @ betas + rng.normal(0, 0.005, T)
    return pd.Series(asset_ret), factor_returns, betas, alpha


class TestCarhart4Factor:
    """Tests for carhart_4_factor_model."""

    def test_returns_required_keys(self):
        """Result must contain all required keys."""
        rng = np.random.default_rng(1)
        asset_ret, factor_returns, _, _ = _make_carhart_data(rng)
        result = carhart_4_factor_model(asset_ret, factor_returns)
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

    def test_betas_has_mom_factor(self):
        """Result betas should include MOM factor."""
        rng = np.random.default_rng(2)
        asset_ret, factor_returns, _, _ = _make_carhart_data(rng)
        result = carhart_4_factor_model(asset_ret, factor_returns)
        assert "MOM" in result["betas"]

    def test_known_betas_recovered(self):
        """With sufficient data, should recover approximately known betas."""
        rng = np.random.default_rng(42)
        asset_ret, factor_returns, true_betas, true_alpha = _make_carhart_data(rng, T=500)
        result = carhart_4_factor_model(asset_ret, factor_returns)
        factors = ["MKT", "SMB", "HML", "MOM"]
        for i, f in enumerate(factors):
            assert abs(result["betas"][f] - true_betas[i]) < 0.25

    def test_r_squared_range(self):
        """R-squared should be in [0, 1]."""
        rng = np.random.default_rng(3)
        asset_ret, factor_returns, _, _ = _make_carhart_data(rng)
        result = carhart_4_factor_model(asset_ret, factor_returns)
        assert 0.0 <= result["r_squared"] <= 1.0

    def test_n_obs_correct(self):
        """n_obs should match asset_returns length."""
        rng = np.random.default_rng(4)
        T = 120
        asset_ret, factor_returns, _, _ = _make_carhart_data(rng, T=T)
        result = carhart_4_factor_model(asset_ret, factor_returns)
        assert result["n_obs"] == T

    def test_4_betas_in_result(self):
        """Should have exactly 4 betas in result (MKT, SMB, HML, MOM)."""
        rng = np.random.default_rng(5)
        asset_ret, factor_returns, _, _ = _make_carhart_data(rng)
        result = carhart_4_factor_model(asset_ret, factor_returns)
        assert len(result["betas"]) == 4

    def test_missing_mom_raises(self):
        """Missing MOM factor should raise ValueError."""
        rng = np.random.default_rng(6)
        asset_ret, factor_returns, _, _ = _make_carhart_data(rng)
        factor_no_mom = factor_returns.drop(columns=["MOM"])
        with pytest.raises(ValueError, match="MOM"):
            carhart_4_factor_model(asset_ret, factor_no_mom)
