"""Tests for financial network centrality metrics."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.networks.centrality import financial_network_centrality


@pytest.fixture
def simple_4x4():
    """Simple 4-node exposure matrix."""
    return np.array(
        [
            [0.0, 10.0, 5.0, 0.0],
            [0.0, 0.0, 8.0, 2.0],
            [3.0, 0.0, 0.0, 7.0],
            [0.0, 4.0, 0.0, 0.0],
        ]
    )


def test_debt_rank_default(simple_4x4):
    result = financial_network_centrality(simple_4x4)
    assert "debt_rank" in result
    dr = result["debt_rank"]
    assert dr.shape == (4,)
    assert np.all(dr >= 0)
    assert abs(dr.sum() - 1.0) < 1e-6


def test_eigenvector_centrality(simple_4x4):
    result = financial_network_centrality(simple_4x4, metrics=["eigenvector"])
    assert "eigenvector" in result
    ev = result["eigenvector"]
    assert ev.shape == (4,)
    assert np.all(ev >= 0)


def test_katz_centrality(simple_4x4):
    result = financial_network_centrality(simple_4x4, metrics=["katz"])
    assert "katz" in result
    katz = result["katz"]
    assert katz.shape == (4,)
    assert np.all(katz >= -1e-9)


def test_betweenness_centrality(simple_4x4):
    result = financial_network_centrality(simple_4x4, metrics=["betweenness"])
    assert "betweenness" in result
    betw = result["betweenness"]
    assert betw.shape == (4,)


def test_multiple_metrics(simple_4x4):
    result = financial_network_centrality(
        simple_4x4, metrics=["debt_rank", "eigenvector", "katz", "betweenness"]
    )
    assert set(result.keys()) == {"debt_rank", "eigenvector", "katz", "betweenness"}


def test_all_metrics_no_nan(simple_4x4):
    result = financial_network_centrality(
        simple_4x4, metrics=["debt_rank", "eigenvector", "katz", "betweenness"]
    )
    for name, arr in result.items():
        assert not np.any(np.isnan(arr)), f"{name} has NaN"


def test_zero_matrix():
    E = np.zeros((3, 3))
    result = financial_network_centrality(E, metrics=["debt_rank"])
    # All nodes equal importance
    assert result["debt_rank"].shape == (3,)


def test_non_negative_requirement():
    E = np.array([[0.0, -1.0], [1.0, 0.0]])
    with pytest.raises(ValueError, match="non-negative"):
        financial_network_centrality(E)


def test_too_few_nodes():
    with pytest.raises(ValueError, match="N >= 2"):
        financial_network_centrality(np.array([[1.0]]))


def test_unknown_metric_returns_zeros(simple_4x4):
    result = financial_network_centrality(simple_4x4, metrics=["unknown_metric"])
    assert "unknown_metric" in result
    assert np.all(result["unknown_metric"] == 0)
