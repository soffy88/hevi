"""Group 4: Similarity Retrieval skills."""

from __future__ import annotations

import warnings
from datetime import date
from typing import Literal

import numpy as np
import oprim
import pandas as pd

STABILITY_NEW = "experimental"  # for Sprint 0 additions only


def historical_analogy_search(
    query: np.ndarray,
    historical_db: list[np.ndarray] | np.ndarray,
    *,
    methods: list[Literal["dtw", "wasserstein", "cosine", "euclidean"]] | None = None,
    ensemble: Literal["mean_rank", "borda", "weighted"] = "mean_rank",
    weights: dict[str, float] | None = None,
    top_k: int = 10,
    sakoe_chiba_band: int | None = None,
) -> list[dict]:
    """Historical analogy ensemble search using multiple distance metrics.

    Calls:
        oprim.dtw_distance, oprim.wasserstein_distance,
        oprim.cosine_similarity_batch, oprim.euclidean_distance_matrix

    Args:
        query: Query time series (1D).
        historical_db: List of historical series or 2D array.
        methods: Distance methods to use. Default: ["dtw", "wasserstein"].
        ensemble: Ensemble strategy.
        weights: Method weights (required for 'weighted' ensemble).
        top_k: Number of top results to return.
        sakoe_chiba_band: Sakoe-Chiba band for DTW.

    Returns:
        List of dicts with rank, historical_idx, ensemble_score, distances, ranks.

    Raises:
        ValueError: If inputs are invalid.
    """
    if methods is None:
        methods = ["dtw", "wasserstein"]

    if ensemble == "weighted" and weights is None:
        raise ValueError("weights must be provided for 'weighted' ensemble")

    query = np.asarray(query, dtype=np.float64)

    # Normalize historical_db to list
    if isinstance(historical_db, np.ndarray) and historical_db.ndim == 2:
        db_list = [historical_db[i] for i in range(historical_db.shape[0])]
    else:
        db_list = [np.asarray(h, dtype=np.float64) for h in historical_db]

    n_db = len(db_list)
    if n_db == 0:
        raise ValueError("historical_db must not be empty")

    top_k = min(top_k, n_db)

    # Compute distances per method
    distances: dict[str, np.ndarray] = {}

    for method in methods:
        dists = np.full(n_db, np.inf)

        if method == "dtw":
            for i, h in enumerate(db_list):
                result = oprim.dtw_distance(query, y=h, window=sakoe_chiba_band)
                dists[i] = result["distance"]

        elif method == "wasserstein":
            for i, h in enumerate(db_list):
                dists[i] = oprim.wasserstein_distance(query, v=h)

        elif method == "cosine":
            # Cosine requires same length
            query_len = len(query)
            same_len = [i for i, h in enumerate(db_list) if len(h) == query_len]
            excluded = [i for i in range(n_db) if i not in same_len]
            if excluded:
                warnings.warn(
                    f"cosine: indices {excluded} have different length than query "
                    f"({query_len}), excluded from ranking",
                    stacklevel=2,
                )
            if not same_len:
                raise ValueError(
                    f"cosine: all series have different length than query ({query_len})"
                )
            if same_len:
                db_matrix = np.array([db_list[i] for i in same_len])
                sims = oprim.cosine_similarity_batch(query, database=db_matrix)
                for j, idx in enumerate(same_len):
                    dists[idx] = 1.0 - sims[j]  # Convert similarity to distance

        elif method == "euclidean":
            query_len = len(query)
            same_len = [i for i, h in enumerate(db_list) if len(h) == query_len]
            excluded = [i for i in range(n_db) if i not in same_len]
            if excluded:
                warnings.warn(
                    f"euclidean: indices {excluded} have different length than query "
                    f"({query_len}), excluded from ranking",
                    stacklevel=2,
                )
            if same_len:
                db_matrix = np.array([db_list[i] for i in same_len])
                dist_matrix = oprim.euclidean_distance_matrix(query.reshape(1, -1), y=db_matrix)
                for j, idx in enumerate(same_len):
                    dists[idx] = dist_matrix[0, j]

        distances[method] = dists

    # Compute ranks per method with tie handling (average rank for ties)
    ranks: dict[str, np.ndarray] = {}
    for method, dists in distances.items():
        from scipy.stats import rankdata

        # rankdata handles ties with 'average' method; inf gets highest rank
        r = rankdata(dists, method="average")
        ranks[method] = r

    # Ensemble scoring
    if ensemble == "mean_rank":
        scores = np.mean([ranks[m] for m in methods], axis=0)
    elif ensemble == "borda":
        # Proper Borda count: each method awards (n_db - rank) points
        # With tie handling via average ranks, fractional points are possible
        borda_points = np.zeros(n_db, dtype=float)
        for m in methods:
            borda_points += (n_db + 1) - ranks[m]  # higher = better
        scores = -borda_points  # Negate so lower = better for sorting
    elif ensemble == "weighted":
        w = weights or {}
        scores = np.zeros(n_db)
        for m in methods:
            w_m = w.get(m, 1.0)
            scores += w_m * ranks[m]
    else:
        scores = np.mean([ranks[m] for m in methods], axis=0)

    # Sort by score (lower = better)
    top_indices = np.argsort(scores)[:top_k]

    results = []
    for rank_pos, idx in enumerate(top_indices):
        results.append(
            {
                "rank": rank_pos + 1,
                "historical_idx": int(idx),
                "ensemble_score": float(scores[idx]),
                "distances_per_method": {m: float(distances[m][idx]) for m in methods},
                "ranks_per_method": {m: int(ranks[m][idx]) for m in methods},
            }
        )

    return results


def regime_transition_analysis(
    regime_labels: pd.Series,
    *,
    data_per_regime: pd.Series | None = None,
    include_duration_stats: bool = True,
    min_duration: int = 1,
) -> dict:
    """Regime transition analysis with holding period and half-life.

    Calls:
        oprim.regime_transition_matrix, oprim.regime_filter_data, oprim.distribution_summary

    Args:
        regime_labels: Series of regime labels.
        data_per_regime: Optional data series for per-regime statistics.
        include_duration_stats: Whether to include duration distribution.
        min_duration: Minimum duration to count as a regime stay.

    Returns:
        Dict with transition_matrix, stationary_distribution, holding periods, half-lives.

    Raises:
        ValueError: If regime_labels has fewer than 2 unique regimes.
    """
    if not isinstance(regime_labels, pd.Series):
        regime_labels = pd.Series(regime_labels)

    # Remove NaN
    valid_labels = regime_labels.dropna()
    if len(valid_labels) < 2:
        raise ValueError("regime_labels must have at least 2 observations")

    unique_regimes = valid_labels.unique()
    if len(unique_regimes) < 2:
        raise ValueError("regime_labels must have at least 2 unique regimes")

    # Use oprim.regime_transition_matrix
    tm_result = oprim.regime_transition_matrix(
        valid_labels, include_duration=include_duration_stats
    )

    transition_matrix = tm_result["transition_matrix"]
    stationary_dist = tm_result["stationary_distribution"]
    n_transitions = tm_result["n_transitions"]
    duration_dist = tm_result.get("duration_distribution") if include_duration_stats else None

    # Compute expected holding period and half-life
    expected_holding_period = {}
    half_life = {}

    for regime in unique_regimes:
        if regime in transition_matrix.index:
            p_stay = transition_matrix.loc[regime, regime]
            if p_stay >= 1.0:
                expected_holding_period[regime] = np.inf
                half_life[regime] = np.inf
            elif p_stay <= 0.0:
                expected_holding_period[regime] = 1.0
                half_life[regime] = 0.0
            else:
                expected_holding_period[regime] = 1.0 / (1.0 - p_stay)
                half_life[regime] = np.log(0.5) / np.log(p_stay)

    # Per-regime data summary
    data_summary = None
    if data_per_regime is not None:
        if not isinstance(data_per_regime, pd.Series):
            data_per_regime = pd.Series(data_per_regime)
        data_df = pd.DataFrame({"value": data_per_regime})
        data_summary = {}
        for regime in unique_regimes:
            filtered = oprim.regime_filter_data(data_df, regime_labels=regime_labels, target_regime=regime)
            if len(filtered) > 0:
                data_summary[regime] = oprim.distribution_summary(filtered["value"].values)

    return {
        "transition_matrix": transition_matrix,
        "stationary_distribution": stationary_dist,
        "n_transitions": n_transitions,
        "duration_distribution": duration_dist,
        "expected_holding_period": expected_holding_period,
        "half_life": half_life,
        "data_summary_per_regime": data_summary,
    }


def commodity_ratio_analytics(
    numerator: pd.Series,
    denominator: pd.Series,
    *,
    benchmark_window: int = 252,
) -> dict:
    """Analyze commodity price ratio with regime classification.

    Calls:
        oprim.percentile_rank, oprim.zscore_normalize

    Args:
        numerator: Price series of numerator asset.
        denominator: Price series of denominator asset.
        benchmark_window: Rolling window for percentile/zscore.

    Returns:
        Dict with ratio_series, current_ratio, percentile_rank, zscore, regime.
    """
    if not isinstance(numerator, pd.Series):
        numerator = pd.Series(numerator)
    if not isinstance(denominator, pd.Series):
        denominator = pd.Series(denominator)
    if len(numerator) != len(denominator):
        raise ValueError("numerator and denominator must have same length")
    if (denominator == 0).any():
        raise ValueError("denominator must not contain zeros")

    ratio = numerator / denominator
    ratio_series = ratio.dropna()

    if len(ratio_series) < 20:
        raise ValueError("Need at least 20 data points")

    current = float(ratio_series.iloc[-1])

    # Use oprim for percentile and zscore
    prank = oprim.percentile_rank(ratio_series, method="expanding")
    current_pct = float(prank.iloc[-1]) if not np.isnan(prank.iloc[-1]) else 0.5

    zscores = oprim.zscore_normalize(ratio_series, window=benchmark_window, min_periods=20)
    current_z = float(zscores.iloc[-1]) if not np.isnan(zscores.iloc[-1]) else 0.0

    # Regime classification
    if current_pct > 0.95 or current_z > 2:
        regime = "extreme_high"
    elif current_pct > 0.75 or current_z > 1:
        regime = "high"
    elif current_pct < 0.05 or current_z < -2:
        regime = "extreme_low"
    elif current_pct < 0.25 or current_z < -1:
        regime = "low"
    else:
        regime = "normal"

    return {
        "ratio_series": ratio_series,
        "current_ratio": current,
        "percentile_rank": current_pct,
        "zscore": current_z,
        "regime": regime,
    }


def geopolitical_risk_index(
    events: pd.DataFrame,
    *,
    decay_half_life: int = 30,
) -> dict:
    """Compute geopolitical risk index from event data.

    Calls:
        oprim.ewma_smooth, oprim.percentile_rank, oprim.zscore_normalize

    Args:
        events: DataFrame with columns: timestamp, intensity, region, weight.
        decay_half_life: Half-life in days for exponential decay.

    Returns:
        Dict with index_series, current_value, percentile_rank, regime, top_contributors.
    """
    required = {"timestamp", "intensity"}
    if not required.issubset(events.columns):
        raise ValueError(f"events must have columns: {required}")
    if len(events) == 0:
        raise ValueError("events must not be empty")

    df = events.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")

    # Compute weighted intensity
    weight_col = df["weight"].values if "weight" in df.columns else np.ones(len(df))
    weighted_intensity = df["intensity"].values * weight_col

    # Create daily time series
    daily_idx = pd.date_range(df["timestamp"].min(), df["timestamp"].max(), freq="D")
    daily_series = pd.Series(0.0, index=daily_idx)
    for i, row in df.iterrows():
        date = row["timestamp"].normalize()
        if date in daily_series.index:
            daily_series.loc[date] += weighted_intensity[df.index.get_loc(i)]

    # Apply EWMA decay using oprim
    index_series = oprim.ewma_smooth(daily_series, half_life=decay_half_life)

    current_value = float(index_series.iloc[-1])

    # Percentile and regime
    prank = oprim.percentile_rank(index_series, method="expanding")
    current_pct = float(prank.iloc[-1]) if len(prank) > 0 and not np.isnan(prank.iloc[-1]) else 0.5

    if current_pct > 0.9:
        regime = "extreme"
    elif current_pct > 0.7:
        regime = "elevated"
    elif current_pct > 0.3:
        regime = "normal"
    else:
        regime = "low"

    # Top contributors (most recent events by intensity)
    recent = df.tail(10).sort_values("intensity", ascending=False)
    top_contributors = recent[["timestamp", "intensity"]].head(5).to_dict("records")
    if "region" in df.columns:
        top_contributors = recent[["timestamp", "intensity", "region"]].head(5).to_dict("records")

    return {
        "index_series": index_series,
        "current_value": current_value,
        "percentile_rank": current_pct,
        "regime": regime,
        "top_contributors": top_contributors,
    }


# ── Sprint 0 additions (v2.5.0) ──────────────────────────────────────────────


def multi_dim_nearest_search(
    anchor_vec: list[float],
    history_vecs: list[tuple],
    k: int = 20,
    weights: list[float] | None = None,
    distance_metric: Literal["euclidean", "cosine", "weighted_euclidean"] = "weighted_euclidean",
) -> list[dict]:
    """Find k nearest historical neighbors for a multi-dimensional anchor vector.

    Parameters
    ----------
    anchor_vec : current state vector (e.g. 5 dims)
    history_vecs : [(date, vec), ...] historical states
    k : number of neighbors to return
    weights : optional dimension weights (must match len(anchor_vec))
    distance_metric : distance function

    Returns
    -------
    [{"date": date, "distance": float, "vec": list[float]}, ...] sorted ascending by distance

    Methodology
    -----------
    Uses oprim.distance.euclidean_distance_matrix or oprim.distance.cosine_similarity_batch
    depending on metric. Weighted euclidean composes element-wise weights with euclidean.

    Uses: oprim.distance

    Reference
    ---------
    Cover, T. M., & Hart, P. E. (1967). Nearest neighbor pattern classification.
    IEEE Transactions on Information Theory, 13(1), 21-27.
    """
    if not history_vecs:
        return []

    anchor = np.array(anchor_vec, dtype=np.float64)
    n_dims = len(anchor_vec)

    if weights is not None and len(weights) != n_dims:
        raise ValueError("weights must match len(anchor_vec)")

    w = np.array(weights, dtype=np.float64) if weights is not None else np.ones(n_dims)

    results = []
    for hist_date, hist_vec in history_vecs:
        hv = np.array(hist_vec, dtype=np.float64)
        if len(hv) != n_dims:
            continue

        if distance_metric in ("euclidean", "weighted_euclidean"):
            diff = (anchor - hv) * w
            dist = float(np.sqrt(np.sum(diff**2)))
        elif distance_metric == "cosine":
            anchor_norm = np.linalg.norm(anchor)
            hv_norm = np.linalg.norm(hv)
            if anchor_norm > 0 and hv_norm > 0:
                sim = float(np.dot(anchor, hv) / (anchor_norm * hv_norm))
                dist = 1.0 - sim
            else:
                dist = 1.0
        else:
            raise ValueError(f"Unknown distance_metric: {distance_metric!r}")

        results.append({"date": hist_date, "distance": dist, "vec": list(hv)})

    results.sort(key=lambda x: x["distance"])
    return results[:k]


def forward_outcome_distribution(
    anchor_date: date,
    similar_dates: list[date],
    ohlcv_lookup: dict,
    periods: list[int],
) -> dict:
    """Compute the distribution of forward returns starting from similar historical dates.

    Parameters
    ----------
    anchor_date : reference date (not used in computation, only for output)
    similar_dates : list of historical analogue dates
    ohlcv_lookup : {date: [open, high, low, close, volume]} for all needed dates
    periods : forward periods to compute (e.g. [5, 10, 20])

    Returns
    -------
    {
        "anchor_date": date,
        "n_analogues": int,
        "by_period": {
            period: {"mean_return": float, "median_return": float, "win_rate": float,
                     "p25": float, "p75": float, "p10": float, "p90": float}
        }
    }

    Methodology
    -----------
    For each similar_date, compute forward N-period return using ohlcv_lookup.

    Uses: oprim.statistics.distribution_summary, oprim.statistics.percentile_value

    Reference
    ---------
    Lo, A. W., Mamaysky, H., & Wang, J. (2000). Foundations of Technical Analysis.
    Journal of Finance, 55(4), 1705-1770.
    """
    sorted_dates = sorted(ohlcv_lookup.keys())

    def _fwd_return(start_date: date, n: int) -> float | None:
        try:
            idx = sorted_dates.index(start_date)
        except ValueError:
            return None
        end_idx = idx + n
        if end_idx >= len(sorted_dates):
            return None
        start_ohlcv = ohlcv_lookup[sorted_dates[idx]]
        end_ohlcv = ohlcv_lookup[sorted_dates[end_idx]]
        start_price = (
            start_ohlcv[3]
            if isinstance(start_ohlcv, (list, tuple))
            else start_ohlcv.get("close", 0)
        )
        end_price = (
            end_ohlcv[3] if isinstance(end_ohlcv, (list, tuple)) else end_ohlcv.get("close", 0)
        )
        if start_price <= 0:
            return None
        return (end_price - start_price) / start_price

    by_period = {}
    for period in periods:
        rets = []
        for sim_date in similar_dates:
            r = _fwd_return(sim_date, period)
            if r is not None:
                rets.append(r)

        if not rets:
            by_period[period] = {
                "mean_return": 0.0,
                "median_return": 0.0,
                "win_rate": 0.0,
                "p25": 0.0,
                "p75": 0.0,
                "p10": 0.0,
                "p90": 0.0,
            }
            continue

        rets_sorted = sorted(rets)
        n = len(rets)
        by_period[period] = {
            "mean_return": sum(rets) / n,
            "median_return": oprim.percentile_value(rets_sorted, q=0.5),
            "win_rate": sum(1 for r in rets if r > 0) / n,
            "p25": oprim.percentile_value(rets_sorted, q=0.25),
            "p75": oprim.percentile_value(rets_sorted, q=0.75),
            "p10": oprim.percentile_value(rets_sorted, q=0.10),
            "p90": oprim.percentile_value(rets_sorted, q=0.90),
        }

    return {
        "anchor_date": anchor_date,
        "n_analogues": len(similar_dates),
        "by_period": by_period,
    }
