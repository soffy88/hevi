"""Tests for bonferroni_holm_correction."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.validation.trial_correction import bonferroni_holm_correction


@pytest.fixture
def p_values():
    return [0.001, 0.01, 0.03, 0.08, 0.15, 0.30, 0.50]


def test_correction_bonferroni_basic(p_values):
    result = bonferroni_holm_correction(p_values, method="bonferroni")
    m = len(p_values)
    expected = np.minimum(np.array(p_values) * m, 1.0)
    np.testing.assert_allclose(result["corrected_p_values"], expected)


def test_correction_holm_basic(p_values):
    result = bonferroni_holm_correction(p_values, method="holm")
    corrected = result["corrected_p_values"]
    assert len(corrected) == len(p_values)
    assert np.all(corrected >= np.array(p_values))


def test_correction_fdr_bh_basic(p_values):
    result = bonferroni_holm_correction(p_values, method="fdr_bh")
    assert result["fdr_or_fwer"] == "FDR"
    assert len(result["corrected_p_values"]) == len(p_values)


def test_correction_fdr_by_basic(p_values):
    result = bonferroni_holm_correction(p_values, method="fdr_by")
    assert result["fdr_or_fwer"] == "FDR"
    # BHY is more conservative than BH
    bh = bonferroni_holm_correction(p_values, method="fdr_bh")["corrected_p_values"]
    by = result["corrected_p_values"]
    assert np.all(by >= bh - 1e-12)


def test_correction_returns_correct_keys(p_values):
    result = bonferroni_holm_correction(p_values)
    expected_keys = {
        "corrected_p_values",
        "is_significant_per_test",
        "is_significant_corrected",
        "method",
        "fdr_or_fwer",
    }
    assert set(result.keys()) == expected_keys


def test_correction_significant_uncorrected_more_than_corrected(p_values):
    result = bonferroni_holm_correction(p_values, method="bonferroni", alpha=0.05)
    n_uncorr = int(np.sum(result["is_significant_per_test"]))
    n_corr = int(np.sum(result["is_significant_corrected"]))
    assert n_uncorr >= n_corr


def test_correction_single_pvalue():
    result = bonferroni_holm_correction([0.03], method="holm", alpha=0.05)
    # With one test, Holm is identical to uncorrected
    assert result["corrected_p_values"][0] == pytest.approx(0.03)
    assert bool(result["is_significant_corrected"][0]) is True
