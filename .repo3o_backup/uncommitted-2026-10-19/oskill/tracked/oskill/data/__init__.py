"""B5 — Point-in-time join (prevents lookahead bias)."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from oskill.data.calendar_surprise_detect import calendar_surprise_detect


def point_in_time_join(
    *,
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_on: str = "date",
    right_on: str = "announce_date",
    value_cols: list[str] | None = None,
    publish_lag_days: int = 0,
    tolerance: str | timedelta | None = None,
) -> pd.DataFrame:
    """Join right table to left using point-in-time semantics (no lookahead).

    Parameters
    ----------
    left : DataFrame with date column (the timeline to join onto)
    right : DataFrame with announce_date and value columns
    left_on : date column in left
    right_on : announce/publish date column in right
    value_cols : columns from right to bring over (all non-key cols if None)
    publish_lag_days : additional lag to add to right dates
    tolerance : max backward look (pd.Timedelta string or timedelta)

    Returns
    -------
    DataFrame = left + value columns with _pit suffix.
    """
    left_sorted = left.sort_values(left_on).copy()
    right_sorted = right.sort_values(right_on).copy()

    # Apply publish lag
    right_sorted["_pit_effective_date"] = pd.to_datetime(right_sorted[right_on]) + timedelta(
        days=publish_lag_days
    )

    # Determine value columns
    if value_cols is None:
        value_cols = [c for c in right_sorted.columns if c not in (right_on, "_pit_effective_date")]

    # Prepare for merge_asof
    left_sorted["_pit_left_dt"] = pd.to_datetime(left_sorted[left_on])

    tol = pd.Timedelta(tolerance) if isinstance(tolerance, str) else tolerance

    merged = pd.merge_asof(
        left_sorted.sort_values("_pit_left_dt"),
        right_sorted[["_pit_effective_date"] + value_cols].sort_values("_pit_effective_date"),
        left_on="_pit_left_dt",
        right_on="_pit_effective_date",
        direction="backward",
        tolerance=tol,
    )

    # Rename value cols with _pit suffix
    rename_map = {c: f"{c}_pit" for c in value_cols}
    merged = merged.rename(columns=rename_map)

    # Clean up temp columns
    merged = merged.drop(columns=["_pit_left_dt", "_pit_effective_date"], errors="ignore")
    return merged
