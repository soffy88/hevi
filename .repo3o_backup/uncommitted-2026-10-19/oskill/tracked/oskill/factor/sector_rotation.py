"""Detect sector-level capital rotation."""

from __future__ import annotations

STABILITY = "experimental"


def sector_capital_rotation_detect(
    industry_capital_flow: list[dict],
    classification: dict[str, str],
    prev_window_days: int = 5,
    top_n: int = 5,
) -> dict:
    """Detect capital rotation between sectors over a lookback window.

    Parameters
    ----------
    industry_capital_flow : list of {"symbol": str, "date": date, "net_inflow": float}
    classification : {symbol: industry_code} mapping
    prev_window_days : lookback window for "previous" period comparison
    top_n : top N sectors to return

    Returns
    -------
    {
        "rotation_detected": bool,
        "top_inflow_sectors": [{"sector": str, "net_inflow": float, "rank_change": int}, ...],
        "top_outflow_sectors": [...],
        "rotation_intensity": float
    }

    Methodology
    -----------
    Aggregate individual stock net inflows to sector level. Compare current
    window sector rank vs previous window. Detect rotation when top inflow
    sectors differ significantly between windows.

    Uses: oprim.statistics.percentile_value, oprim.statistics.correlation_batch

    Reference
    ---------
    Stovall, S. (2006). Sector Rotation: A Quantitative Analysis.
    """
    if not industry_capital_flow:
        return {
            "rotation_detected": False,
            "top_inflow_sectors": [],
            "top_outflow_sectors": [],
            "rotation_intensity": 0.0,
        }

    sorted_data = sorted(industry_capital_flow, key=lambda x: x.get("date", ""), reverse=True)

    if not sorted_data:
        return {
            "rotation_detected": False,
            "top_inflow_sectors": [],
            "top_outflow_sectors": [],
            "rotation_intensity": 0.0,
        }

    most_recent_date = sorted_data[0].get("date")
    current_window = [d for d in sorted_data if d.get("date") == most_recent_date]

    all_dates = sorted({d.get("date") for d in sorted_data}, reverse=True)
    prev_dates = set(list(all_dates)[1 : prev_window_days + 1]) if len(all_dates) > 1 else set()
    prev_window = [d for d in sorted_data if d.get("date") in prev_dates]

    def _aggregate_sectors(data: list[dict]) -> dict[str, float]:
        sector_inflow: dict[str, float] = {}
        for item in data:
            sym = item.get("symbol", "")
            sector = classification.get(sym, "unknown")
            sector_inflow[sector] = sector_inflow.get(sector, 0.0) + float(
                item.get("net_inflow", 0)
            )
        return sector_inflow

    current_sectors = _aggregate_sectors(current_window)
    prev_sectors = _aggregate_sectors(prev_window)

    cur_ranked = sorted(current_sectors.items(), key=lambda x: x[1], reverse=True)
    prev_ranked = sorted(prev_sectors.items(), key=lambda x: x[1], reverse=True)
    prev_rank = {sector: i for i, (sector, _) in enumerate(prev_ranked)}

    top_inflow = []
    for i, (sector, inflow) in enumerate(cur_ranked[:top_n]):
        if inflow > 0:
            rank_change = prev_rank.get(sector, len(cur_ranked)) - i
            top_inflow.append({"sector": sector, "net_inflow": inflow, "rank_change": rank_change})

    top_outflow = []
    for sector, inflow in sorted(current_sectors.items(), key=lambda x: x[1])[:top_n]:
        if inflow < 0:
            i = list(current_sectors.keys()).index(sector)
            rank_change = prev_rank.get(sector, 0) - i
            top_outflow.append({"sector": sector, "net_inflow": inflow, "rank_change": rank_change})

    cur_top_set = {s for s, _ in cur_ranked[:top_n]}
    prev_top_set = {s for s, _ in prev_ranked[:top_n]}
    overlap = len(cur_top_set & prev_top_set)
    rotation_intensity = 1.0 - (overlap / top_n) if top_n > 0 else 0.0
    rotation_detected = rotation_intensity > 0.4

    return {
        "rotation_detected": rotation_detected,
        "top_inflow_sectors": top_inflow,
        "top_outflow_sectors": top_outflow,
        "rotation_intensity": rotation_intensity,
    }
