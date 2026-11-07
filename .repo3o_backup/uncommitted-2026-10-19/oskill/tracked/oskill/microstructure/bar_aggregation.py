"""Information-driven and dollar bar aggregation for tick data."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _resolve_columns(columns: dict[str, str] | None) -> dict[str, str]:
    """Resolve column name mapping with defaults."""
    defaults = {"price": "price", "volume": "volume", "timestamp": "timestamp"}
    if columns:
        defaults.update(columns)
    return defaults


def dollar_bar_aggregation(
    ticks: pd.DataFrame,
    *,
    dollar_threshold: float,
    columns: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Aggregate tick data into dollar bars.

    Forms a new bar when cumulative dollar_volume (price * volume) >= dollar_threshold.

    Parameters
    ----------
    ticks : pd.DataFrame
        Tick data with at minimum price and volume columns.
    dollar_threshold : float
        Dollar volume threshold to close a bar.
    columns : dict, optional
        Column name mapping, e.g. {'price': 'px', 'volume': 'qty', 'timestamp': 'ts'}.

    Returns
    -------
    pd.DataFrame
        Bars with columns: open, high, low, close, volume, dollar_volume,
        tick_count, timestamp_start, timestamp_end.
    """
    if ticks.empty:
        return pd.DataFrame(
            columns=[
                "open",
                "high",
                "low",
                "close",
                "volume",
                "dollar_volume",
                "tick_count",
                "timestamp_start",
                "timestamp_end",
            ]
        )

    col = _resolve_columns(columns)
    has_ts = col["timestamp"] in ticks.columns

    prices = ticks[col["price"]].values.astype(float)
    volumes = ticks[col["volume"]].values.astype(float)
    timestamps = ticks[col["timestamp"]].values if has_ts else np.arange(len(ticks))

    bars: list[dict[str, Any]] = []
    bar_open = prices[0]
    bar_high = prices[0]
    bar_low = prices[0]
    bar_close = prices[0]
    bar_vol = 0.0
    bar_dv = 0.0
    bar_ticks = 0
    bar_ts_start = timestamps[0]

    for i in range(len(prices)):
        p = prices[i]
        v = volumes[i]
        dv = p * v

        bar_high = max(bar_high, p)
        bar_low = min(bar_low, p)
        bar_close = p
        bar_vol += v
        bar_dv += dv
        bar_ticks += 1

        if bar_dv >= dollar_threshold:
            bars.append(
                {
                    "open": bar_open,
                    "high": bar_high,
                    "low": bar_low,
                    "close": bar_close,
                    "volume": bar_vol,
                    "dollar_volume": bar_dv,
                    "tick_count": bar_ticks,
                    "timestamp_start": bar_ts_start,
                    "timestamp_end": timestamps[i],
                }
            )
            # Reset bar
            if i + 1 < len(prices):
                bar_open = prices[i + 1]
                bar_high = prices[i + 1]
                bar_low = prices[i + 1]
                bar_close = prices[i + 1]
                bar_ts_start = timestamps[i + 1]
            bar_vol = 0.0
            bar_dv = 0.0
            bar_ticks = 0

    return pd.DataFrame(bars)


def _compute_tick_rule(prices: np.ndarray) -> np.ndarray:
    """Compute tick rule: +1 if price up, -1 if price down, carry forward."""
    n = len(prices)
    b = np.ones(n)
    for t in range(1, n):
        diff = prices[t] - prices[t - 1]
        if diff > 0:
            b[t] = 1.0
        elif diff < 0:
            b[t] = -1.0
        else:
            b[t] = b[t - 1]  # carry forward
    return b


def volume_imbalance_bar(
    ticks: pd.DataFrame,
    *,
    expected_imbalance_method: str = "ewma",
    ewma_window: int = 50,
    static_threshold: float | None = None,
    columns: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Information-driven bar based on signed volume imbalance.

    Tick rule: b_t = sign(price_t - price_{t-1}), use +1 for first tick.
    signed_volume_t = b_t * volume_t.
    Bar forms when |cumulative_imbalance| > expected_imbalance.

    Parameters
    ----------
    ticks : pd.DataFrame
        Tick data.
    expected_imbalance_method : str
        'ewma': EWMA of absolute imbalance at previous bar boundaries.
        'static': use static_threshold directly.
    ewma_window : int
        Window for EWMA computation.
    static_threshold : float, optional
        Threshold when method='static'.
    columns : dict, optional
        Column name mapping.

    Returns
    -------
    pd.DataFrame
        Bar DataFrame with OHLCV and metadata.
    """
    if ticks.empty:
        return pd.DataFrame(
            columns=[
                "open",
                "high",
                "low",
                "close",
                "volume",
                "dollar_volume",
                "tick_count",
                "timestamp_start",
                "timestamp_end",
            ]
        )

    col = _resolve_columns(columns)
    has_ts = col["timestamp"] in ticks.columns

    prices = ticks[col["price"]].values.astype(float)
    volumes = ticks[col["volume"]].values.astype(float)
    timestamps = ticks[col["timestamp"]].values if has_ts else np.arange(len(ticks))

    b = _compute_tick_rule(prices)
    signed_vols = b * volumes

    bars: list[dict[str, Any]] = []
    prev_imbalances: list[float] = []

    # Initial expected imbalance
    if static_threshold is not None:
        expected_imb = static_threshold
    else:
        # Seed with first few ticks
        expected_imb = float(np.abs(signed_vols[: min(ewma_window, len(signed_vols))]).mean())
        if expected_imb <= 0:
            expected_imb = 1.0

    cum_imb = 0.0
    bar_open = prices[0]
    bar_high = prices[0]
    bar_low = prices[0]
    bar_close = prices[0]
    bar_vol = 0.0
    bar_dv = 0.0
    bar_ticks = 0
    bar_ts_start = timestamps[0]

    for i in range(len(prices)):
        p = prices[i]
        v = volumes[i]

        bar_high = max(bar_high, p)
        bar_low = min(bar_low, p)
        bar_close = p
        bar_vol += v
        bar_dv += p * v
        bar_ticks += 1
        cum_imb += signed_vols[i]

        if abs(cum_imb) >= expected_imb:
            bars.append(
                {
                    "open": bar_open,
                    "high": bar_high,
                    "low": bar_low,
                    "close": bar_close,
                    "volume": bar_vol,
                    "dollar_volume": bar_dv,
                    "tick_count": bar_ticks,
                    "timestamp_start": bar_ts_start,
                    "timestamp_end": timestamps[i],
                }
            )
            prev_imbalances.append(abs(cum_imb))

            # Update expected imbalance via EWMA
            if expected_imbalance_method == "ewma" and static_threshold is None:
                alpha_ema = 2.0 / (ewma_window + 1)
                expected_imb = expected_imb * (1 - alpha_ema) + abs(cum_imb) * alpha_ema
                if expected_imb <= 0:
                    expected_imb = 1.0

            # Reset
            cum_imb = 0.0
            bar_ticks = 0
            bar_vol = 0.0
            bar_dv = 0.0
            if i + 1 < len(prices):
                bar_open = prices[i + 1]
                bar_high = prices[i + 1]
                bar_low = prices[i + 1]
                bar_close = prices[i + 1]
                bar_ts_start = timestamps[i + 1]

    return pd.DataFrame(bars)


def tick_imbalance_bar(
    ticks: pd.DataFrame,
    *,
    expected_imbalance_method: str = "ewma",
    ewma_window: int = 50,
    static_threshold: float | None = None,
    columns: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Information-driven bar based on signed tick imbalance.

    Same as volume_imbalance_bar but counts signed ticks, not signed volume.
    b_t same tick rule; cumulative += b_t (not b_t * volume_t).

    Parameters
    ----------
    ticks : pd.DataFrame
        Tick data.
    expected_imbalance_method : str
        'ewma' or 'static'.
    ewma_window : int
        Window for EWMA computation.
    static_threshold : float, optional
        Threshold when method='static'.
    columns : dict, optional
        Column name mapping.

    Returns
    -------
    pd.DataFrame
        Bar DataFrame with OHLCV and metadata.
    """
    if ticks.empty:
        return pd.DataFrame(
            columns=[
                "open",
                "high",
                "low",
                "close",
                "volume",
                "dollar_volume",
                "tick_count",
                "timestamp_start",
                "timestamp_end",
            ]
        )

    col = _resolve_columns(columns)
    has_ts = col["timestamp"] in ticks.columns

    prices = ticks[col["price"]].values.astype(float)
    volumes = ticks[col["volume"]].values.astype(float)
    timestamps = ticks[col["timestamp"]].values if has_ts else np.arange(len(ticks))

    b = _compute_tick_rule(prices)  # signed ticks: +1 / -1

    bars: list[dict[str, Any]] = []

    # Initial expected imbalance
    if static_threshold is not None:
        expected_imb = static_threshold
    else:
        expected_imb = float(np.abs(b[: min(ewma_window, len(b))]).mean())
        if expected_imb <= 0:
            expected_imb = 1.0

    cum_imb = 0.0
    bar_open = prices[0]
    bar_high = prices[0]
    bar_low = prices[0]
    bar_close = prices[0]
    bar_vol = 0.0
    bar_dv = 0.0
    bar_ticks = 0
    bar_ts_start = timestamps[0]

    for i in range(len(prices)):
        p = prices[i]
        v = volumes[i]

        bar_high = max(bar_high, p)
        bar_low = min(bar_low, p)
        bar_close = p
        bar_vol += v
        bar_dv += p * v
        bar_ticks += 1
        cum_imb += b[i]

        if abs(cum_imb) >= expected_imb:
            bars.append(
                {
                    "open": bar_open,
                    "high": bar_high,
                    "low": bar_low,
                    "close": bar_close,
                    "volume": bar_vol,
                    "dollar_volume": bar_dv,
                    "tick_count": bar_ticks,
                    "timestamp_start": bar_ts_start,
                    "timestamp_end": timestamps[i],
                }
            )

            # Update expected imbalance via EWMA
            if expected_imbalance_method == "ewma" and static_threshold is None:
                alpha_ema = 2.0 / (ewma_window + 1)
                expected_imb = expected_imb * (1 - alpha_ema) + abs(cum_imb) * alpha_ema
                if expected_imb <= 0:
                    expected_imb = 1.0

            # Reset
            cum_imb = 0.0
            bar_ticks = 0
            bar_vol = 0.0
            bar_dv = 0.0
            if i + 1 < len(prices):
                bar_open = prices[i + 1]
                bar_high = prices[i + 1]
                bar_low = prices[i + 1]
                bar_close = prices[i + 1]
                bar_ts_start = timestamps[i + 1]

    return pd.DataFrame(bars)
