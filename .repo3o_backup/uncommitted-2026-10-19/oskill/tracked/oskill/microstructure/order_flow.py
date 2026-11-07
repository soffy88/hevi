"""Order flow imbalance estimator (Cont-Kukanov-Stoikov 2014)."""

from __future__ import annotations

import numpy as np


def order_flow_imbalance(
    bid_volumes: np.ndarray,
    ask_volumes: np.ndarray,
    bid_prices: np.ndarray | None = None,
    ask_prices: np.ndarray | None = None,
    *,
    window: int | None = None,
    method: str = "volume",
) -> np.ndarray:
    """Order Flow Imbalance (OFI) estimator.

    Cont, Kukanov & Stoikov (2014): "The Price Impact of Order Book Events".

    Parameters
    ----------
    bid_volumes : np.ndarray
        Array of bid volume at best bid each tick.
    ask_volumes : np.ndarray
        Array of ask volume at best ask each tick.
    bid_prices : np.ndarray, optional
        Best bid prices (required for method='price_weighted').
    ask_prices : np.ndarray, optional
        Best ask prices (required for method='price_weighted').
    window : int, optional
        Rolling window size. If None, return element-wise OFI.
        If int, return rolling sum of raw imbalance over the window.
    method : str
        'volume': OFI_t = (bid_vol - ask_vol) / (bid_vol + ask_vol), in [-1, 1].
        'price_weighted': uses bid/ask price changes + volume deltas.

    Returns
    -------
    np.ndarray
        Element-wise or rolling OFI values.
    """
    bid_volumes = np.asarray(bid_volumes, dtype=float)
    ask_volumes = np.asarray(ask_volumes, dtype=float)

    if method == "volume":
        total = bid_volumes + ask_volumes
        with np.errstate(divide="ignore", invalid="ignore"):
            ofi = np.where(total > 0, (bid_volumes - ask_volumes) / total, 0.0)

        if window is not None:
            # Rolling sum of raw imbalance (un-normalized)
            raw = bid_volumes - ask_volumes
            ofi = np.array([raw[max(0, i - window + 1) : i + 1].sum() for i in range(len(raw))])
        return ofi

    elif method == "price_weighted":
        if bid_prices is None or ask_prices is None:
            raise ValueError("bid_prices and ask_prices required for method='price_weighted'")
        bid_prices = np.asarray(bid_prices, dtype=float)
        ask_prices = np.asarray(ask_prices, dtype=float)

        n = len(bid_volumes)
        ofi = np.zeros(n)

        for t in range(1, n):
            # Bid side contribution: change in bid depth weighted by price move
            delta_bid_p = bid_prices[t] - bid_prices[t - 1]
            if delta_bid_p > 0:
                bid_contrib = bid_volumes[t]
            elif delta_bid_p < 0:
                bid_contrib = -bid_volumes[t - 1]
            else:
                bid_contrib = bid_volumes[t] - bid_volumes[t - 1]

            # Ask side contribution
            delta_ask_p = ask_prices[t] - ask_prices[t - 1]
            if delta_ask_p > 0:
                ask_contrib = ask_volumes[t - 1]
            elif delta_ask_p < 0:
                ask_contrib = -ask_volumes[t]
            else:
                ask_contrib = ask_volumes[t - 1] - ask_volumes[t]

            ofi[t] = bid_contrib - ask_contrib

        if window is not None:
            ofi = np.array([ofi[max(0, i - window + 1) : i + 1].sum() for i in range(len(ofi))])
        return ofi

    else:
        raise ValueError(f"Unknown method '{method}'. Use 'volume' or 'price_weighted'.")
