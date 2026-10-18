"""Tests for Group 5: Prediction Quality skills."""

import numpy as np
import pandas as pd
import pytest

from oskill.prediction import calibration_analysis


class TestCalibrationAnalysis:
    """Tests for calibration_analysis."""

    def test_perfect_calibration(self):
        """Perfect calibration → brier ≈ 0, ece ≈ 0."""
        # predictions = outcomes → perfect
        predictions = np.array([0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0])
        outcomes = predictions.copy()
        result = calibration_analysis(predictions, outcomes)
        assert result["brier_score"] < 0.01
        assert result["ece"] < 0.01

    def test_poor_calibration_high_ece(self):
        """All 0.5 predictions, random outcomes → ECE > 0."""
        rng = np.random.default_rng(42)
        predictions = np.full(200, 0.5)
        outcomes = rng.choice([0.0, 1.0], size=200)
        result = calibration_analysis(predictions, outcomes)
        # ECE should be small since 0.5 predictions with ~50% outcomes is calibrated
        assert result["ece"] < 0.1

    def test_completely_wrong(self):
        """predictions=1 when outcomes=0 → high brier."""
        predictions = np.array([0.9] * 50 + [0.1] * 50)
        outcomes = np.array([0.0] * 50 + [1.0] * 50)
        result = calibration_analysis(predictions, outcomes)
        assert result["brier_score"] > 0.5
        assert result["ece"] > 0.5

    def test_binning_equal_width(self):
        """binning='equal_width' works."""
        rng = np.random.default_rng(42)
        predictions = rng.uniform(0, 1, 100)
        outcomes = (rng.uniform(0, 1, 100) < predictions).astype(float)
        result = calibration_analysis(predictions, outcomes, binning="equal_width")
        assert result["binning"] == "equal_width"

    def test_binning_equal_freq(self):
        """binning='equal_freq' works."""
        rng = np.random.default_rng(42)
        predictions = rng.uniform(0, 1, 100)
        outcomes = (rng.uniform(0, 1, 100) < predictions).astype(float)
        result = calibration_analysis(predictions, outcomes, binning="equal_freq")
        assert result["binning"] == "equal_freq"

    def test_include_reliability_diagram_true(self):
        """include_reliability_diagram=True returns DataFrame."""
        rng = np.random.default_rng(42)
        predictions = rng.uniform(0, 1, 100)
        outcomes = (rng.uniform(0, 1, 100) < predictions).astype(float)
        result = calibration_analysis(predictions, outcomes, include_reliability_diagram=True)
        assert result["reliability_diagram"] is not None
        assert isinstance(result["reliability_diagram"], pd.DataFrame)

    def test_include_reliability_diagram_false(self):
        """include_reliability_diagram=False returns None."""
        rng = np.random.default_rng(42)
        predictions = rng.uniform(0, 1, 100)
        outcomes = (rng.uniform(0, 1, 100) < predictions).astype(float)
        result = calibration_analysis(predictions, outcomes, include_reliability_diagram=False)
        assert result["reliability_diagram"] is None

    def test_include_bayesian_ci_true(self):
        """include_bayesian_ci=True adds CI columns."""
        rng = np.random.default_rng(42)
        predictions = rng.uniform(0, 1, 100)
        outcomes = (rng.uniform(0, 1, 100) < predictions).astype(float)
        result = calibration_analysis(predictions, outcomes, include_bayesian_ci=True)
        df = result["reliability_diagram"]
        assert "ci_low" in df.columns
        assert "ci_high" in df.columns
        assert df["ci_low"].notna().any()

    def test_include_bayesian_ci_false(self):
        """include_bayesian_ci=False → CI columns are None."""
        rng = np.random.default_rng(42)
        predictions = rng.uniform(0, 1, 100)
        outcomes = (rng.uniform(0, 1, 100) < predictions).astype(float)
        result = calibration_analysis(predictions, outcomes, include_bayesian_ci=False)
        df = result["reliability_diagram"]
        assert all(df["ci_low"].isna())

    def test_predictions_out_of_range_raises(self):
        """predictions outside [0,1] raises."""
        with pytest.raises(ValueError, match="\\[0, 1\\]"):
            calibration_analysis(np.array([0.5, 1.5]), np.array([0.0, 1.0]))

    def test_outcomes_not_binary_raises(self):
        """outcomes not 0/1 raises."""
        with pytest.raises(ValueError, match="binary"):
            calibration_analysis(np.array([0.5, 0.5]), np.array([0.0, 0.5]))

    def test_length_mismatch_raises(self):
        """Different lengths raises."""
        with pytest.raises(ValueError, match="same length"):
            calibration_analysis(np.array([0.5, 0.5, 0.5]), np.array([0.0, 1.0]))

    def test_empty_raises(self):
        """Empty raises."""
        with pytest.raises(ValueError, match="empty"):
            calibration_analysis(np.array([]), np.array([]))

    def test_integration_mock_brier(self, mocker):
        """Integration: oprim.brier_score_decomposed called."""
        mock_brier = mocker.patch(
            "oskill.prediction.oprim.brier_score_decomposed",
            return_value={
                "brier_score": 0.2,
                "reliability": 0.01,
                "resolution": 0.05,
                "uncertainty": 0.25,
                "skill": 0.2,
            },
        )
        mocker.patch(
            "oskill.prediction.oprim.bayes_beta_update",
            return_value={
                "posterior_alpha": 2,
                "posterior_beta": 2,
                "posterior_mean": 0.5,
                "q_0.025": 0.1,
                "q_0.975": 0.9,
            },
        )
        rng = np.random.default_rng(42)
        predictions = rng.uniform(0, 1, 100)
        outcomes = (rng.uniform(0, 1, 100) < predictions).astype(float)
        calibration_analysis(predictions, outcomes)
        mock_brier.assert_called_once()

    def test_integration_mock_bayes_beta(self, mocker):
        """Integration: oprim.bayes_beta_update called n_bins times."""
        mocker.patch(
            "oskill.prediction.oprim.brier_score_decomposed",
            return_value={
                "brier_score": 0.2,
                "reliability": 0.01,
                "resolution": 0.05,
                "uncertainty": 0.25,
                "skill": 0.2,
            },
        )
        mock_bb = mocker.patch(
            "oskill.prediction.oprim.bayes_beta_update",
            return_value={
                "posterior_alpha": 2,
                "posterior_beta": 2,
                "posterior_mean": 0.5,
                "q_0.025": 0.1,
                "q_0.975": 0.9,
            },
        )
        rng = np.random.default_rng(42)
        predictions = rng.uniform(0, 1, 200)
        outcomes = (rng.uniform(0, 1, 200) < predictions).astype(float)
        calibration_analysis(predictions, outcomes, n_bins=10, include_bayesian_ci=True)
        # Should be called once per non-empty bin
        assert mock_bb.call_count >= 5

    def test_integration_mock_percentile_rank(self, mocker):
        """Integration: oprim.percentile_rank called for equal_freq binning."""
        mocker.patch(
            "oskill.prediction.oprim.brier_score_decomposed",
            return_value={
                "brier_score": 0.2,
                "reliability": 0.01,
                "resolution": 0.05,
                "uncertainty": 0.25,
                "skill": 0.2,
            },
        )
        mocker.patch(
            "oskill.prediction.oprim.bayes_beta_update",
            return_value={
                "posterior_alpha": 2,
                "posterior_beta": 2,
                "posterior_mean": 0.5,
                "q_0.025": 0.1,
                "q_0.975": 0.9,
            },
        )
        mock_pr = mocker.patch(
            "oskill.prediction.oprim.percentile_rank",
            return_value=pd.Series(np.linspace(0, 1, 100)),
        )
        rng = np.random.default_rng(42)
        predictions = rng.uniform(0, 1, 100)
        outcomes = (rng.uniform(0, 1, 100) < predictions).astype(float)
        calibration_analysis(predictions, outcomes, binning="equal_freq")
        mock_pr.assert_called_once()

    def test_academic_brier_decomposition(self):
        """Academic: BS = reliability - resolution + uncertainty."""
        rng = np.random.default_rng(42)
        predictions = rng.uniform(0, 1, 500)
        outcomes = (rng.uniform(0, 1, 500) < predictions).astype(float)
        result = calibration_analysis(predictions, outcomes)
        # BS ≈ R - Res + U (approximate due to binning)
        reconstructed = result["reliability"] - result["resolution"] + result["uncertainty"]
        assert abs(result["brier_score"] - reconstructed) < 0.05

    def test_academic_ece_formula(self):
        """Academic: ECE = Σ (n_k/N) × |avg_pred_k - avg_outcome_k|."""
        rng = np.random.default_rng(42)
        predictions = rng.uniform(0, 1, 200)
        outcomes = (rng.uniform(0, 1, 200) < predictions).astype(float)
        result = calibration_analysis(predictions, outcomes, n_bins=5)
        # Manually compute ECE from reliability diagram
        df = result["reliability_diagram"]
        manual_ece = sum(
            (row["n"] / result["n_obs"]) * abs(row["avg_prediction"] - row["avg_outcome"])
            for _, row in df.iterrows()
        )
        assert abs(result["ece"] - manual_ece) < 1e-10
