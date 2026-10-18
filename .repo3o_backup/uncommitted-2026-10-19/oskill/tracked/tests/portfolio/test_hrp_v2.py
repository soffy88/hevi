"""Tests for hierarchical_risk_parity_v2."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.portfolio.hrp import hierarchical_risk_parity_v2


def make_returns(T: int = 100, N: int = 5, seed: int = 42) -> np.ndarray:
    """Generate synthetic asset returns."""
    rng = np.random.default_rng(seed)
    return rng.normal(0.001, 0.02, size=(T, N))


def make_block_returns(
    T: int = 200, n_per_block: int = 3, n_blocks: int = 3, seed: int = 0
) -> np.ndarray:
    """Returns with block correlation structure."""
    rng = np.random.default_rng(seed)
    N = n_per_block * n_blocks
    factors = rng.normal(0, 0.02, (T, n_blocks))
    idio = rng.normal(0, 0.01, (T, N))
    returns = np.zeros((T, N))
    for b in range(n_blocks):
        idx = slice(b * n_per_block, (b + 1) * n_per_block)
        returns[:, idx] = factors[:, b : b + 1] + idio[:, idx]
    return returns


class TestHRPv2Basic:
    def test_returns_dict_keys(self):
        returns = make_returns()
        result = hierarchical_risk_parity_v2(returns)
        assert "weights" in result
        assert "linkage_matrix" in result
        assert "cluster_order" in result
        assert "cov_used" in result

    def test_weights_sum_to_one(self):
        returns = make_returns()
        result = hierarchical_risk_parity_v2(returns)
        assert pytest.approx(result["weights"].sum(), abs=1e-8) == 1.0

    def test_weights_non_negative(self):
        returns = make_returns()
        result = hierarchical_risk_parity_v2(returns)
        assert np.all(result["weights"] >= -1e-10)

    def test_weights_shape(self):
        N = 7
        returns = make_returns(N=N)
        result = hierarchical_risk_parity_v2(returns)
        assert result["weights"].shape == (N,)

    def test_cluster_order_is_permutation(self):
        """cluster_order should be a permutation of [0, N-1]."""
        N = 5
        returns = make_returns(N=N)
        result = hierarchical_risk_parity_v2(returns)
        assert sorted(result["cluster_order"]) == list(range(N))

    def test_linkage_matrix_shape(self):
        N = 5
        returns = make_returns(N=N)
        result = hierarchical_risk_parity_v2(returns)
        # Linkage matrix has shape (N-1, 4)
        assert result["linkage_matrix"].shape == (N - 1, 4)

    def test_cov_matrix_shape(self):
        N = 5
        returns = make_returns(N=N)
        result = hierarchical_risk_parity_v2(returns)
        assert result["cov_used"].shape == (N, N)


class TestHRPv2Linkage:
    def test_ward_linkage(self):
        returns = make_returns()
        result = hierarchical_risk_parity_v2(returns, linkage_method="ward")
        assert pytest.approx(result["weights"].sum(), abs=1e-8) == 1.0

    def test_average_linkage(self):
        returns = make_returns()
        result = hierarchical_risk_parity_v2(returns, linkage_method="average")
        assert pytest.approx(result["weights"].sum(), abs=1e-8) == 1.0

    def test_single_linkage(self):
        returns = make_returns()
        result = hierarchical_risk_parity_v2(returns, linkage_method="single")
        assert pytest.approx(result["weights"].sum(), abs=1e-8) == 1.0


class TestHRPv2RiskMetrics:
    def test_variance_metric(self):
        returns = make_returns()
        result = hierarchical_risk_parity_v2(returns, risk_metric="variance")
        assert np.all(result["weights"] >= -1e-10)

    def test_cvar_metric(self):
        returns = make_returns()
        result = hierarchical_risk_parity_v2(returns, risk_metric="cvar")
        assert pytest.approx(result["weights"].sum(), abs=1e-8) == 1.0

    def test_tail_dependence_metric(self):
        returns = make_returns()
        result = hierarchical_risk_parity_v2(returns, risk_metric="tail_dependence")
        assert pytest.approx(result["weights"].sum(), abs=1e-8) == 1.0


class TestHRPv2Validation:
    def test_too_few_samples_raises(self):
        with pytest.raises(ValueError, match="10 samples"):
            hierarchical_risk_parity_v2(make_returns(T=5))

    def test_single_asset_raises(self):
        with pytest.raises(ValueError, match="2 assets"):
            hierarchical_risk_parity_v2(make_returns(N=1))

    def test_rie_disabled(self):
        returns = make_returns()
        result = hierarchical_risk_parity_v2(returns, use_rie_cleaning=False)
        assert pytest.approx(result["weights"].sum(), abs=1e-8) == 1.0

    def test_block_structure_diversification(self):
        """Weights should be reasonably diversified for block returns."""
        returns = make_block_returns()
        result = hierarchical_risk_parity_v2(returns, use_rie_cleaning=False)
        w = result["weights"]
        # No single asset should dominate (all weights < 0.5)
        assert np.all(w < 0.5)
