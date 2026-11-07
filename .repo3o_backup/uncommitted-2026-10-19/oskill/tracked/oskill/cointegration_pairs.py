"""oskill.cointegration_pairs — Pairs-trading signal from cointegrated series.

Composites:
    - oprim.cointegration_test  (Engle-Granger ADF)
    - oprim.zscore_signal       (rolling z-score of the spread)
"""

from __future__ import annotations

from typing import Any


def cointegration_pairs(
    series_a: Any,
    series_b: Any,
    *,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    lookback: int = 60,
) -> dict[str, Any]:
    """Generate a pairs-trading signal for two potentially cointegrated series.

    Composites used:
        1. oprim.cointegration_test — tests whether the pair is cointegrated
           and estimates the hedge ratio.
        2. oprim.zscore_signal     — computes the rolling z-score of the
           hedge-ratio-adjusted spread for entry/exit signals.

    Args:
        series_a: Price series A, array-like of length T.
        series_b: Price series B, array-like of length T.
        entry_z: Absolute z-score threshold to enter a position (default 2.0).
        exit_z: Absolute z-score threshold to exit (close) a position (default 0.5).
        lookback: Rolling window for z-score computation.

    Returns:
        Dict with keys:

        - ``cointegrated``  – bool from the Engle-Granger test.
        - ``hedge_ratio``   – OLS coefficient (b regressed on a).
        - ``spread``        – Residual series (b − hedge_ratio × a).
        - ``zscore``        – Latest z-score of the spread.
        - ``signal``        – ``"long_a_short_b"``, ``"short_a_long_b"``,
          ``"close"``, or ``"flat"``.
        - ``p_value``       – Cointegration test p-value.
        - ``coint_result``  – Full cointegration_test output dict.
        - ``zscore_result`` – Full zscore_signal output dict.
    """
    import numpy as np  # noqa: PLC0415
    from oprim.cointegration_test import cointegration_test  # noqa: PLC0415
    from oprim.zscore_signal import zscore_signal  # noqa: PLC0415

    a = np.asarray(series_a, dtype=float)
    b = np.asarray(series_b, dtype=float)

    coint_result = cointegration_test(a, b)
    hedge_ratio = coint_result["hedge_ratio"]

    spread = (b - hedge_ratio * a).tolist()

    effective_lookback = min(lookback, len(spread))
    if effective_lookback < 2:
        effective_lookback = 2
    zs_result = zscore_signal(spread, lookback=effective_lookback)
    z = zs_result["zscore"]

    if z <= -entry_z:
        signal = "long_a_short_b"
    elif z >= entry_z:
        signal = "short_a_long_b"
    elif abs(z) <= exit_z:
        signal = "close"
    else:
        signal = "flat"

    return {
        "cointegrated": coint_result["cointegrated"],
        "hedge_ratio": hedge_ratio,
        "spread": spread,
        "zscore": z,
        "signal": signal,
        "p_value": coint_result["p_value"],
        "coint_result": coint_result,
        "zscore_result": zs_result,
    }
