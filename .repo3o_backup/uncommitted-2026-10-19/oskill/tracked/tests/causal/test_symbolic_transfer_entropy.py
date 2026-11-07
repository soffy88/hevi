"""Tests for oskill.causal.symbolic_transfer_entropy."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.causal import symbolic_transfer_entropy

# ─── basic API ───────────────────────────────────────────────────────────────


def test_ste_returns_te_key():
    """Basic call returns a dict with 'te' key."""
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 100)
    y = rng.normal(0, 1, 100)
    result = symbolic_transfer_entropy(x, y, d=3, lag=1)
    assert "te" in result
    assert isinstance(result["te"], float)


def test_ste_value_is_non_negative():
    """Transfer entropy must be >= 0."""
    rng = np.random.default_rng(1)
    x = rng.normal(0, 1, 200)
    y = rng.normal(0, 1, 200)
    result = symbolic_transfer_entropy(x, y, d=3, lag=1)
    assert result["te"] >= 0.0


def test_ste_independent_series_low_te():
    """Two independent series: TE should be low (allow up to 0.5 bits)."""
    rng = np.random.default_rng(42)
    x = rng.normal(0, 1, 300)
    y = rng.normal(0, 1, 300)
    result = symbolic_transfer_entropy(x, y, d=3, lag=1, random_state=42)
    assert result["te"] < 0.5, f"Expected low TE for independent series, got {result['te']:.4f}"


def test_ste_driven_series_positive_te():
    """target[t] = 0.9*source[t-1] + 0.1*noise → TE(source→target) > 0."""
    rng = np.random.default_rng(7)
    n = 500
    source = rng.normal(0, 1, n)
    target = np.zeros(n)
    for t in range(1, n):
        target[t] = 0.9 * source[t - 1] + 0.1 * rng.normal()
    result = symbolic_transfer_entropy(source, target, d=3, lag=1)
    assert result["te"] > 0.0, f"Expected TE>0 for driven series, got {result['te']:.4f}"


def test_ste_with_surrogates_returns_p_value():
    """n_surrogates=20 → result has 'p_value' and 'significant' keys."""
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 200)
    y = rng.normal(0, 1, 200)
    result = symbolic_transfer_entropy(x, y, d=3, lag=1, n_surrogates=20, random_state=0)
    assert "p_value" in result
    assert "significant" in result
    assert 0.0 <= result["p_value"] <= 1.0
    assert isinstance(result["significant"], bool)


def test_ste_too_short_input():
    """Very short input: either returns te=0 or raises gracefully (no crash)."""
    x = np.array([1, 2, 3, 4, 5])
    y = np.array([1, 2, 3, 4, 5])
    try:
        result = symbolic_transfer_entropy(x, y, d=3, lag=1)
        assert result["te"] == 0.0 or result["te"] >= 0.0
    except (ValueError, ZeroDivisionError):
        pass  # acceptable to raise on very short input


@pytest.mark.academic_reference
def test_ste_staniek_lehnertz_2008():
    """Staniek & Lehnertz (2008): For X→Y coupling, TE(X→Y) > TE(Y→X).

    Reference: Staniek, M. & Lehnertz, K. (2008). Physical Review Letters.
    Coupled system: y[t] = 0.9*x[t-1] + 0.1*eps.
    Asymmetry: TE(x→y) > TE(y→x).
    """
    rng = np.random.default_rng(42)
    n = 600
    x = rng.normal(0, 1, n)
    y = np.zeros(n)
    for t in range(1, n):
        y[t] = 0.9 * x[t - 1] + 0.1 * rng.normal()

    te_xy = symbolic_transfer_entropy(x, y, d=3, lag=1)["te"]
    te_yx = symbolic_transfer_entropy(y, x, d=3, lag=1)["te"]

    assert te_xy > te_yx, f"Expected TE(x→y)={te_xy:.4f} > TE(y→x)={te_yx:.4f} for driven system"
