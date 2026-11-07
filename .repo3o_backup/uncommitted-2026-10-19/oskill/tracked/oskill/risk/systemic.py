"""Systemic risk metrics: CoVaR, MES, SRISK."""

from __future__ import annotations

from typing import Literal

import numpy as np


def systemic_risk_metrics(
    institution_returns: np.ndarray,
    market_returns: np.ndarray,
    *,
    metrics: list[Literal["covar", "mes", "srisk"]] | None = None,
    quantile: float = 0.05,
    leverage: np.ndarray | None = None,
    market_cap: np.ndarray | None = None,
    prudential_capital_ratio: float = 0.08,
) -> dict[str, np.ndarray]:
    """Compute systemic risk metrics for a panel of institutions.

    Parameters
    ----------
    institution_returns:
        Array of shape (T, N).
    market_returns:
        Array of shape (T,) or (T, 1).
    metrics:
        Subset of ["covar", "mes", "srisk"]. Defaults to ["covar", "mes"].
    quantile:
        Tail quantile level (default 0.05 = 5th percentile).
    leverage:
        (N,) debt-to-equity ratios, required for SRISK.
    market_cap:
        (N,) market capitalizations, required for SRISK.
    prudential_capital_ratio:
        Capital ratio k used in SRISK formula (default 0.08).

    Returns
    -------
    dict mapping metric name to ndarray of shape (N,).
    """
    institution_returns = np.asarray(institution_returns, dtype=float)
    market_returns = np.asarray(market_returns, dtype=float).ravel()

    if institution_returns.ndim != 2:
        raise ValueError("institution_returns must be 2-D array (T, N)")
    T, N = institution_returns.shape
    if len(market_returns) != T:
        raise ValueError(f"market_returns length {len(market_returns)} != T={T}")

    if metrics is None:
        metrics = ["covar", "mes"]

    results: dict[str, np.ndarray] = {}

    # Pre-compute market distress index for MES
    market_distress_threshold = float(np.percentile(market_returns, quantile * 100))
    market_distress_idx = market_returns <= market_distress_threshold

    covar_arr = np.zeros(N)
    mes_arr = np.zeros(N)

    for i in range(N):
        inst_i = institution_returns[:, i]

        if "covar" in metrics:
            distress_threshold = float(np.percentile(inst_i, quantile * 100))
            distress_idx = inst_i <= distress_threshold
            # Median state: institution between 45th and 55th percentile
            p45 = float(np.percentile(inst_i, 45))
            p55 = float(np.percentile(inst_i, 55))
            median_idx = (inst_i >= p45) & (inst_i <= p55)

            if distress_idx.sum() >= 2 and median_idx.sum() >= 2:
                q_distress = float(np.percentile(market_returns[distress_idx], quantile * 100))
                q_median = float(np.percentile(market_returns[median_idx], quantile * 100))
                covar_arr[i] = q_distress - q_median
            else:
                covar_arr[i] = 0.0

        if "mes" in metrics:
            if market_distress_idx.sum() > 0:
                mes_arr[i] = float(np.mean(inst_i[market_distress_idx]))
            else:
                mes_arr[i] = 0.0

    if "covar" in metrics:
        results["covar"] = covar_arr

    if "mes" in metrics:
        results["mes"] = mes_arr

    if "srisk" in metrics:
        if leverage is None or market_cap is None:
            results["srisk"] = np.zeros(N)
        else:
            leverage = np.asarray(leverage, dtype=float)
            market_cap = np.asarray(market_cap, dtype=float)
            # Ensure MES computed
            if "mes" not in results:
                for i in range(N):
                    inst_i = institution_returns[:, i]
                    if market_distress_idx.sum() > 0:
                        mes_arr[i] = float(np.mean(inst_i[market_distress_idx]))
            # LRMES: long-run MES approximation (6-month ~ 126 trading days)
            lrmes = 1 - np.exp(18 * mes_arr)
            debt = leverage * market_cap
            k = prudential_capital_ratio
            srisk = np.maximum(
                0.0,
                k * debt - (1 - k) * (1 - lrmes) * market_cap,
            )
            results["srisk"] = srisk

    return results
