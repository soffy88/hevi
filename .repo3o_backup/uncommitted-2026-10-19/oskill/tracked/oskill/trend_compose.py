"""trend_signal_compose: config-driven trend signal using SuperTrend + EMA + ADX + MACD.

Each indicator produces a per-bar directional vote (+1=long, -1=short, 0=neutral).
Confluence filter: only emit signal when ≥ min_confluence indicators agree.

ohlcv keys expected: 'high', 'low', 'close', 'volume' (np.ndarray, same length).
"""

from __future__ import annotations

import numpy as np
from oprim.technical import adx_series, ema, macd, supertrend


def trend_signal_compose(
    ohlcv: dict[str, np.ndarray],
    *,
    config: dict,
) -> np.ndarray:
    """Config-driven trend signal: SuperTrend + EMA crossover + ADX + MACD.

    Parameters
    ----------
    ohlcv : dict
        Keys: 'high', 'low', 'close' (required); 'open', 'volume' (optional).
        All arrays must have the same length.
    config : dict
        Schema::

            indicators:
              supertrend:
                enabled: bool   (default true)
                period: int     (default 10)
                multiplier: float (default 3.0)
              ema:
                enabled: bool   (default true)
                fast: int       (default 20)
                slow: int       (default 50)
              adx:
                enabled: bool   (default true)
                period: int     (default 14)
                threshold: float  (default 25.0)  # ADX must exceed this
              macd:
                enabled: bool   (default true)
                fast: int       (default 12)
                slow: int       (default 26)
                signal: int     (default 9)
            signal_logic:
              min_confluence: int  (default 2)  # indicators must agree
              direction: str       ('both'|'long'|'short')

    Returns
    -------
    np.ndarray of int8, same length as closes.
        +1 = long, -1 = short, 0 = neutral.

    Raises
    ------
    ValueError
        If 'close' is missing or arrays have different lengths.
    ImportError
        If oprim.technical is not available.
    """
    if adx_series is None or ema is None or macd is None or supertrend is None:
        raise ImportError("oprim.technical is required for trend_signal_compose")

    closes = np.asarray(ohlcv["close"], dtype=float)
    highs = np.asarray(ohlcv.get("high", closes), dtype=float)
    lows = np.asarray(ohlcv.get("low", closes), dtype=float)
    n = len(closes)

    if len(highs) != n or len(lows) != n:
        raise ValueError("ohlcv arrays must all have the same length")

    indicators_cfg = config.get("indicators", {})
    logic = config.get("signal_logic", {})
    min_confluence = int(logic.get("min_confluence", 2))
    direction_mode = logic.get("direction", "both")

    # Accumulate per-bar votes: list of (n,) int8 arrays
    votes: list[np.ndarray] = []

    # ── SuperTrend ──
    st_cfg = indicators_cfg.get("supertrend", {})
    if "supertrend" in indicators_cfg and st_cfg.get("enabled", True):
        st = supertrend(
            highs,
            lows,
            closes,
            period=int(st_cfg.get("period", 10)),
            multiplier=float(st_cfg.get("multiplier", 3.0)),
        )
        d = st["direction"]
        vote = np.where(np.isnan(d), 0, np.sign(d)).astype(np.int8)
        votes.append(vote)

    # ── EMA crossover ──
    em_cfg = indicators_cfg.get("ema", {})
    if "ema" in indicators_cfg and em_cfg.get("enabled", True):
        fast_ema = ema(closes, window=int(em_cfg.get("fast", 20)))
        slow_ema = ema(closes, window=int(em_cfg.get("slow", 50)))
        f = np.asarray(fast_ema, dtype=float)
        s = np.asarray(slow_ema, dtype=float)
        vote = np.zeros(n, dtype=np.int8)
        valid = ~np.isnan(f) & ~np.isnan(s)
        vote[valid & (f > s)] = 1
        vote[valid & (f < s)] = -1
        votes.append(vote)

    # ── ADX filter (uses direction from +DI vs -DI) ──
    adx_cfg = indicators_cfg.get("adx", {})
    if "adx" in indicators_cfg and adx_cfg.get("enabled", True):
        adx_period = int(adx_cfg.get("period", 14))
        adx_threshold = float(adx_cfg.get("threshold", 25.0))
        adx_result = adx_series(highs, lows, closes, period=adx_period)
        adx_v = np.asarray(adx_result["adx"], dtype=float)
        plus_di = np.asarray(adx_result["plus_di"], dtype=float)
        minus_di = np.asarray(adx_result["minus_di"], dtype=float)
        vote = np.zeros(n, dtype=np.int8)
        trending = (~np.isnan(adx_v)) & (adx_v > adx_threshold)
        vote[trending & (plus_di > minus_di)] = 1
        vote[trending & (minus_di > plus_di)] = -1
        votes.append(vote)

    # ── MACD ──
    mc_cfg = indicators_cfg.get("macd", {})
    if "macd" in indicators_cfg and mc_cfg.get("enabled", True):
        mc = macd(
            closes,
            fast_period=int(mc_cfg.get("fast", 12)),
            slow_period=int(mc_cfg.get("slow", 26)),
            signal_period=int(mc_cfg.get("signal", 9)),
        )
        m_line = np.asarray(mc["macd"], dtype=float)
        s_line = np.asarray(mc["signal"], dtype=float)
        vote = np.zeros(n, dtype=np.int8)
        valid = ~np.isnan(m_line) & ~np.isnan(s_line)
        vote[valid & (m_line > s_line)] = 1
        vote[valid & (m_line < s_line)] = -1
        votes.append(vote)

    if not votes:
        return np.zeros(n, dtype=np.int8)

    # Confluence: count agreements
    vote_matrix = np.stack(votes, axis=1)  # (n, n_indicators)
    long_count = np.sum(vote_matrix == 1, axis=1)
    short_count = np.sum(vote_matrix == -1, axis=1)

    signal = np.zeros(n, dtype=np.int8)
    if direction_mode in ("both", "long"):
        signal[long_count >= min_confluence] = 1
    if direction_mode in ("both", "short"):
        signal[short_count >= min_confluence] = -1

    return signal
