"""Tests for operational risk LDA implementation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from oskill.operational_risk.lda import operational_risk_lda


def _make_losses(n=500, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"loss_amount": rng.lognormal(10, 2, n)})


def test_lda_basic():
    r = operational_risk_lda(_make_losses(), seed=42, n_simulations=1000)
    assert "var" in r and r["var"] > 0


def test_lda_var_at_999():
    r = operational_risk_lda(_make_losses(), var_confidence=0.999, seed=42, n_simulations=5000)
    assert r["capital_requirement"] == r["var"]


def test_lda_es_ge_var():
    r = operational_risk_lda(_make_losses(), seed=42, n_simulations=5000)
    assert r["expected_shortfall"] >= r["var"]


def test_lda_expected_annual_loss_positive():
    r = operational_risk_lda(_make_losses(), seed=1, n_simulations=1000)
    assert r["expected_annual_loss"] > 0


def test_lda_percentiles_ordered():
    r = operational_risk_lda(_make_losses(), seed=2, n_simulations=5000)
    p = r["percentiles"]
    assert p["p50"] <= p["p90"] <= p["p99"] <= p["p999"]


def test_lda_frequency_params_dict():
    r = operational_risk_lda(_make_losses(), seed=3, n_simulations=1000)
    assert isinstance(r["frequency_params"], dict)


def test_lda_severity_params_dict():
    r = operational_risk_lda(_make_losses(), seed=4, n_simulations=1000)
    assert isinstance(r["severity_params"], dict)


def test_lda_weibull_severity():
    r = operational_risk_lda(
        _make_losses(), severity_distribution="weibull", seed=5, n_simulations=1000
    )
    assert r["var"] > 0


def test_lda_nbinom_frequency():
    r = operational_risk_lda(
        _make_losses(), frequency_distribution="negative_binomial", seed=6, n_simulations=1000
    )
    assert r["var"] > 0


def test_lda_seed_reproducible():
    r1 = operational_risk_lda(_make_losses(), seed=99, n_simulations=1000)
    r2 = operational_risk_lda(_make_losses(), seed=99, n_simulations=1000)
    np.testing.assert_allclose(r1["var"], r2["var"])
