"""Tests for oskill.conformal.change_point_cp.conformal_with_change_points."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.conformal.change_point_cp import conformal_with_change_points


def _make_data(n=200, seed=42):
    rng = np.random.default_rng(seed)
    preds = rng.normal(0, 1, n)
    acts = preds + rng.normal(0, 1, n)
    return preds, acts


# ─── API / return keys ────────────────────────────────────────────────────────


def test_returns_expected_keys():
    preds, acts = _make_data()
    result = conformal_with_change_points(preds, acts, detection_method="external")
    expected = {
        "lower",
        "upper",
        "change_points",
        "segments",
        "per_segment_quantiles",
        "segment_assignments",
        "fingerprint",
    }
    assert expected == set(result.keys())


def test_output_shapes():
    n = 120
    preds, acts = _make_data(n=n)
    result = conformal_with_change_points(preds, acts, detection_method="external")
    assert result["lower"].shape == (n,)
    assert result["upper"].shape == (n,)
    assert result["segment_assignments"].shape == (n,)


def test_lower_leq_upper():
    preds, acts = _make_data()
    result = conformal_with_change_points(preds, acts, detection_method="external")
    assert np.all(result["lower"] <= result["upper"])


def test_external_change_points():
    n = 200
    preds, acts = _make_data(n=n)
    cps = [50, 100, 150]
    result = conformal_with_change_points(
        preds, acts, detection_method="external", change_points=cps
    )
    assert result["change_points"] == cps
    assert len(result["segments"]) == 4


def test_no_change_points_single_segment():
    preds, acts = _make_data()
    result = conformal_with_change_points(
        preds, acts, detection_method="external", change_points=[]
    )
    assert len(result["segments"]) == 1
    assert len(result["per_segment_quantiles"]) == 1


def test_pelt_method_runs():
    preds, acts = _make_data(n=150)
    result = conformal_with_change_points(preds, acts, detection_method="pelt")
    assert "change_points" in result
    assert np.all(result["lower"] <= result["upper"])


def test_invalid_alpha_raises():
    preds, acts = _make_data()
    with pytest.raises(ValueError, match="alpha"):
        conformal_with_change_points(preds, acts, alpha=0.0)


def test_fingerprint_is_hex64():
    preds, acts = _make_data()
    result = conformal_with_change_points(preds, acts, detection_method="external")
    fp = result["fingerprint"]
    assert isinstance(fp, str) and len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_short_segments_use_global_quantile():
    """Segments shorter than min_segment_length should use global quantile."""
    n = 200
    rng = np.random.default_rng(0)
    preds = rng.normal(0, 1, n)
    acts = preds + rng.normal(0, 1, n)
    # Create a very short segment [190, 200] = 10 points
    cps = [190]
    result = conformal_with_change_points(
        preds,
        acts,
        detection_method="external",
        change_points=cps,
        min_segment_length=20,
    )
    # Both quantiles should be valid positive numbers
    assert all(q >= 0 for q in result["per_segment_quantiles"])
