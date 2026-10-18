"""Tests for oskill.scm_fit.structural_causal_model_fit."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oskill.scm_fit import structural_causal_model_fit


def _make_linear_scm_data(n=300, seed=42):
    """Known linear SCM: X → Y with coefficient 2.0."""
    rng = np.random.default_rng(seed)
    X = rng.normal(0, 1, n)
    noise = rng.normal(0, 0.1, n)
    Y = 2.0 * X + noise
    data = pd.DataFrame({"X": X, "Y": Y})
    graph = {"X": [], "Y": ["X"]}
    return data, graph


def _make_chain_scm(n=200, seed=0):
    """X → Y → Z chain."""
    rng = np.random.default_rng(seed)
    X = rng.normal(0, 1, n)
    Y = 1.5 * X + rng.normal(0, 0.2, n)
    Z = -0.5 * Y + rng.normal(0, 0.2, n)
    data = pd.DataFrame({"X": X, "Y": Y, "Z": Z})
    graph = {"X": [], "Y": ["X"], "Z": ["Y"]}
    return data, graph


# ─── API / return keys ────────────────────────────────────────────────────────


def test_returns_expected_keys():
    data, graph = _make_linear_scm_data()
    result = structural_causal_model_fit(data, graph)
    expected = {
        "fitted_models",
        "residuals",
        "r_squared_per_var",
        "intervention_samples",
        "natural_distribution_samples",
        "intervention_effect_size",
        "graph_is_dag",
    }
    assert expected == set(result.keys())


def test_graph_is_dag_true_for_valid_dag():
    data, graph = _make_linear_scm_data()
    result = structural_causal_model_fit(data, graph)
    assert result["graph_is_dag"] is True


def test_cycle_detection_raises():
    rng = np.random.default_rng(0)
    data = pd.DataFrame(rng.normal(0, 1, (100, 2)), columns=["A", "B"])
    cyclic_graph = {"A": ["B"], "B": ["A"]}
    with pytest.raises(ValueError, match="cycle"):
        structural_causal_model_fit(data, cyclic_graph)


def test_linear_recovers_known_coefficient():
    """Linear estimator should recover coefficient ~ 2.0 for Y = 2.0*X + noise."""
    data, graph = _make_linear_scm_data(n=1000)
    result = structural_causal_model_fit(data, graph)
    coef_y = result["fitted_models"]["Y"]["coefficients"]["X"]
    assert abs(coef_y - 2.0) < 0.15, f"Expected ~2.0, got {coef_y:.4f}"


def test_r_squared_high_for_clean_linear():
    data, graph = _make_linear_scm_data(n=500)
    result = structural_causal_model_fit(data, graph)
    assert result["r_squared_per_var"]["Y"] > 0.9


def test_residuals_returned():
    data, graph = _make_linear_scm_data()
    result = structural_causal_model_fit(data, graph)
    assert "X" in result["residuals"]
    assert "Y" in result["residuals"]
    assert len(result["residuals"]["Y"]) == len(data)


def test_natural_distribution_samples_shape():
    data, graph = _make_linear_scm_data()
    result = structural_causal_model_fit(data, graph, n_samples_intervention=200)
    for var in ["X", "Y"]:
        assert result["natural_distribution_samples"][var].shape == (200,)


def test_intervention_samples_returned():
    data, graph = _make_linear_scm_data()
    result = structural_causal_model_fit(
        data,
        graph,
        do_intervention_var="X",
        do_intervention_value=5.0,
        n_samples_intervention=100,
    )
    assert "X" in result["intervention_samples"]
    assert result["intervention_samples"]["X"].shape == (100,)
    # Intervention on X should fix it to 5.0
    assert np.all(result["intervention_samples"]["X"] == 5.0)


def test_effect_size_computed():
    data, graph = _make_linear_scm_data()
    result = structural_causal_model_fit(
        data,
        graph,
        do_intervention_var="X",
        do_intervention_value=5.0,
    )
    # Y should have non-zero effect size when X is shifted
    assert "Y" in result["intervention_effect_size"]
    assert result["intervention_effect_size"]["Y"] > 0.0


def test_chain_scm():
    data, graph = _make_chain_scm()
    result = structural_causal_model_fit(data, graph)
    assert result["graph_is_dag"] is True
    # Y coefficient on X should be ~1.5
    coef = result["fitted_models"]["Y"]["coefficients"]["X"]
    assert abs(coef - 1.5) < 0.3
