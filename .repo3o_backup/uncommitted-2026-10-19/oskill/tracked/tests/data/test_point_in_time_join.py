"""Tests for oskill.data.point_in_time_join (B5)."""

import pandas as pd

from oskill.data import point_in_time_join


class TestPointInTimeJoin:
    def test_standard_join(self) -> None:
        left = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=5)})
        right = pd.DataFrame({"announce_date": ["2024-01-02"], "eps": [1.5]})
        result = point_in_time_join(left=left, right=right)
        # Jan 1 should be NaN (before announce), Jan 2+ should have eps
        assert pd.isna(result.iloc[0]["eps_pit"])
        assert result.iloc[1]["eps_pit"] == 1.5

    def test_publish_lag_45_days(self) -> None:
        left = pd.DataFrame({"date": pd.date_range("2024-03-01", periods=60)})
        right = pd.DataFrame({"announce_date": ["2024-03-15"], "eps": [2.0]})
        result = point_in_time_join(left=left, right=right, publish_lag_days=45)
        # With 45-day lag, effective date = 2024-04-29
        apr28 = result[result["date"] == "2024-04-28"]
        apr29 = result[result["date"] == "2024-04-29"]
        assert pd.isna(apr28.iloc[0]["eps_pit"])
        assert apr29.iloc[0]["eps_pit"] == 2.0

    def test_right_no_match_nan(self) -> None:
        left = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3)})
        right = pd.DataFrame({"announce_date": ["2024-06-01"], "eps": [3.0]})
        result = point_in_time_join(left=left, right=right)
        assert result["eps_pit"].isna().all()

    def test_left_before_all_right_nan(self) -> None:
        left = pd.DataFrame({"date": pd.date_range("2023-01-01", periods=3)})
        right = pd.DataFrame({"announce_date": ["2024-01-01"], "eps": [1.0]})
        result = point_in_time_join(left=left, right=right)
        assert result["eps_pit"].isna().all()

    def test_multi_value_cols(self) -> None:
        left = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=5)})
        right = pd.DataFrame({"announce_date": ["2024-01-03"], "eps": [1.5], "revenue": [100]})
        result = point_in_time_join(left=left, right=right, value_cols=["eps", "revenue"])
        assert "eps_pit" in result.columns
        assert "revenue_pit" in result.columns

    def test_duplicate_as_of_takes_latest(self) -> None:
        left = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=10)})
        right = pd.DataFrame(
            {
                "announce_date": ["2024-01-03", "2024-01-05"],
                "eps": [1.0, 2.0],
            }
        )
        result = point_in_time_join(left=left, right=right)
        # After Jan 5, should use latest (2.0)
        assert result.iloc[5]["eps_pit"] == 2.0

    def test_quarterly_eps_pit_pe_fixture(self) -> None:
        """Tide business fixture: quarterly EPS with PIT semantics."""
        left = pd.DataFrame({"date": pd.date_range("2024-01-01", "2024-12-31", freq="D")})
        right = pd.DataFrame(
            {
                "announce_date": ["2024-04-20", "2024-08-15", "2024-10-30"],
                "eps": [5.0, 6.0, 7.0],  # Q1, Q2, Q3
            }
        )
        result = point_in_time_join(left=left, right=right)
        # Before Apr 20: NaN
        jan_rows = result[result["date"] < "2024-04-20"]
        assert jan_rows["eps_pit"].isna().all()
        # Apr 20 - Aug 14: Q1 EPS = 5.0
        may_row = result[result["date"] == "2024-05-01"]
        assert may_row.iloc[0]["eps_pit"] == 5.0
        # Aug 15+: Q2 EPS = 6.0
        sep_row = result[result["date"] == "2024-09-01"]
        assert sep_row.iloc[0]["eps_pit"] == 6.0

    def test_no_lookahead_bias(self) -> None:
        """Strict: 2024-08-14 must NOT see Q2 EPS announced 2024-08-15."""
        left = pd.DataFrame({"date": ["2024-08-14", "2024-08-15"]})
        right = pd.DataFrame(
            {
                "announce_date": ["2024-04-20", "2024-08-15"],
                "eps": [5.0, 6.0],
            }
        )
        result = point_in_time_join(left=left, right=right)
        # Aug 14 should use Q1 EPS (5.0), NOT Q2 (6.0)
        assert result.iloc[0]["eps_pit"] == 5.0
        # Aug 15 should use Q2 EPS (6.0)
        assert result.iloc[1]["eps_pit"] == 6.0
