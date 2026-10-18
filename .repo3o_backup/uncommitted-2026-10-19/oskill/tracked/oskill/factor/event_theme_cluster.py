"""Cluster events into themes using stock-industry-theme mapping."""

from __future__ import annotations

STABILITY = "experimental"


def event_theme_cluster(
    events: list[dict],
    classification: dict[str, list[str]],
    history_window: list[dict] | None = None,
    top_n: int = 3,
) -> list[dict]:
    """Cluster event-bearing stocks into themes, rank by strength.

    Parameters
    ----------
    events : list of event dicts, each like {"symbol": str, "strength": float, ...}
    classification : {symbol: [theme_tag, ...]} mapping (caller provides; for A-share
                     this is e.g. {"600519": ["baijiu", "consumption"], ...})
    history_window : optional list of past N days' events for continuation analysis
    top_n : number of top themes to return

    Returns
    -------
    [{
        "theme_name": str,
        "n_stocks": int,
        "total_strength": float,
        "leader_symbols": list[str],   # top 3-5 stocks by individual strength
        "continuation_prob": float,    # if history_window provided
        "stage": str | None            # "emergent" / "developing" / "mature" / "fading"
    }, ...]

    Methodology
    -----------
    Generic theme clustering. Continuation probability uses simple historical
    base rate from history_window.

    Uses: oprim.statistics.percentile_value

    Reference
    ---------
    Sector rotation literature; momentum-based theme persistence.
    """
    if not events:
        return []

    theme_data: dict[str, dict] = {}

    for ev in events:
        symbol = ev.get("symbol", "")
        strength = float(ev.get("strength", 0.0))
        themes = classification.get(symbol, [])

        for theme in themes:
            if theme not in theme_data:
                theme_data[theme] = {"symbols": {}, "total_strength": 0.0}
            theme_data[theme]["symbols"][symbol] = (
                theme_data[theme]["symbols"].get(symbol, 0.0) + strength
            )
            theme_data[theme]["total_strength"] += strength

    if history_window:
        hist_theme_counts: dict[str, int] = {}
        for ev in history_window:
            sym = ev.get("symbol", "")
            for theme in classification.get(sym, []):
                hist_theme_counts[theme] = hist_theme_counts.get(theme, 0) + 1
        total_hist = len(history_window) if history_window else 1
    else:
        hist_theme_counts = {}
        total_hist = 0

    result = []
    for theme_name, data in theme_data.items():
        syms_by_strength = sorted(data["symbols"].items(), key=lambda x: x[1], reverse=True)
        leader_symbols = [s for s, _ in syms_by_strength[:5]]
        n_stocks = len(data["symbols"])
        total_strength = data["total_strength"]

        if total_hist > 0 and theme_name in hist_theme_counts:
            continuation_prob = min(hist_theme_counts[theme_name] / total_hist, 1.0)
        else:
            continuation_prob = 0.0

        if n_stocks == 1:
            stage = "emergent"
        elif n_stocks <= 3:
            stage = "developing"
        elif continuation_prob > 0.5:
            stage = "mature"
        else:
            stage = "developing"

        result.append(
            {
                "theme_name": theme_name,
                "n_stocks": n_stocks,
                "total_strength": total_strength,
                "leader_symbols": leader_symbols,
                "continuation_prob": continuation_prob,
                "stage": stage,
            }
        )

    result.sort(key=lambda x: x["total_strength"], reverse=True)
    return result[:top_n]
