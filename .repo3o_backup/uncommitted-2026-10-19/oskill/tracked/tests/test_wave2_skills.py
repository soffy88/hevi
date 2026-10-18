"""Tests for Wave 2 oskills and omodul."""

import pytest

from oskill.wave2_skills import (
    cross_asset_score_normalization,
    ic_root_cause_decompose,
    regime_dynamic_weight_adjustment,
    signal_directionality_profile,
)


def test_ic_root_cause():
    r = ic_root_cause_decompose(
        signal_matrix=[[0.1, 0.2, -0.1]] * 100,
        returns=[0.01 if i % 2 == 0 else -0.01 for i in range(100)],
        regime_labels=["bull"] * 50 + ["bear"] * 50,
        dimension_names=["trend", "flow", "sentiment"],
    )
    assert "matrix" in r
    assert "diagnosis_summary" in r


def test_signal_directionality():
    r = signal_directionality_profile(
        signal_matrix=[[0.1, -0.1]] * 50,
        returns_by_horizon={1: [0.01] * 50, 7: [-0.01] * 50},
        dimension_names=["trend", "flow"],
    )
    assert len(r["dimensions"]) == 2
    assert "summary" in r


def test_cross_asset_normalization():
    r = cross_asset_score_normalization(
        asset_scores={"BTC": 65, "Gold": 42},
        asset_histories={"BTC": list(range(30, 80)), "Gold": list(range(20, 60))},
    )
    assert len(r["ranking"]) == 2
    assert r["top_opportunity"] in ("BTC", "Gold")


def test_regime_weight_adjustment():
    r = regime_dynamic_weight_adjustment(
        base_weights={"trend": 0.15, "flow": 0.12, "sentiment": 0.10},
        current_regime="bull",
        regime_weight_matrix={"bull": {"trend": 0.10, "sentiment": -0.05}},
    )
    assert r["adjusted_weights"]["trend"] > 0.15 * r["normalization_factor"]
    assert sum(r["adjusted_weights"].values()) == pytest.approx(1.0, abs=0.001)


def test_regime_weight_unknown_regime():
    r = regime_dynamic_weight_adjustment(
        base_weights={"a": 0.5, "b": 0.5},
        current_regime="unknown",
        regime_weight_matrix={"bull": {"a": 0.1}},
    )
    assert r["adjusted_weights"] == {"a": 0.5, "b": 0.5}
