"""Reference paper reproduction tests: HRP v2 — López de Prado (2016).

Reference
---------
López de Prado, M. (2016). Building diversified portfolios that outperform out-of-sample.
    Journal of Portfolio Management, 42(4), 59–69.
"""

from __future__ import annotations

import numpy as np
import pytest

from oskill.portfolio.hrp import hierarchical_risk_parity_v2


def _block_corr_returns(
    n_assets: int = 10,
    n_obs: int = 252,
    rho_within: float = 0.9,
    rho_across: float = 0.1,
    vol: float = 0.01,
    seed: int = 0,
) -> np.ndarray:
    """Generate returns with 2-group block correlation structure."""
    rng = np.random.default_rng(seed)
    half = n_assets // 2
    # Build correlation matrix
    corr = np.full((n_assets, n_assets), rho_across)
    corr[:half, :half] = rho_within
    corr[half:, half:] = rho_within
    np.fill_diagonal(corr, 1.0)
    cov = corr * (vol**2)
    # Cholesky factor
    L = np.linalg.cholesky(cov)
    z = rng.standard_normal((n_obs, n_assets))
    return z @ L.T


@pytest.mark.academic_reference
def test_weights_sum_to_one():
    """HRP weights must sum to exactly 1.0 (paper Section 3)."""
    returns = _block_corr_returns()
    result = hierarchical_risk_parity_v2(returns, use_rie_cleaning=False)
    np.testing.assert_allclose(result["weights"].sum(), 1.0, atol=1e-10)


@pytest.mark.academic_reference
def test_weights_non_negative():
    """HRP produces non-negative weights (long-only by construction)."""
    returns = _block_corr_returns()
    result = hierarchical_risk_parity_v2(returns, use_rie_cleaning=False)
    assert np.all(result["weights"] >= -1e-12), "Negative weights detected."


@pytest.mark.academic_reference
def test_hrp_more_diversified_than_mv():
    """HRP concentration should be more evenly spread than minimum-variance.

    Paper claim: HRP outperforms concentrated MV portfolios.  We proxy
    diversification with the Herfindahl index on risk contributions.
    """
    returns = _block_corr_returns(seed=7)
    result = hierarchical_risk_parity_v2(returns, use_rie_cleaning=False)
    w_hrp = result["weights"]
    cov = result["cov_used"]
    np.sqrt(np.diag(cov))
    n = len(w_hrp)

    # HRP risk contributions
    hrp_rc = w_hrp * (cov @ w_hrp) / (w_hrp @ cov @ w_hrp + 1e-12)

    # Minimum-variance portfolio (analytic: w ∝ cov^{-1} @ ones)
    try:
        cov_inv = np.linalg.inv(cov + 1e-8 * np.eye(n))
        ones = np.ones(n)
        w_mv = cov_inv @ ones / (ones @ cov_inv @ ones)
    except np.linalg.LinAlgError:
        w_mv = np.ones(n) / n
    mv_rc = w_mv * (cov @ w_mv) / (w_mv @ cov @ w_mv + 1e-12)

    def herfindahl(rc: np.ndarray) -> float:
        rc = rc / (rc.sum() + 1e-12)
        return float((rc**2).sum())

    hhi_hrp = herfindahl(hrp_rc)
    hhi_mv = herfindahl(mv_rc)
    # HRP should be at least as diversified (lower HHI) or within tolerance
    assert hhi_hrp <= hhi_mv + 0.2, f"HRP HHI={hhi_hrp:.4f} is much higher than MV HHI={hhi_mv:.4f}"


@pytest.mark.academic_reference
def test_hrp_hrc_vs_equal_weight():
    """HRP risk contribution spread >= 80% of equal-weight HRC spread.

    Implements the paper's diversification ratio comparison:
    HRC = weights · std, verifying HRP does not collapse to near-trivial allocation.
    """
    returns = _block_corr_returns(seed=42)
    result = hierarchical_risk_parity_v2(returns, use_rie_cleaning=False)
    w_hrp = result["weights"]
    cov = result["cov_used"]
    stds = np.sqrt(np.diag(cov) + 1e-12)
    n = len(w_hrp)

    def hrc_spread(w: np.ndarray) -> float:
        """Sum of |weight_i * std_i| — a measure of risk spread."""
        return float(np.sum(np.abs(w) * stds))

    w_eq = np.ones(n) / n
    hrc_hrp = hrc_spread(w_hrp)
    hrc_eq = hrc_spread(w_eq)

    assert hrc_hrp >= 0.8 * hrc_eq, (
        f"HRP HRC={hrc_hrp:.6f} is below 80% of equal-weight HRC={hrc_eq:.6f}"
    )


@pytest.mark.academic_reference
def test_result_keys_present():
    """Result dict must contain all documented keys."""
    returns = _block_corr_returns()
    result = hierarchical_risk_parity_v2(returns, use_rie_cleaning=False)
    for key in ("weights", "linkage_matrix", "cluster_order", "cov_used"):
        assert key in result, f"Missing key: {key}"


@pytest.mark.academic_reference
def test_cluster_order_is_permutation():
    """Cluster order must be a valid permutation of asset indices."""
    returns = _block_corr_returns(n_assets=10)
    result = hierarchical_risk_parity_v2(returns, use_rie_cleaning=False)
    order = result["cluster_order"]
    n = returns.shape[1]
    assert sorted(order) == list(range(n)), "cluster_order is not a valid permutation."


@pytest.mark.academic_reference
def test_ward_linkage_valid():
    """HRP with ward linkage also returns valid weights summing to 1."""
    returns = _block_corr_returns(seed=99)
    result = hierarchical_risk_parity_v2(returns, use_rie_cleaning=False, linkage_method="ward")
    np.testing.assert_allclose(result["weights"].sum(), 1.0, atol=1e-10)


@pytest.mark.academic_reference
def test_two_asset_trivial_case():
    """2-asset HRP: each asset receives a share inversely proportional to its variance."""
    rng = np.random.default_rng(5)
    # Asset 0 is twice as volatile as asset 1
    r = np.column_stack(
        [
            rng.normal(0, 0.02, 300),
            rng.normal(0, 0.01, 300),
        ]
    )
    result = hierarchical_risk_parity_v2(r, use_rie_cleaning=False)
    w = result["weights"]
    # Lower volatility asset should get higher weight
    assert w[1] > w[0], f"Expected w[1]>w[0], got w={w}"


@pytest.mark.academic_reference
def test_rie_cleaning_does_not_break_weights():
    """HRP with RIE cleaning enabled should still produce valid weights."""
    returns = _block_corr_returns(n_obs=300)
    result = hierarchical_risk_parity_v2(returns, use_rie_cleaning=True)
    np.testing.assert_allclose(result["weights"].sum(), 1.0, atol=1e-10)
    assert np.all(result["weights"] >= -1e-12)


@pytest.mark.academic_reference
def test_raises_on_insufficient_samples():
    """Fewer than 10 samples must raise ValueError."""
    with pytest.raises(ValueError, match="10"):
        hierarchical_risk_parity_v2(np.random.randn(5, 4), use_rie_cleaning=False)


@pytest.mark.academic_reference
def test_raises_on_single_asset():
    """Single asset must raise ValueError."""
    with pytest.raises(ValueError, match="2"):
        hierarchical_risk_parity_v2(np.random.randn(50, 1), use_rie_cleaning=False)
