"""Tests for systemic risk metrics (CoVaR, MES, SRISK)."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.risk.systemic import systemic_risk_metrics


@pytest.fixture
def base_data():
    rng = np.random.default_rng(42)
    T, N = 200, 4
    market = rng.normal(0.0, 0.01, T)
    institutions = rng.normal(0.0, 0.015, (T, N))
    return institutions, market


def test_default_metrics_present(base_data):
    inst, mkt = base_data
    result = systemic_risk_metrics(inst, mkt)
    assert "covar" in result
    assert "mes" in result


def test_covar_shape(base_data):
    inst, mkt = base_data
    result = systemic_risk_metrics(inst, mkt, metrics=["covar"])
    assert result["covar"].shape == (4,)


def test_mes_shape(base_data):
    inst, mkt = base_data
    result = systemic_risk_metrics(inst, mkt, metrics=["mes"])
    assert result["mes"].shape == (4,)


def test_mes_negative_for_correlated_asset(base_data):
    """Institution correlated with market should have negative MES."""
    rng = np.random.default_rng(99)
    T = 300
    market = rng.normal(0.0, 0.01, T)
    inst = np.column_stack([market + rng.normal(0, 0.001, T), rng.normal(0, 0.01, T)])
    result = systemic_risk_metrics(inst, market, metrics=["mes"])
    # First institution is strongly correlated; when market is down, it's also down
    assert result["mes"][0] < 0.0


def test_no_nan_in_results(base_data):
    inst, mkt = base_data
    result = systemic_risk_metrics(inst, mkt, metrics=["covar", "mes"])
    for k, arr in result.items():
        assert not np.any(np.isnan(arr)), f"{k} has NaN"


def test_srisk_with_leverage_market_cap(base_data):
    inst, mkt = base_data
    N = 4
    leverage = np.array([10.0, 15.0, 8.0, 12.0])
    market_cap = np.array([100.0, 50.0, 200.0, 75.0])
    result = systemic_risk_metrics(
        inst,
        mkt,
        metrics=["srisk"],
        leverage=leverage,
        market_cap=market_cap,
    )
    assert "srisk" in result
    assert result["srisk"].shape == (N,)
    assert np.all(result["srisk"] >= 0)


def test_srisk_without_leverage_is_zeros(base_data):
    inst, mkt = base_data
    result = systemic_risk_metrics(inst, mkt, metrics=["srisk"])
    assert "srisk" in result
    assert np.all(result["srisk"] == 0)


def test_market_returns_1d_works(base_data):
    inst, mkt = base_data
    result = systemic_risk_metrics(inst, mkt.reshape(-1, 1))
    assert "mes" in result


def test_invalid_institution_returns_shape():
    with pytest.raises(ValueError, match="2-D"):
        systemic_risk_metrics(np.ones(100), np.ones(100))


def test_mismatched_T_raises(base_data):
    inst, mkt = base_data
    with pytest.raises(ValueError, match="T="):
        systemic_risk_metrics(inst, mkt[:50])


def test_custom_quantile(base_data):
    inst, mkt = base_data
    result_5 = systemic_risk_metrics(inst, mkt, metrics=["mes"], quantile=0.05)
    result_10 = systemic_risk_metrics(inst, mkt, metrics=["mes"], quantile=0.10)
    # Both should return valid shapes
    assert result_5["mes"].shape == (4,)
    assert result_10["mes"].shape == (4,)
