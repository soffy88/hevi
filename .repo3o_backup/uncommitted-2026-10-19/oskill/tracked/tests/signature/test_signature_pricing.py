"""Tests for signature_based_pricing."""

from __future__ import annotations

import numpy as np

from oskill.signature.pricing import signature_based_pricing


def _make_paths(n: int = 200, T: int = 30, d: int = 1, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    inc = rng.normal(0, 0.01, (n, T, d))
    paths = np.cumsum(inc, axis=1) + 100.0
    return paths


def _asian_call_payoff(path: np.ndarray, K: float = 100.0) -> float:
    return max(float(np.mean(path[:, 0])) - K, 0.0)


def test_sbp_basic():
    paths = _make_paths()
    r = signature_based_pricing(paths, lambda p: _asian_call_payoff(p), truncation_depth=3)
    assert "pricing_functional" in r


def test_sbp_r_squared_in_range():
    paths = _make_paths(n=100)
    r = signature_based_pricing(paths, lambda p: _asian_call_payoff(p), truncation_depth=3)
    assert -1.0 <= r["in_sample_r_squared"] <= 1.0


def test_sbp_price_fn_callable():
    paths = _make_paths(n=100)
    r = signature_based_pricing(paths, lambda p: _asian_call_payoff(p), truncation_depth=3)
    assert callable(r["price_fn"])


def test_sbp_price_fn_returns_float():
    paths = _make_paths(n=100)
    r = signature_based_pricing(paths, lambda p: _asian_call_payoff(p), truncation_depth=3)
    new_path = _make_paths(n=1, seed=99)[0]
    price = r["price_fn"](new_path)
    assert isinstance(price, float)


def test_sbp_training_arrays_correct_length():
    paths = _make_paths(n=100)
    r = signature_based_pricing(paths, lambda p: _asian_call_payoff(p))
    assert len(r["training_payoffs"]) == len(r["training_predictions"])


def test_sbp_ridge_method():
    paths = _make_paths(n=100)
    r = signature_based_pricing(paths, lambda p: _asian_call_payoff(p), method="ridge")
    assert r["method"] == "ridge"


def test_sbp_lasso_method():
    paths = _make_paths(n=100)
    r = signature_based_pricing(paths, lambda p: _asian_call_payoff(p), method="lasso")
    assert r["method"] == "lasso"


def test_sbp_fingerprint():
    paths = _make_paths(n=100)
    r = signature_based_pricing(paths, lambda p: _asian_call_payoff(p))
    assert isinstance(r["fingerprint"], str) and len(r["fingerprint"]) == 64


def test_sbp_depth_effects():
    paths = _make_paths(n=50)
    r3 = signature_based_pricing(paths, lambda p: _asian_call_payoff(p), truncation_depth=3)
    r4 = signature_based_pricing(paths, lambda p: _asian_call_payoff(p), truncation_depth=4)
    assert r4["pricing_functional"].shape != r3["pricing_functional"].shape


def test_sbp_n_basis_paths():
    paths = _make_paths(n=500)
    r = signature_based_pricing(paths, lambda p: _asian_call_payoff(p), n_basis_paths=50)
    assert len(r["training_payoffs"]) <= 50


def test_sbp_fallback_when_no_signature(mocker):
    """When _HAS_SIGNATURE is False, _compute_sig is used instead of oprim."""
    mocker.patch("oskill.signature.pricing._HAS_SIGNATURE", False)
    paths = _make_paths(n=50)
    r = signature_based_pricing(paths, lambda p: _asian_call_payoff(p), truncation_depth=2)
    assert "pricing_functional" in r
    assert isinstance(r["in_sample_r_squared"], float)


def test_compute_sig_helper_pricing():
    """_compute_sig helper produces correct shape output."""
    from oskill.signature.pricing import _compute_sig

    path = np.cumsum(np.random.default_rng(0).normal(0, 0.1, (8, 2)), axis=0)
    sig = _compute_sig(path, depth=2)
    assert sig.ndim == 1
    assert len(sig) > 0


def test_get_signature_fallback(mocker):
    """_get_signature uses _compute_sig when _HAS_SIGNATURE is False."""
    mocker.patch("oskill.signature.pricing._HAS_SIGNATURE", False)
    from oskill.signature.pricing import _get_signature

    path = np.cumsum(np.random.default_rng(0).normal(0, 0.1, (8, 2)), axis=0)
    sig = _get_signature(path, depth=2)
    assert sig.ndim == 1


def test_sbp_linear_regression_method():
    """Default method (linear regression) works and sets method='linear'."""
    paths = _make_paths(n=50)
    r = signature_based_pricing(paths, lambda p: _asian_call_payoff(p), method="linear")
    assert r["method"] == "linear"
