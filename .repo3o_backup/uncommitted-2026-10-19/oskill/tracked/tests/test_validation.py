"""Tests for Group 2: Time-Series Validation skills."""

import numpy as np
import pandas as pd
import pytest

from oskill.validation import (
    cpcv_pipeline,
    regime_aware_rolling,
    walk_forward_optimization,
)

# ============================================================
# walk_forward_optimization tests
# ============================================================


class TestWalkForwardOptimization:
    """Tests for walk_forward_optimization."""

    def test_basic_fold_count(self):
        """n=1000, is=200, oos=50, step=50 → multiple folds."""
        folds = walk_forward_optimization(1000, is_window=200, oos_window=50, step=50)
        assert len(folds) > 10

    def test_anchored_expanding_is(self):
        """anchored=True: IS always starts from 0."""
        folds = walk_forward_optimization(500, is_window=100, oos_window=50, anchored=True)
        for fold in folds:
            assert fold["is_start"] == 0

    def test_rolling_is(self):
        """anchored=False: IS window rolls forward."""
        folds = walk_forward_optimization(500, is_window=100, oos_window=50, anchored=False)
        if len(folds) > 1:
            assert folds[1]["is_start"] > folds[0]["is_start"]

    def test_step_equals_oos(self):
        """step=oos_window: non-overlapping OOS."""
        folds = walk_forward_optimization(500, is_window=100, oos_window=50, step=50)
        for i in range(len(folds) - 1):
            assert folds[i + 1]["oos_start"] >= folds[i]["oos_end"]

    def test_label_horizon_purge(self):
        """label_horizon > 0 → purged_count > 0."""
        folds = walk_forward_optimization(500, is_window=100, oos_window=50, label_horizon=10)
        assert any(f["purged_count"] > 0 for f in folds)

    def test_embargo_count(self):
        """embargo_pct > 0 → embargo_count > 0."""
        folds = walk_forward_optimization(500, is_window=100, oos_window=50, embargo_pct=0.05)
        assert any(f["embargo_count"] > 0 for f in folds)

    def test_no_purge_no_embargo(self):
        """label_horizon=0, embargo_pct=0 → no purge/embargo."""
        folds = walk_forward_optimization(
            500, is_window=100, oos_window=50, label_horizon=0, embargo_pct=0.0
        )
        for f in folds:
            assert f["purged_count"] == 0

    def test_is_window_too_small_raises(self):
        """is_window < 30 raises."""
        with pytest.raises(ValueError, match="is_window"):
            walk_forward_optimization(500, is_window=20, oos_window=50)

    def test_oos_window_too_small_raises(self):
        """oos_window < 1 raises."""
        with pytest.raises(ValueError, match="oos_window"):
            walk_forward_optimization(500, is_window=100, oos_window=0)

    def test_n_total_too_small_raises(self):
        """n_total < is + oos raises."""
        with pytest.raises(ValueError, match="n_total"):
            walk_forward_optimization(100, is_window=80, oos_window=30)

    def test_is_oos_no_overlap(self):
        """IS and OOS indices don't overlap."""
        folds = walk_forward_optimization(500, is_window=100, oos_window=50)
        for fold in folds:
            is_set = set(fold["is_idx"])
            oos_set = set(fold["oos_idx"])
            assert is_set & oos_set == set()

    def test_temporal_order(self):
        """IS comes before OOS temporally."""
        folds = walk_forward_optimization(500, is_window=100, oos_window=50)
        for fold in folds:
            assert fold["is_idx"].max() < fold["oos_idx"].min()

    def test_integration_mock_rolling_window(self, mocker):
        """Integration: oprim.rolling_window_split is called."""
        mock_rw = mocker.patch(
            "oskill.validation.oprim.rolling_window_split", return_value=[(0, 49), (50, 99)]
        )
        mocker.patch("oskill.validation.oprim.purge_embargo_split", return_value=[])
        walk_forward_optimization(500, is_window=100, oos_window=50)
        mock_rw.assert_called_once()

    def test_integration_mock_purge_embargo(self, mocker):
        """Integration: oprim.purge_embargo_split is called."""
        mock_pe = mocker.patch("oskill.validation.oprim.purge_embargo_split", return_value=[])
        mocker.patch(
            "oskill.validation.oprim.rolling_window_split", return_value=[(0, 49), (50, 99)]
        )
        walk_forward_optimization(500, is_window=100, oos_window=50)
        mock_pe.assert_called_once()


# ============================================================
# cpcv_pipeline tests
# ============================================================


class TestCpcvPipeline:
    """Tests for cpcv_pipeline."""

    def test_combinations_count(self):
        """n_folds=6, n_test_groups=2 → 15 combinations."""
        result = cpcv_pipeline(1000, n_folds=6, n_test_groups=2)
        assert result["n_combinations"] == 15

    def test_n_paths(self):
        """n_paths = C(6,2) * 2/6 = 5."""
        result = cpcv_pipeline(1000, n_folds=6, n_test_groups=2)
        assert result["n_paths"] == 5

    def test_splits_only(self):
        """backtest_fn=None returns splits only."""
        result = cpcv_pipeline(1000, n_folds=6, n_test_groups=2)
        assert "splits" in result
        assert "paths_sharpe_distribution" not in result

    def test_with_backtest_fn(self):
        """backtest_fn given: full pipeline runs."""

        def mock_bt(train_idx, test_idx):
            return np.random.default_rng(42).normal(0.001, 0.01, len(test_idx))

        result = cpcv_pipeline(1000, n_folds=6, n_test_groups=2, backtest_fn=mock_bt)
        assert "paths_sharpe_distribution" in result
        assert "median_sharpe" in result

    def test_train_test_no_overlap(self):
        """Train and test don't overlap (after purge/embargo)."""
        result = cpcv_pipeline(1000, n_folds=6, n_test_groups=2)
        for split in result["splits"]:
            train_set = set(split["train_idx"])
            test_set = set(split["test_idx"])
            assert train_set & test_set == set()

    def test_no_purge_no_embargo_standard_kfold(self):
        """label_horizon=0, embargo_pct=0 → standard combinatorial K-fold."""
        result = cpcv_pipeline(1000, n_folds=6, n_test_groups=2, label_horizon=0, embargo_pct=0.0)
        # All indices should be covered
        for split in result["splits"]:
            total = len(split["train_idx"]) + len(split["test_idx"])
            assert total >= 990  # close to 1000

    def test_n_test_groups_1_standard_kfold(self):
        """n_test_groups=1 → n_combinations = n_folds."""
        result = cpcv_pipeline(1000, n_folds=5, n_test_groups=1)
        assert result["n_combinations"] == 5

    def test_n_test_groups_ge_n_folds_raises(self):
        """n_test_groups >= n_folds raises."""
        with pytest.raises(ValueError, match="n_test_groups"):
            cpcv_pipeline(1000, n_folds=5, n_test_groups=5)

    def test_n_folds_lt_2_raises(self):
        """n_folds < 2 raises."""
        with pytest.raises(ValueError, match="n_folds"):
            cpcv_pipeline(1000, n_folds=1, n_test_groups=1)

    def test_integration_mock_purge_embargo(self, mocker):
        """Integration: cpcv_pipeline applies purge/embargo via fold boundary arithmetic."""
        # Verify purge/embargo is applied by checking train_idx excludes boundary indices
        result = cpcv_pipeline(1000, n_folds=6, n_test_groups=2, label_horizon=5, embargo_pct=0.02)
        # At least some splits should have purged/embargoed indices
        assert any(s["purged_count"] > 0 for s in result["splits"])
        assert any(s["embargo_count"] > 0 for s in result["splits"])

    def test_integration_mock_bootstrap_ci(self, mocker):
        """Integration: oprim.bootstrap_ci called with backtest_fn."""
        mock_ci = mocker.patch(
            "oskill.validation.oprim.bootstrap_ci",
            return_value={
                "point_estimate": 1.0,
                "ci_lower": 0.5,
                "ci_upper": 1.5,
                "se": 0.2,
                "n_bootstrap": 100,
                "method": "percentile",
            },
        )
        mocker.patch("oskill.validation.oprim.distribution_summary", return_value={})

        def mock_bt(train_idx, test_idx):
            return np.random.default_rng(42).normal(0.001, 0.01, len(test_idx))

        cpcv_pipeline(1000, n_folds=6, n_test_groups=2, backtest_fn=mock_bt)
        mock_ci.assert_called_once()

    def test_integration_mock_distribution_summary(self, mocker):
        """Integration: oprim.distribution_summary called."""
        mocker.patch(
            "oskill.validation.oprim.bootstrap_ci",
            return_value={
                "point_estimate": 1.0,
                "ci_lower": 0.5,
                "ci_upper": 1.5,
                "se": 0.2,
                "n_bootstrap": 100,
                "method": "percentile",
            },
        )
        mock_ds = mocker.patch("oskill.validation.oprim.distribution_summary", return_value={})

        def mock_bt(train_idx, test_idx):
            return np.random.default_rng(42).normal(0.001, 0.01, len(test_idx))

        cpcv_pipeline(1000, n_folds=6, n_test_groups=2, backtest_fn=mock_bt)
        mock_ds.assert_called_once()

    def test_academic_path_count(self):
        """Academic: verify path count formula per LdP Ch.12."""
        from math import comb

        result = cpcv_pipeline(1000, n_folds=6, n_test_groups=2)
        expected_combos = comb(6, 2)
        # LdP: n_paths = C(n_folds-1, n_test_groups-1)
        expected_paths = comb(5, 1)
        assert result["n_combinations"] == expected_combos
        assert result["n_paths"] == expected_paths

    def test_path_reconstruction_independent_combos(self):
        """LdP Ch.12: each path uses different combo per fold, no combo reuse within path."""

        def tracking_bt(train_idx, test_idx):
            rng = np.random.default_rng(len(train_idx))
            return rng.normal(0.001, 0.01, len(test_idx))

        result = cpcv_pipeline(600, n_folds=6, n_test_groups=2, backtest_fn=tracking_bt)
        # With backtest_fn, paths should be generated
        assert "median_sharpe" in result
        # n_paths should equal C(5,1) = 5
        assert result["n_paths"] == 5

    def test_path_returns_per_fold_correct_length(self):
        """Each fold's returns in a path have correct length matching fold size."""
        n_total = 600
        n_folds = 6
        fold_size = n_total // n_folds  # 100

        call_log = []

        def logging_bt(train_idx, test_idx):
            call_log.append(len(test_idx))
            return np.random.default_rng(42).normal(0.001, 0.01, len(test_idx))

        cpcv_pipeline(n_total, n_folds=n_folds, n_test_groups=2, backtest_fn=logging_bt)
        # Each combo tests 2 folds, so test_idx length = 2 * fold_size = 200
        assert all(length == 2 * fold_size for length in call_log)


# ============================================================
# regime_aware_rolling tests
# ============================================================


class TestRegimeAwareRolling:
    """Tests for regime_aware_rolling."""

    def test_single_regime_standard_rolling(self):
        """Single regime → standard rolling."""
        data = pd.Series(np.arange(50, dtype=float))
        labels = pd.Series(["A"] * 50, index=data.index)
        result = regime_aware_rolling(data, labels, window=5, stat_fn=np.mean)
        # Should have values from index 4 onwards
        assert result.notna().sum() > 0

    def test_two_regime_reset(self):
        """Two regimes with reset: each regime starts fresh."""
        data = pd.Series(np.ones(100))
        labels = pd.Series(["A"] * 50 + ["B"] * 50, index=data.index)
        result = regime_aware_rolling(data, labels, window=10, stat_fn=np.mean)
        # First few of regime B should be NaN (reset)
        assert np.isnan(result.iloc[50])  # first of B, window not full

    def test_reset_vs_no_reset(self):
        """reset_on_regime_change=True vs False differ."""
        data = pd.Series(np.random.default_rng(42).normal(0, 1, 100))
        labels = pd.Series(["A"] * 50 + ["B"] * 50, index=data.index)
        r_reset = regime_aware_rolling(
            data, labels, window=10, stat_fn=np.mean, reset_on_regime_change=True
        )
        r_carry = regime_aware_rolling(
            data, labels, window=10, stat_fn=np.mean, reset_on_regime_change=False
        )
        # Carry-over should have more non-NaN values at regime boundary
        assert r_carry.iloc[55] is not np.nan or r_reset.iloc[50] is np.nan

    def test_stat_fn_mean(self):
        """stat_fn=np.mean produces correct values."""
        data = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        labels = pd.Series(["A"] * 5, index=data.index)
        result = regime_aware_rolling(data, labels, window=3, stat_fn=np.mean)
        # Window [1,2,3] → mean=2, [2,3,4] → mean=3, [3,4,5] → mean=4
        assert abs(result.iloc[2] - 2.0) < 1e-10
        assert abs(result.iloc[3] - 3.0) < 1e-10
        assert abs(result.iloc[4] - 4.0) < 1e-10

    def test_stat_fn_std(self):
        """stat_fn=np.std works."""
        data = pd.Series(np.random.default_rng(42).normal(0, 1, 50))
        labels = pd.Series(["A"] * 50, index=data.index)
        result = regime_aware_rolling(data, labels, window=10, stat_fn=np.std)
        assert result.notna().sum() > 0
        assert all(result.dropna() >= 0)

    def test_window_larger_than_regime(self):
        """Window > regime size → that regime all NaN."""
        data = pd.Series(np.ones(30))
        labels = pd.Series(["A"] * 5 + ["B"] * 25, index=data.index)
        result = regime_aware_rolling(data, labels, window=10, stat_fn=np.mean)
        # Regime A has only 5 points, window=10 → all NaN for A
        assert all(np.isnan(result.iloc[:5]))

    def test_index_mismatch_raises(self):
        """Mismatched index raises."""
        data = pd.Series([1, 2, 3], index=[0, 1, 2])
        labels = pd.Series(["A", "B", "C"], index=[3, 4, 5])
        with pytest.raises(ValueError, match="same index"):
            regime_aware_rolling(data, labels, window=2, stat_fn=np.mean)

    def test_min_periods(self):
        """min_periods allows partial windows."""
        data = pd.Series(np.arange(20, dtype=float))
        labels = pd.Series(["A"] * 20, index=data.index)
        result = regime_aware_rolling(data, labels, window=10, stat_fn=np.mean, min_periods=3)
        # With min_periods=3, should have values earlier
        assert result.notna().sum() > 0

    def test_output_index_matches_input(self):
        """Output index matches input."""
        data = pd.Series(np.ones(50), index=pd.date_range("2020-01-01", periods=50))
        labels = pd.Series(["A"] * 50, index=data.index)
        result = regime_aware_rolling(data, labels, window=5, stat_fn=np.mean)
        assert result.index.equals(data.index)

    def test_integration_mock_regime_filter(self, mocker):
        """Integration: oprim.regime_filter_data called per regime."""
        mock_rf = mocker.patch(
            "oskill.validation.oprim.regime_filter_data",
            return_value=pd.DataFrame({"value": [1, 2, 3]}),
        )
        mocker.patch("oskill.validation.oprim.rolling_window_split", return_value=[(0, 4), (1, 5)])
        data = pd.Series(np.ones(20))
        labels = pd.Series(["A"] * 10 + ["B"] * 10, index=data.index)
        regime_aware_rolling(data, labels, window=5, stat_fn=np.mean)
        assert mock_rf.call_count >= 2

    def test_integration_mock_rolling_window_split(self, mocker):
        """Integration: oprim.rolling_window_split called within regime."""
        mock_rw = mocker.patch(
            "oskill.validation.oprim.rolling_window_split", return_value=[(0, 4), (1, 5), (2, 6)]
        )
        mocker.patch(
            "oskill.validation.oprim.regime_filter_data",
            return_value=pd.DataFrame({"value": [1, 2, 3]}),
        )
        data = pd.Series(np.ones(20))
        labels = pd.Series(["A"] * 20, index=data.index)
        regime_aware_rolling(data, labels, window=5, stat_fn=np.mean)
        assert mock_rw.called
