"""Tests for oskill.causal_discovery.pcmci_causal_discovery."""

from __future__ import annotations

import numpy as np
import pandas as pd

from oskill.causal_discovery import pcmci_causal_discovery


def _make_iid_data(n=200, n_vars=3, seed=42):
    rng = np.random.default_rng(seed)
    data = pd.DataFrame(rng.normal(0, 1, (n, n_vars)), columns=[f"V{i}" for i in range(n_vars)])
    return data


def _make_lagged_causal_data(n=300, seed=0):
    """X causes Y at lag 1: Y[t] = 0.8*X[t-1] + noise."""
    rng = np.random.default_rng(seed)
    X = rng.normal(0, 1, n)
    Y = np.zeros(n)
    for t in range(1, n):
        Y[t] = 0.8 * X[t - 1] + 0.1 * rng.normal()
    Z = rng.normal(0, 1, n)
    return pd.DataFrame({"X": X, "Y": Y, "Z": Z})


# ─── API / return keys ────────────────────────────────────────────────────────


def test_returns_expected_keys():
    data = _make_iid_data()
    result = pcmci_causal_discovery(data, max_lag=2)
    expected = {"graph", "p_matrix", "val_matrix", "links", "lags", "method", "fingerprint"}
    assert expected == set(result.keys())


def test_p_matrix_shape():
    data = _make_iid_data(n_vars=3)
    result = pcmci_causal_discovery(data, max_lag=3)
    assert result["p_matrix"].shape == (3, 3, 4)  # (n_vars, n_vars, max_lag+1)


def test_val_matrix_shape():
    data = _make_iid_data(n_vars=4)
    result = pcmci_causal_discovery(data, max_lag=2)
    assert result["val_matrix"].shape == (4, 4, 3)


def test_p_values_in_01():
    data = _make_iid_data()
    result = pcmci_causal_discovery(data, max_lag=2)
    p = result["p_matrix"]
    assert np.all(p >= 0.0) and np.all(p <= 1.0)


def test_iid_data_few_links():
    """Independent data should yield very few significant links."""
    rng = np.random.default_rng(99)
    data = pd.DataFrame(rng.normal(0, 1, (500, 4)), columns=[f"V{i}" for i in range(4)])
    result = pcmci_causal_discovery(data, max_lag=2, alpha=0.01)
    # Few false positives expected (allow up to 5)
    assert len(result["links"]) <= 5, f"Too many links: {result['links']}"


def test_causal_link_detected():
    """Known X→Y at lag 1 should be detected."""
    data = _make_lagged_causal_data(n=400)
    result = pcmci_causal_discovery(data, max_lag=2, alpha=0.05, fdr_correction=False)
    links = result["links"]
    # Find X (index 0) → Y (index 1) at lag 1
    var_names = list(data.columns)
    x_idx = var_names.index("X")
    y_idx = var_names.index("Y")
    causal_link = (x_idx, y_idx, 1)
    assert causal_link in links, f"Expected link {causal_link} in {links}"


def test_lags_list():
    data = _make_iid_data()
    result = pcmci_causal_discovery(data, max_lag=4)
    assert result["lags"] == [1, 2, 3, 4]


def test_method_returned():
    data = _make_iid_data()
    result = pcmci_causal_discovery(data, independence_test="partial_correlation")
    assert result["method"] == "partial_correlation"


def test_fingerprint_hex64():
    data = _make_iid_data()
    result = pcmci_causal_discovery(data)
    fp = result["fingerprint"]
    assert isinstance(fp, str) and len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_fingerprint_deterministic():
    data = _make_iid_data()
    r1 = pcmci_causal_discovery(data, max_lag=2, alpha=0.05)
    r2 = pcmci_causal_discovery(data, max_lag=2, alpha=0.05)
    assert r1["fingerprint"] == r2["fingerprint"]


def test_graph_boolean_array():
    data = _make_iid_data()
    result = pcmci_causal_discovery(data, max_lag=2)
    assert result["graph"].dtype == bool
