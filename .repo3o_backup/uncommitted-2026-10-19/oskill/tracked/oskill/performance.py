"""Group 1: Performance Evaluation skills."""

from __future__ import annotations

import warnings
from typing import Literal

import numpy as np
import oprim
import pandas as pd
from scipy import stats as scipy_stats


def bootstrap_sharpe(
    returns: np.ndarray,
    *,
    n_bootstrap: int = 1000,
    confidence_level: float = 0.95,
    annualization_factor: float = 252.0,
    method: Literal["percentile", "bca"] = "percentile",
    risk_free_rate: float | np.ndarray = 0.0,
    random_state: int | None = None,
) -> dict:
    """Bootstrap distribution of Sharpe ratio with confidence interval.

    Calls:
        oprim.bootstrap_ci, oprim.sharpe_ratio

    Args:
        returns: Array of returns.
        n_bootstrap: Number of bootstrap resamples.
        confidence_level: CI confidence level.
        annualization_factor: Annualization factor (252 equity, 365 crypto).
        method: CI method ('percentile' or 'bca').
        risk_free_rate: Risk-free rate (scalar or array).
        random_state: Random seed.

    Returns:
        Dict with sharpe, ci_low, ci_high, se, samples, n_bootstrap, confidence_level, method.

    Raises:
        ValueError: If returns is empty or all NaN.
    """
    returns = np.asarray(returns, dtype=np.float64)
    valid = returns[~np.isnan(returns)]
    if valid.size == 0:
        raise ValueError("returns must not be empty or all NaN")
    if valid.size < 10:
        warnings.warn("Sample size < 10 may give unreliable bootstrap estimates", stacklevel=2)

    # Compute point estimate using oprim.sharpe_ratio
    rf = risk_free_rate
    sharpe_point = oprim.sharpe_ratio(
        pd.Series(valid),
        risk_free_rate=float(rf) if np.isscalar(rf) else pd.Series(rf[: len(valid)]),
        annualization_factor=int(annualization_factor),
    )

    # Define statistic for bootstrap
    def _sharpe_stat(sample: np.ndarray) -> float:
        return oprim.sharpe_ratio(
            pd.Series(sample),
            risk_free_rate=float(rf) if np.isscalar(rf) else pd.Series(rf[: len(sample)]),
            annualization_factor=int(annualization_factor),
        )

    # Use oprim.bootstrap_ci for CI
    ci_result = oprim.bootstrap_ci(
        valid,
        statistic_fn=_sharpe_stat,
        n_bootstrap=n_bootstrap,
        confidence_level=confidence_level,
        method=method,
        random_state=random_state,
    )

    # Generate samples for distribution (using same seed for reproducibility)
    rng = np.random.default_rng(random_state)
    indices = rng.integers(0, len(valid), size=(n_bootstrap, len(valid)))
    samples = np.array([_sharpe_stat(valid[idx]) for idx in indices])

    return {
        "sharpe": float(sharpe_point),
        "ci_low": float(ci_result["ci_lower"]),
        "ci_high": float(ci_result["ci_upper"]),
        "se": float(ci_result["se"]),
        "samples": samples,
        "n_bootstrap": n_bootstrap,
        "confidence_level": confidence_level,
        "method": method,
    }


def psr_dsr(
    returns: np.ndarray,
    *,
    benchmark_sharpe: float = 0.0,
    n_strategies_tested: int | None = None,
    n_eff: float | None = None,
    annualization_factor: float = 252.0,
    bootstrap_ci: bool = False,
    n_bootstrap: int = 1000,
) -> dict:
    """Probabilistic Sharpe Ratio (PSR) and Deflated Sharpe Ratio (DSR).

    Calls:
        oprim.sharpe_ratio, oprim.skew_kurt_robust, oprim.bootstrap_ci (optional)

    Args:
        returns: Array of returns.
        benchmark_sharpe: Benchmark SR for PSR comparison (non-annualized scale).
        n_strategies_tested: Number of strategies tested (for DSR).
        n_eff: Effective number of independent strategies (overrides n_strategies_tested).
        annualization_factor: Annualization factor.
        bootstrap_ci: Whether to compute bootstrap CI for PSR.
        n_bootstrap: Number of bootstrap resamples.

    Returns:
        Dict with psr, psr_ci, dsr, sharpe_observed, skewness, excess_kurtosis, etc.

    Raises:
        ValueError: If returns is empty.

    References:
        Bailey & López de Prado 2012, 2014.
    """
    returns = np.asarray(returns, dtype=np.float64)
    valid = returns[~np.isnan(returns)]
    if valid.size == 0:
        raise ValueError("returns must not be empty or all NaN")

    warn_list: list[str] = []
    if valid.size < 30:
        warn_list.append(f"T={valid.size} < 30: PSR estimate may be unreliable")
        warnings.warn(warn_list[-1], stacklevel=2)

    T = len(valid)

    # Compute observed Sharpe (non-annualized for PSR formula)
    sr_annualized = oprim.sharpe_ratio(
        pd.Series(valid), annualization_factor=int(annualization_factor)
    )
    # Non-annualized SR for PSR formula
    sr_obs = sr_annualized / np.sqrt(annualization_factor)

    # Get skewness and kurtosis using oprim
    sk = oprim.skew_kurt_robust(valid, bias=False)
    gamma3 = sk["skewness"]
    gamma4 = sk["kurtosis_excess"]

    # PSR formula: PSR(SR*) = Φ((SR_obs - SR*) × √(T-1) / √(1 - γ3*SR_obs + (γ4-1)/4 * SR_obs²))
    sr_star = benchmark_sharpe
    numerator = (sr_obs - sr_star) * np.sqrt(T - 1)
    denominator_sq = 1 - gamma3 * sr_obs + (gamma4 - 1) / 4 * sr_obs**2
    if denominator_sq <= 0:
        warn_list.append("PSR denominator non-positive; setting PSR=NaN")
        psr_val = np.nan
    else:
        denominator = np.sqrt(denominator_sq)
        psr_val = float(scipy_stats.norm.cdf(numerator / denominator))

    # DSR computation
    dsr_val = None
    n_eff_used = None
    if n_strategies_tested is not None or n_eff is not None:
        N = n_eff if n_eff is not None else float(n_strategies_tested)  # type: ignore[arg-type]
        n_eff_used = N
        if N <= 1:
            dsr_val = psr_val
        else:
            # SR_threshold ≈ √(2 ln N) - (γ_E + ln(ln N)) / (2√(2 ln N))
            euler_mascheroni = 0.5772156649
            ln_N = np.log(N)
            sqrt_2lnN = np.sqrt(2 * ln_N)
            sr_threshold = sqrt_2lnN - (euler_mascheroni + np.log(ln_N)) / (2 * sqrt_2lnN)
            # DSR = PSR(SR_threshold)
            num_dsr = (sr_obs - sr_threshold) * np.sqrt(T - 1)
            if denominator_sq <= 0:
                dsr_val = np.nan
            else:
                dsr_val = float(scipy_stats.norm.cdf(num_dsr / np.sqrt(denominator_sq)))

    # Optional bootstrap CI for PSR
    psr_ci_val = None
    if bootstrap_ci:

        def _psr_stat(sample: np.ndarray) -> float:
            sr_s = oprim.sharpe_ratio(
                pd.Series(sample), annualization_factor=int(annualization_factor)
            ) / np.sqrt(annualization_factor)
            sk_s = oprim.skew_kurt_robust(sample, bias=False)
            g3, g4 = sk_s["skewness"], sk_s["kurtosis_excess"]
            n = (sr_s - sr_star) * np.sqrt(len(sample) - 1)
            d_sq = 1 - g3 * sr_s + (g4 - 1) / 4 * sr_s**2
            if d_sq <= 0:
                return np.nan
            return float(scipy_stats.norm.cdf(n / np.sqrt(d_sq)))

        ci_result = oprim.bootstrap_ci(valid, statistic_fn=_psr_stat, n_bootstrap=n_bootstrap)
        psr_ci_val = (ci_result["ci_lower"], ci_result["ci_upper"])

    return {
        "psr": psr_val,
        "psr_ci": psr_ci_val,
        "dsr": dsr_val,
        "sharpe_observed": float(sr_obs),
        "sharpe_observed_annualized": float(sr_annualized),
        "skewness": float(gamma3),
        "excess_kurtosis": float(gamma4),
        "n_obs": T,
        "n_eff_used": n_eff_used,
        "warnings": warn_list,
    }


def factor_attribution(
    asset_returns: np.ndarray,
    factor_returns: pd.DataFrame,
    *,
    bootstrap_ci_enabled: bool = True,
    n_bootstrap: int = 1000,
    confidence_level: float = 0.95,
    standard_errors: Literal["ols", "white", "newey_west"] = "newey_west",
    nw_lags: int | None = None,
    handle_nan: Literal["pairwise", "drop", "raise"] = "drop",
    random_state: int | None = None,
) -> dict:
    """Fama-French style factor attribution with bootstrap CI.

    Calls:
        oprim.beta_alpha_ols, oprim.bootstrap_ci

    Args:
        asset_returns: Asset return series.
        factor_returns: DataFrame with factor returns (columns = factor names).
        bootstrap_ci_enabled: Whether to compute bootstrap CI.
        n_bootstrap: Number of bootstrap resamples.
        confidence_level: CI confidence level.
        standard_errors: SE method ('ols', 'white', 'newey_west').
        nw_lags: Newey-West lags (None = auto).
        handle_nan: NaN handling strategy.
        random_state: Random seed.

    Returns:
        Dict with alpha, betas, standard errors, t-stats, p-values, R², CI.

    Raises:
        ValueError: If inputs are invalid.

    References:
        Fama & French 1993, 2015.
    """
    asset_returns = np.asarray(asset_returns, dtype=np.float64)
    if not isinstance(factor_returns, pd.DataFrame):
        raise ValueError("factor_returns must be a pandas DataFrame")

    factor_names = list(factor_returns.columns)

    # Handle NaN
    asset_s = pd.Series(asset_returns)
    combined = pd.concat([asset_s.rename("asset"), factor_returns], axis=1)
    if handle_nan == "drop":
        combined = combined.dropna()
    elif handle_nan == "raise":
        if combined.isna().any().any():
            raise ValueError("NaN values found in inputs")
    # pairwise: keep as-is, let OLS handle

    if len(combined) < 3:
        raise ValueError(f"Insufficient observations: {len(combined)} < 3")

    asset_clean = combined["asset"]
    factors_clean = combined[factor_names]

    # Use oprim.beta_alpha_ols
    use_hac = standard_errors == "newey_west"
    ols_result = oprim.beta_alpha_ols(
        asset_clean,
        market_returns=factors_clean,
        use_hac=use_hac,
        hac_lags=nw_lags,
    )

    alpha = ols_result["alpha"]
    betas_raw = ols_result["beta"]
    alpha_se = ols_result["alpha_se"]
    betas_se_raw = ols_result["beta_se"]
    r_squared = ols_result["r_squared"]
    adj_r_squared = ols_result["adj_r_squared"]
    n_obs = ols_result["n_samples"]
    p_values = ols_result["p_values"]

    # Normalize betas to dict
    if isinstance(betas_raw, dict):
        betas = betas_raw
        betas_se = betas_se_raw
    else:
        betas = {factor_names[0]: float(betas_raw)}
        betas_se = {factor_names[0]: float(betas_se_raw)}

    # Compute t-stats and p-values
    alpha_tstat = alpha / alpha_se if alpha_se > 0 else np.nan
    alpha_pvalue = p_values.get("alpha", np.nan)

    betas_tstat = {}
    betas_pvalue = {}
    for fn in factor_names:
        se_val = betas_se.get(fn, 0)
        betas_tstat[fn] = betas[fn] / se_val if se_val > 0 else np.nan
        betas_pvalue[fn] = p_values.get(fn, np.nan)

    # Bootstrap CI
    alpha_ci = None
    betas_ci = None
    if bootstrap_ci_enabled:
        asset_arr = asset_clean.values
        factors_arr = factors_clean.values
        joint = np.column_stack([asset_arr, factors_arr])
        rng = np.random.default_rng(random_state)
        n_samples = len(joint)

        # Use oprim.bootstrap_ci for alpha CI
        def _alpha_stat(data: np.ndarray) -> float:
            boot_idx = rng.integers(0, n_samples, size=n_samples)
            r = oprim.beta_alpha_ols(
                pd.Series(joint[boot_idx, 0]),
                market_returns=pd.DataFrame(joint[boot_idx, 1:], columns=factor_names),
            )
            return r["alpha"]

        ci_alpha = oprim.bootstrap_ci(
            asset_arr,
            statistic_fn=_alpha_stat,
            n_bootstrap=n_bootstrap,
            confidence_level=confidence_level,
            random_state=random_state,
        )
        alpha_ci = (ci_alpha["ci_lower"], ci_alpha["ci_upper"])

        # Paired bootstrap for betas CI
        rng2 = np.random.default_rng(random_state)
        betas_boots = {fn: np.empty(n_bootstrap) for fn in factor_names}
        for i in range(n_bootstrap):
            boot_idx = rng2.integers(0, n_samples, size=n_samples)
            r = oprim.beta_alpha_ols(
                pd.Series(joint[boot_idx, 0]),
                market_returns=pd.DataFrame(joint[boot_idx, 1:], columns=factor_names),
            )
            b = r["beta"]
            if isinstance(b, dict):
                for fn in factor_names:
                    betas_boots[fn][i] = b[fn]
            else:
                betas_boots[factor_names[0]][i] = float(b)

        lo = (1 - confidence_level) / 2
        hi = 1 - lo
        betas_ci = {}
        for fn in factor_names:
            betas_ci[fn] = (
                float(np.nanpercentile(betas_boots[fn], lo * 100)),
                float(np.nanpercentile(betas_boots[fn], hi * 100)),
            )

    return {
        "alpha": float(alpha),
        "alpha_se": float(alpha_se),
        "alpha_tstat": float(alpha_tstat),
        "alpha_pvalue": float(alpha_pvalue),
        "alpha_ci": alpha_ci,
        "betas": {k: float(v) for k, v in betas.items()},
        "betas_se": {k: float(v) for k, v in betas_se.items()},
        "betas_tstat": {k: float(v) for k, v in betas_tstat.items()},
        "betas_pvalue": {k: float(v) for k, v in betas_pvalue.items()},
        "betas_ci": betas_ci,
        "r_squared": float(r_squared),
        "adj_r_squared": float(adj_r_squared),
        "n_obs": int(n_obs),
        "factor_names": factor_names,
        "standard_errors_method": standard_errors,
    }


def regime_aware_performance(
    returns: pd.Series,
    regime_labels: pd.Series,
    *,
    metrics: list[str] | None = None,
    annualization_factor: float = 252.0,
    var_confidence: float = 0.95,
    var_method: Literal["historical", "parametric", "cornish_fisher"] = "historical",
    include_overall: bool = True,
) -> pd.DataFrame:
    """Per-regime performance breakdown.

    Calls:
        oprim.regime_filter_data, oprim.sharpe_ratio, oprim.drawdown_curve, oprim.value_at_risk

    Args:
        returns: Return series.
        regime_labels: Regime label series (same index as returns).
        metrics: List of metrics to compute. Default: sharpe, max_drawdown, var_95, cumulative_return.
        annualization_factor: Annualization factor.
        var_confidence: VaR confidence level.
        var_method: VaR method.
        include_overall: Whether to include OVERALL row.

    Returns:
        DataFrame with regimes as index and metrics as columns.

    Raises:
        ValueError: If returns and regime_labels have mismatched index.
    """
    if metrics is None:
        metrics = ["sharpe", "max_drawdown", "var_95", "cumulative_return"]

    if not isinstance(returns, pd.Series):
        returns = pd.Series(returns)
    if not isinstance(regime_labels, pd.Series):
        regime_labels = pd.Series(regime_labels, index=returns.index)

    if not returns.index.equals(regime_labels.index):
        raise ValueError("returns and regime_labels must have the same index")

    regimes = sorted(regime_labels.unique())
    results = {}

    def _compute_metrics(ret_series: pd.Series, label: str) -> dict:
        row: dict[str, float] = {}
        n = len(ret_series)
        row["n_obs"] = float(n)

        if n < 2:
            for m in metrics:
                if m != "n_obs":
                    row[m] = np.nan
            return row

        for m in metrics:
            if m == "sharpe":
                if n < 30:
                    row[m] = np.nan
                else:
                    row[m] = oprim.sharpe_ratio(
                        ret_series, annualization_factor=int(annualization_factor)
                    )
            elif m == "max_drawdown":
                dd = oprim.drawdown_curve(ret_series, input_type="returns")
                row[m] = dd["max_drawdown"]
            elif m.startswith("var_"):
                conf = var_confidence
                var_result = oprim.value_at_risk(
                    ret_series, confidence_level=conf, method=var_method
                )
                row[m] = -var_result["var"]  # negative convention
            elif m == "cumulative_return":
                row[m] = float((1 + ret_series).prod() - 1)
        return row

    # Per-regime computation
    returns_df = pd.DataFrame({"returns": returns})
    for regime in regimes:
        filtered = oprim.regime_filter_data(returns_df, regime_labels=regime_labels, target_regime=regime)
        ret_s = filtered["returns"]
        results[regime] = _compute_metrics(ret_s, regime)

    # Overall
    if include_overall:
        results["OVERALL"] = _compute_metrics(returns, "OVERALL")

    # Build DataFrame
    all_cols = [m for m in metrics] + (["n_obs"] if "n_obs" not in metrics else [])
    df = pd.DataFrame(results).T
    # Reorder columns
    cols = [c for c in all_cols if c in df.columns]
    return df[cols]


# ── Sprint 0 additions (v2.5.0) ──────────────────────────────────────────────

STABILITY_NEW = "experimental"  # for Sprint 0 additions only


def portfolio_metrics_summary(
    trades: list[dict],
    equity_curve: list[tuple],
    initial_capital: float,
) -> dict:
    """Compute summary performance metrics for a backtest run.

    Parameters
    ----------
    trades : list of {"entry_date": date, "exit_date": date,
                      "pnl": float, "pnl_pct": float}
    equity_curve : [(date, equity_value), ...] sorted ascending
    initial_capital : starting capital

    Returns
    -------
    {
        "total_return_pct": float,
        "cagr": float,
        "sharpe_ratio": float,
        "max_drawdown_pct": float,
        "win_rate": float,
        "profit_loss_ratio": float,
        "n_trades": int,
        "avg_holding_days": float
    }

    Methodology
    -----------
    Combines oprim.finance.sharpe_ratio + oprim.finance.drawdown_curve +
    oprim.performance.cagr into a single summary report.

    Uses: oprim.finance, oprim.performance

    Reference
    ---------
    Bailey & Lopez de Prado (2014). The Deflated Sharpe Ratio.
    """

    n_trades = len(trades)

    if not equity_curve or initial_capital <= 0:
        return {
            "total_return_pct": 0.0,
            "cagr": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "win_rate": 0.0,
            "profit_loss_ratio": 0.0,
            "n_trades": n_trades,
            "avg_holding_days": 0.0,
        }

    final_equity = equity_curve[-1][1]
    total_return_pct = (final_equity - initial_capital) / initial_capital * 100

    # CAGR using oprim
    start_date = equity_curve[0][0]
    end_date = equity_curve[-1][0]
    years = max((end_date - start_date).days / 365.25, 1 / 365.25)
    cagr_val = oprim.cagr(pd.Series([initial_capital, final_equity]), periods_per_year=1 / years)

    # Daily returns from equity curve for Sharpe
    equity_vals = [v for _, v in equity_curve]
    if len(equity_vals) >= 2:
        daily_rets = pd.Series(
            [
                (equity_vals[i] - equity_vals[i - 1]) / equity_vals[i - 1]
                for i in range(1, len(equity_vals))
            ]
        )
        sharpe = float(oprim.sharpe_ratio(daily_rets, annualization_factor=252))
    else:
        sharpe = 0.0

    # Max drawdown using oprim.drawdown_curve
    eq_series = pd.Series(equity_vals)
    dd_curve = oprim.drawdown_curve(eq_series)
    max_drawdown_pct = float(dd_curve["max_drawdown"]) * 100

    # Trade statistics
    if trades:
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) <= 0]
        win_rate = len(wins) / n_trades
        avg_win = sum(t.get("pnl", 0) for t in wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(t.get("pnl", 0) for t in losses) / len(losses)) if losses else 0.0
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")

        holding_days = []
        for t in trades:
            entry = t.get("entry_date")
            exit_ = t.get("exit_date")
            if entry is not None and exit_ is not None:
                holding_days.append((exit_ - entry).days)
        avg_holding_days = sum(holding_days) / len(holding_days) if holding_days else 0.0
    else:
        win_rate = 0.0
        profit_loss_ratio = 0.0
        avg_holding_days = 0.0

    return {
        "total_return_pct": total_return_pct,
        "cagr": cagr_val,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": max_drawdown_pct,
        "win_rate": win_rate,
        "profit_loss_ratio": profit_loss_ratio,
        "n_trades": n_trades,
        "avg_holding_days": avg_holding_days,
    }


def trade_pnl_statistics(
    trades: list[dict],
    pnl_field: str = "realized_pnl_pct",
    group_fields: list[str] | None = None,
) -> dict:
    """Compute PnL aggregation statistics, optionally grouped.

    Parameters
    ----------
    trades : list of trade dicts
    pnl_field : which field to aggregate (e.g. "realized_pnl_pct" or "pnl_yuan")
    group_fields : optional list of fields to group by (e.g. ["symbol", "entry_reason"])

    Returns
    -------
    If group_fields is None:
        {"win_rate": float, "profit_loss_ratio": float, "avg_pnl": float,
         "median_pnl": float, "std_pnl": float, "n_trades": int}
    Else:
        {group_key_tuple: same dict, ...}

    Reference
    ---------
    Standard trade journal analytics.
    """
    import statistics as _stats

    def _compute_group(group: list[dict]) -> dict:
        pnls = [float(t.get(pnl_field, 0)) for t in group]
        n = len(pnls)
        if n == 0:
            return {
                "win_rate": 0.0,
                "profit_loss_ratio": 0.0,
                "avg_pnl": 0.0,
                "median_pnl": 0.0,
                "std_pnl": 0.0,
                "n_trades": 0,
            }
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        win_rate = len(wins) / n
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
        plr = avg_win / avg_loss if avg_loss > 0 else float("inf")

        avg_pnl = sum(pnls) / n
        median_pnl = _stats.median(pnls)
        std_pnl = _stats.stdev(pnls) if n > 1 else 0.0

        return {
            "win_rate": win_rate,
            "profit_loss_ratio": plr,
            "avg_pnl": avg_pnl,
            "median_pnl": median_pnl,
            "std_pnl": std_pnl,
            "n_trades": n,
        }

    if group_fields is None:
        return _compute_group(trades)

    # Group by
    groups: dict[tuple, list[dict]] = {}
    for t in trades:
        key = tuple(t.get(f) for f in group_fields)
        if key not in groups:
            groups[key] = []
        groups[key].append(t)

    return {k: _compute_group(v) for k, v in groups.items()}


def rule_compliance_winrate_diff(
    *,
    trades: list[dict[str, object]],
    rule_check_fn: object,
    return_field: str = "pnl_pct",
) -> dict[str, object]:
    """Compare winrate between rule-compliant and rule-violating trades.

    Parameters
    ----------
    trades : list of dict
        Each dict must have at least the `return_field` key.
    rule_check_fn : callable
        Function(trade) -> bool. True = compliant. Exceptions → skip + log.
    return_field : str
        Key in trade dict for the return value (default "pnl_pct").

    Returns
    -------
    dict with keys: compliant, violation, diff, n_total, errors.
    """
    compliant_trades: list[dict[str, object]] = []
    violation_trades: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []

    for trade in trades:
        try:
            is_compliant = rule_check_fn(trade)  # type: ignore[operator]
        except Exception as e:
            errors.append({"trade": trade, "error": str(e)})
            continue
        if is_compliant:
            compliant_trades.append(trade)
        else:
            violation_trades.append(trade)

    def _group_stats(group: list[dict[str, object]]) -> dict[str, object]:
        if not group:
            return {
                "n_trades": 0,
                "winrate": None,
                "avg_return_pct": None,
                "median_return_pct": None,
            }
        returns = [t[return_field] for t in group if t.get(return_field) is not None]
        if not returns:
            return {
                "n_trades": len(group),
                "winrate": None,
                "avg_return_pct": None,
                "median_return_pct": None,
            }
        arr = np.array(returns, dtype=float)
        valid = arr[~np.isnan(arr)]
        if len(valid) == 0:
            return {
                "n_trades": len(group),
                "winrate": None,
                "avg_return_pct": None,
                "median_return_pct": None,
            }
        n = len(valid)
        wins = int(np.sum(valid > 0))
        return {
            "n_trades": n,
            "winrate": wins / n,
            "avg_return_pct": float(np.mean(valid)),
            "median_return_pct": float(np.median(valid)),
        }

    c_stats = _group_stats(compliant_trades)
    v_stats = _group_stats(violation_trades)

    # Compute diff
    diff: dict[str, object] = {}
    if c_stats["winrate"] is not None and v_stats["winrate"] is not None:
        diff["winrate_pct_points"] = round((c_stats["winrate"] - v_stats["winrate"]) * 100, 2)
        if c_stats["avg_return_pct"] is not None and v_stats["avg_return_pct"] is not None:
            diff["avg_return_pct_points"] = round(
                c_stats["avg_return_pct"] - v_stats["avg_return_pct"], 2
            )
    else:
        diff["winrate_pct_points"] = None
        diff["avg_return_pct_points"] = None

    return {
        "compliant": c_stats,
        "violation": v_stats,
        "diff": diff,
        "n_total": len(trades),
        "errors": errors,
    }


def subject_forward_winrate(
    *,
    events: list[dict],
    prices: dict[str, list[float]],
    forward_window_days: int = 3,
    win_mode: str = "any_positive",
) -> dict:
    """Calculate forward winrate for a subject (seat/trader/theme)."""
    if forward_window_days <= 0:
        raise ValueError("forward_window_days must be > 0")
    if not events:
        return {"winrate": None, "n_events_total": 0, "n_events_valid": 0, "wins": 0, "losses": 0}
    wins = 0
    losses = 0
    skipped = 0
    for event in events:
        symbol = event.get("symbol", "")
        price_series = prices.get(symbol)
        if not price_series or len(price_series) < forward_window_days + 1:
            skipped += 1
            continue
        entry_price = price_series[0]
        forward_prices = price_series[1 : forward_window_days + 1]
        if entry_price <= 0:
            skipped += 1
            continue
        returns = [(p - entry_price) / entry_price for p in forward_prices]
        if win_mode == "any_positive":
            is_win = any(r > 0 for r in returns)
        elif win_mode == "final_positive":
            is_win = returns[-1] > 0 if returns else False
        else:
            raise ValueError(f"Unknown win_mode: {win_mode}")
        if is_win:
            wins += 1
        else:
            losses += 1
    n_valid = wins + losses
    winrate = wins / n_valid if n_valid > 0 else None
    return {
        "winrate": winrate,
        "n_events_total": len(events),
        "n_events_valid": n_valid,
        "wins": wins,
        "losses": losses,
    }
