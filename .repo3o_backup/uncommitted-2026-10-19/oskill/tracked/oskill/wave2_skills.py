"""Wave 2 oskills — IC diagnosis, directionality, normalization, regime weights."""

from __future__ import annotations

from typing import Literal

import numpy as np


class Wave2SkillError(Exception):
    """Raised when a Wave 2 oskill fails."""


def ic_root_cause_decompose(
    *,
    signal_matrix: list[list[float]],
    returns: list[float],
    regime_labels: list[str],
    dimension_names: list[str],
) -> dict:
    """Decompose IC by Regime × Dimension to identify negative contributors.

    Internal oprim composition:
    - oprim.compute_regime_conditional_ic
    - oprim.compute_factor_contribution
    - oprim.classify_market_regime

    Example:
        >>> ic_root_cause_decompose(signal_matrix=[[0.1]*3]*100, returns=[0.01]*100, regime_labels=["bull"]*100, dimension_names=["trend","flow","sentiment"])
    """
    T = len(returns)
    len(dimension_names)
    regimes = sorted(set(regime_labels))
    matrix = []
    top_neg = []

    for regime in regimes:
        row = []
        for d_idx, dim in enumerate(dimension_names):
            indices = [i for i in range(T) if regime_labels[i] == regime]
            if len(indices) < 10:
                row.append(
                    {
                        "dimension": dim,
                        "regime": regime,
                        "ic_value": 0,
                        "sample_count": len(indices),
                        "is_significant": False,
                    }
                )
                continue
            sig = [signal_matrix[i][d_idx] if d_idx < len(signal_matrix[i]) else 0 for i in indices]
            ret = [returns[i] for i in indices]
            # Spearman IC approximation
            sig_rank = np.argsort(np.argsort(sig)).astype(float)
            ret_rank = np.argsort(np.argsort(ret)).astype(float)
            n = len(sig_rank)
            ic = float(np.corrcoef(sig_rank, ret_rank)[0, 1]) if n > 2 else 0
            entry = {
                "dimension": dim,
                "regime": regime,
                "ic_value": round(ic, 4),
                "sample_count": n,
                "is_significant": abs(ic) > 0.05,
            }
            row.append(entry)
            if ic < -0.05:
                top_neg.append(entry)
        matrix.append(row)

    top_neg.sort(key=lambda x: x["ic_value"])
    regime_agg = []
    for regime in regimes:
        entries = [
            e for row in matrix for e in row if e["regime"] == regime and e["is_significant"]
        ]
        avg_ic = sum(e["ic_value"] for e in entries) / max(len(entries), 1)
        regime_agg.append(
            {"regime": regime, "weighted_ic": round(avg_ic, 4), "significant_dims": len(entries)}
        )

    if not top_neg:
        summary = "No significant negative IC contributors found."
        recommendation = "Signal appears healthy across all regime-dimension combinations."
    elif len(set(e["regime"] for e in top_neg[:3])) == 1:
        bad_regime = top_neg[0]["regime"]
        summary = f"{bad_regime} regime dominates negative IC contributions."
        recommendation = f"Consider reducing signal weight during {bad_regime} regime."
    else:
        bad_dim = top_neg[0]["dimension"]
        summary = f"{bad_dim} dimension is the largest negative IC contributor across regimes."
        recommendation = f"Review {bad_dim} dimension signal design or flip its sign."

    return {
        "matrix": matrix,
        "top_negative_contributors": top_neg[:5],
        "regime_aggregated": regime_agg,
        "diagnosis_summary": summary,
        "recommendation": recommendation,
    }


def signal_directionality_profile(
    *,
    signal_matrix: list[list[float]],
    returns_by_horizon: dict[int, list[float]],
    dimension_names: list[str],
) -> dict:
    """Analyze signal directionality — trending vs mean-reverting vs noisy.

    Internal oprim composition:
    - oprim.compute_information_coefficient
    - oprim.classify_market_regime

    Example:
        >>> signal_directionality_profile(signal_matrix=[[0.1]*2]*50, returns_by_horizon={1: [0.01]*50, 7: [-0.01]*50}, dimension_names=["trend","flow"])
    """
    dimensions = []
    to_flip = []

    for d_idx, dim in enumerate(dimension_names):
        ic_by_horizon = {}
        for horizon, rets in returns_by_horizon.items():
            n = min(len(rets), len(signal_matrix))
            if n < 20:
                continue
            sig = [
                signal_matrix[i][d_idx] if d_idx < len(signal_matrix[i]) else 0 for i in range(n)
            ]
            sig_rank = np.argsort(np.argsort(sig)).astype(float)
            ret_rank = np.argsort(np.argsort(rets[:n])).astype(float)
            ic = float(np.corrcoef(sig_rank, ret_rank)[0, 1]) if n > 2 else 0
            ic_by_horizon[horizon] = round(ic, 4)

        if not ic_by_horizon:
            dimensions.append(
                {
                    "dimension": dim,
                    "direction_type": "insufficient_data",
                    "best_horizon_days": 0,
                    "best_horizon_ic": 0,
                    "ic_across_horizons": {},
                    "recommendation": "Need more data",
                }
            )
            continue

        best_h = max(ic_by_horizon, key=lambda h: abs(ic_by_horizon[h]))
        best_ic = ic_by_horizon[best_h]

        if best_ic > 0.05:
            dtype = "trending"
            rec = "Use as trend-following factor."
        elif best_ic < -0.05:
            dtype = "mean_reverting"
            rec = "Signal direction may be inverted — consider flipping sign."
            to_flip.append(dim)
        else:
            dtype = "noisy"
            rec = "Low predictive power — consider removing or redesigning."

        dimensions.append(
            {
                "dimension": dim,
                "direction_type": dtype,
                "best_horizon_days": best_h,
                "best_horizon_ic": best_ic,
                "ic_across_horizons": ic_by_horizon,
                "recommendation": rec,
            }
        )

    trending = sum(1 for d in dimensions if d["direction_type"] == "trending")
    reverting = sum(1 for d in dimensions if d["direction_type"] == "mean_reverting")
    noisy = sum(1 for d in dimensions if d["direction_type"] == "noisy")
    summary = (
        f"{len(dimensions)} dims: {trending} trending, {reverting} mean-reverting, {noisy} noisy."
    )

    return {"dimensions": dimensions, "summary": summary, "dimensions_to_flip": to_flip}


def cross_asset_score_normalization(
    *,
    asset_scores: dict[str, float],
    asset_histories: dict[str, list[float]],
    method: Literal["percentile", "zscore", "both"] = "both",
) -> dict:
    """Normalize fusion scores across different asset classes to comparable scale.

    Internal oprim composition:
    - oprim.compute_percentile_rank
    - oprim.compute_score_z_score

    Example:
        >>> cross_asset_score_normalization(asset_scores={"BTC": 65, "Gold": 42}, asset_histories={"BTC": [50,55,60,65,70], "Gold": [30,35,40,42,45]})
    """
    assets = []
    for name, score in asset_scores.items():
        history = asset_histories.get(name, [])
        if len(history) < 20:
            assets.append(
                {
                    "asset": name,
                    "raw_score": score,
                    "percentile_rank": None,
                    "z_score": None,
                    "normalized_score": score,
                }
            )
            continue
        pct = sum(1 for h in history if h <= score) / len(history) * 100
        mean = sum(history) / len(history)
        std = (sum((h - mean) ** 2 for h in history) / (len(history) - 1)) ** 0.5
        z = (score - mean) / std if std > 0 else 0
        norm = (
            pct
            if method == "percentile"
            else (z * 15 + 50)
            if method == "zscore"
            else (pct + (z * 15 + 50)) / 2
        )
        assets.append(
            {
                "asset": name,
                "raw_score": score,
                "percentile_rank": round(pct, 2),
                "z_score": round(z, 4),
                "normalized_score": round(norm, 2),
            }
        )

    assets.sort(key=lambda a: a["normalized_score"] or 0, reverse=True)
    ranking = [a["asset"] for a in assets]
    top = ranking[0] if ranking else ""
    summary = f"Top: {top} (norm={assets[0]['normalized_score']})" if assets else "No assets"

    return {"assets": assets, "ranking": ranking, "top_opportunity": top, "summary": summary}


def regime_dynamic_weight_adjustment(
    *,
    base_weights: dict[str, float],
    current_regime: str,
    regime_weight_matrix: dict[str, dict[str, float]],
    adjustment_strength: float = 1.0,
    clamp_range: tuple[float, float] = (0.0, 1.0),
) -> dict:
    """Dynamically adjust dimension weights based on current market regime.

    Internal oprim composition:
    - oprim.classify_market_regime (regime input from caller)

    Internal obase dependency:
    - obase.template (loads regime_weight_matrix YAML)

    Example:
        >>> regime_dynamic_weight_adjustment(base_weights={"trend": 0.15, "flow": 0.12}, current_regime="bull", regime_weight_matrix={"bull": {"trend": 0.10}})
    """
    offsets = regime_weight_matrix.get(current_regime, {})
    if not offsets:
        return {
            "original_weights": base_weights,
            "regime": current_regime,
            "offsets_applied": {},
            "adjusted_weights": base_weights,
            "normalization_factor": 1.0,
            "note": f"No offsets for regime '{current_regime}'",
        }

    adjusted = {}
    applied = {}
    lo, hi = clamp_range
    notes = []

    for dim, w in base_weights.items():
        offset = offsets.get(dim, 0) * adjustment_strength
        new_w = w + offset
        if new_w < lo:
            notes.append(f"{dim} clamped to {lo}")
            new_w = lo
        elif new_w > hi:
            notes.append(f"{dim} clamped to {hi}")
            new_w = hi
        adjusted[dim] = new_w
        applied[dim] = round(offset, 6)

    total = sum(adjusted.values())
    if total <= 0:
        return {
            "original_weights": base_weights,
            "regime": current_regime,
            "offsets_applied": applied,
            "adjusted_weights": base_weights,
            "normalization_factor": 1.0,
            "note": "All weights zero after adjustment — reverted",
        }

    norm_factor = 1.0 / total
    adjusted = {k: round(v * norm_factor, 6) for k, v in adjusted.items()}

    return {
        "original_weights": base_weights,
        "regime": current_regime,
        "offsets_applied": applied,
        "adjusted_weights": adjusted,
        "normalization_factor": round(norm_factor, 6),
        "note": "; ".join(notes) if notes else None,
    }
