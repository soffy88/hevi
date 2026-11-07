"""Disclosure event scoring (multi-dimensional weighted scoring of corporate events)."""

from __future__ import annotations

from collections.abc import Callable

STABILITY = "experimental"


def disclosure_event_scoring(
    events: list[dict],
    scoring_dimensions: list[dict],
    weights: dict[str, float],
    history_lookup: Callable | None = None,
) -> list[dict]:
    """Score a list of disclosure events on multiple dimensions.

    Parameters
    ----------
    events : list of event dicts, e.g.
             [{"symbol": "600519", "date": date, "event_type": "lhb_buy", ...}, ...]
    scoring_dimensions : list of dimension definitions, e.g.
                        [{"name": "market_recognition", "max_score": 25,
                          "method": "percentile", "params": {...}}, ...]
    weights : {dimension_name: weight} for final composite (must sum to 1.0)
    history_lookup : optional callback (symbol, date) -> historical context dict

    Returns
    -------
    [{
        "symbol": str,
        "date": date,
        "total_score": float,
        "scores_by_dimension": {dim_name: float, ...},
        "metadata": {...}
    }, ...]

    Methodology
    -----------
    Generic N-dimension event scoring pattern. Each dimension's scoring
    method is caller-provided via params. Weights normalize the composite.

    Uses: oprim.statistics.percentile_value, oprim.numerics.softmax_safe

    Reference
    ---------
    Multi-criteria decision analysis literature (Saaty, T. L. AHP).
    """
    if not events:
        return []

    weight_sum = sum(weights.values())
    if abs(weight_sum - 1.0) > 1e-6 and weights:
        normalized_weights = {k: v / weight_sum for k, v in weights.items()}
    else:
        normalized_weights = weights

    results = []

    for event in events:
        symbol = event.get("symbol", "")
        event_date = event.get("date")
        scores_by_dim: dict[str, float] = {}

        historical_context = {}
        if history_lookup is not None and symbol and event_date is not None:
            try:
                historical_context = history_lookup(symbol, event_date) or {}
            except Exception:
                pass

        for dim in scoring_dimensions:
            dim_name = dim.get("name", "")
            max_score = float(dim.get("max_score", 100))
            method = dim.get("method", "direct")
            params = dim.get("params", {})

            if method == "direct":
                field = params.get("field", dim_name)
                raw_val = float(event.get(field, 0))
                dim_max = float(params.get("max", max_score))
                score = min(raw_val / dim_max * max_score, max_score) if dim_max > 0 else 0.0
            elif method == "percentile":
                field = params.get("field", dim_name)
                raw_val = float(event.get(field, 0))
                reference = params.get("reference", [])
                if reference:
                    sorted_ref = sorted(reference)
                    pct_rank = sum(1 for v in sorted_ref if v <= raw_val) / len(sorted_ref)
                    score = pct_rank * max_score
                else:
                    score = 0.0
            elif method == "context":
                ctx_field = params.get("field", dim_name)
                score = float(historical_context.get(ctx_field, 0))
            else:
                score = 0.0

            scores_by_dim[dim_name] = max(0.0, score)

        total_score = sum(
            scores_by_dim.get(dim_name, 0.0) * normalized_weights.get(dim_name, 0.0)
            for dim_name in scores_by_dim
        )

        results.append(
            {
                "symbol": symbol,
                "date": event_date,
                "total_score": total_score,
                "scores_by_dimension": scores_by_dim,
                "metadata": {k: v for k, v in event.items() if k not in ("symbol", "date")},
            }
        )

    return results
