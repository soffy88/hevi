"""mean_reversion_compose: config-driven mean-reversion signal.

Indicators: VWAP z-score + Bollinger Bands + RSI + Stochastic.
Each indicator casts a per-bar vote: +1=oversold/long, -1=overbought/short, 0=neutral.
Confluence filter: emit only when ≥ min_confluence indicators agree.

ohlcv keys: 'high', 'low', 'close', 'volume' (np.ndarray, same length).
"""

from __future__ import annotations

import numpy as np
from oprim.technical import bollinger_bands, rsi_normalized, stochastic_oscillator


def mean_reversion_compose(
    ohlcv: dict[str, np.ndarray],
    *,
    config: dict,
) -> np.ndarray:
    """Config-driven mean-reversion signal: VWAP + BB + RSI + Stochastic.

    Parameters
    ----------
    ohlcv : dict
        Keys: 'close', 'volume' (required for VWAP), 'high', 'low' (for BB/Stoch).
    config : dict
        Schema::

            indicators:
              vwap:
                enabled: bool     (default true)
                window: int       (default 4, rolling window for VWAP)
                z_threshold: float (default 2.0)
              bollinger:
                enabled: bool     (default true)
                window: int       (default 20)
                num_std: float    (default 2.0)
              rsi:
                enabled: bool     (default true)
                period: int       (default 14)
                oversold: float   (default 0.3)   # in [0,1], RSI below → long
                overbought: float (default 0.7)
              stochastic:
                enabled: bool     (default true)
                k_period: int     (default 14)
                d_period: int     (default 3)
                smooth_k: int     (default 3)
                oversold: float   (default 0.2)
                overbought: float (default 0.8)
            signal_logic:
              min_confluence: int  (default 2)
              direction: str       ('both'|'long'|'short')

    Returns
    -------
    np.ndarray of int8, same length as closes.
        +1 = oversold → long, -1 = overbought → short, 0 = neutral.

    Raises
    ------
    ValueError
        If 'close' is missing or array lengths mismatch.
    ImportError
        If oprim.technical is not available.
    """
    if bollinger_bands is None:
        raise ImportError("oprim.technical is required for mean_reversion_compose")

    closes = np.asarray(ohlcv["close"], dtype=float)
    volumes = np.asarray(ohlcv.get("volume", np.ones(len(closes))), dtype=float)
    highs = np.asarray(ohlcv.get("high", closes), dtype=float)
    lows = np.asarray(ohlcv.get("low", closes), dtype=float)
    n = len(closes)

    for arr_name, arr in [("high", highs), ("low", lows), ("volume", volumes)]:
        if len(arr) != n:
            raise ValueError(f"ohlcv['{arr_name}'] length {len(arr)} != close length {n}")

    indicators_cfg = config.get("indicators", {})
    logic = config.get("signal_logic", {})
    min_confluence = int(logic.get("min_confluence", 2))
    direction_mode = logic.get("direction", "both")

    votes: list[np.ndarray] = []

    # ── VWAP z-score ──
    vwap_cfg = indicators_cfg.get("vwap", {})
    if "vwap" in indicators_cfg and vwap_cfg.get("enabled", True):
        window = int(vwap_cfg.get("window", 4))
        z_threshold = float(vwap_cfg.get("z_threshold", 2.0))
        # Rolling VWAP with lagged window (shift=1 to avoid lookahead)
        import pandas as pd

        s_c = pd.Series(closes)
        s_v = pd.Series(volumes)
        roll_vc = (s_c * s_v).rolling(window, min_periods=max(2, window // 4)).sum().shift(1)
        roll_v = s_v.rolling(window, min_periods=max(2, window // 4)).sum().shift(1)
        vwap_s = (roll_vc / (roll_v + 1e-10)).to_numpy()
        std_s = s_c.rolling(window, min_periods=max(2, window // 4)).std().shift(1).to_numpy()
        z = (closes - vwap_s) / (std_s + 1e-10)

        vote = np.zeros(n, dtype=np.int8)
        valid = ~np.isnan(vwap_s) & ~np.isnan(std_s)
        vote[valid & (z < -z_threshold)] = 1  # below VWAP → oversold → long
        vote[valid & (z > z_threshold)] = -1  # above VWAP → overbought → short
        votes.append(vote)

    # ── Bollinger Bands ──
    bb_cfg = indicators_cfg.get("bollinger", {})
    if "bollinger" in indicators_cfg and bb_cfg.get("enabled", True):
        bb = bollinger_bands(
            closes,
            window=int(bb_cfg.get("window", 20)),
            num_std=float(bb_cfg.get("num_std", 2.0)),
        )
        upper = np.asarray(bb["upper"], dtype=float)
        lower = np.asarray(bb["lower"], dtype=float)
        vote = np.zeros(n, dtype=np.int8)
        valid = ~np.isnan(upper) & ~np.isnan(lower)
        vote[valid & (closes < lower)] = 1  # below lower band → oversold
        vote[valid & (closes > upper)] = -1  # above upper band → overbought
        votes.append(vote)

    # ── RSI ──
    rsi_cfg = indicators_cfg.get("rsi", {})
    if "rsi" in indicators_cfg and rsi_cfg.get("enabled", True):
        oversold = float(rsi_cfg.get("oversold", 0.3))
        overbought = float(rsi_cfg.get("overbought", 0.7))
        rsi_s = np.asarray(
            rsi_normalized(closes, period=int(rsi_cfg.get("period", 14))), dtype=float
        )
        vote = np.zeros(n, dtype=np.int8)
        valid = ~np.isnan(rsi_s)
        vote[valid & (rsi_s < oversold)] = 1
        vote[valid & (rsi_s > overbought)] = -1
        votes.append(vote)

    # ── Stochastic ──
    st_cfg = indicators_cfg.get("stochastic", {})
    if "stochastic" in indicators_cfg and st_cfg.get("enabled", True):
        oversold = float(st_cfg.get("oversold", 0.2))
        overbought = float(st_cfg.get("overbought", 0.8))
        stoch = stochastic_oscillator(
            highs,
            lows=lows,
            closes=closes,
            k_period=int(st_cfg.get("k_period", 14)),
            d_period=int(st_cfg.get("d_period", 3)),
            smooth_k=int(st_cfg.get("smooth_k", 3)),
            normalize=True,
        )
        k = np.asarray(stoch["k"], dtype=float)
        vote = np.zeros(n, dtype=np.int8)
        valid = ~np.isnan(k)
        vote[valid & (k < oversold)] = 1
        vote[valid & (k > overbought)] = -1
        votes.append(vote)

    if not votes:
        return np.zeros(n, dtype=np.int8)

    vote_matrix = np.stack(votes, axis=1)
    long_count = np.sum(vote_matrix == 1, axis=1)
    short_count = np.sum(vote_matrix == -1, axis=1)

    signal = np.zeros(n, dtype=np.int8)
    if direction_mode in ("both", "long"):
        signal[long_count >= min_confluence] = 1
    if direction_mode in ("both", "short"):
        signal[short_count >= min_confluence] = -1

    return signal
