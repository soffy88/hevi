"""oskill.market_impact_sigmoid — Sigmoid market-impact model (no square-root law).

Composites:
    - oprim.risk_limit_check  (parameter validation gate)
    - oprim.zscore_signal     (participation-rate normalisation)

⚠️  Forbidden: square-root law.  Only sigmoid is used.
⚠️  Missing required params → raise ValueError.  No silent 100bps fallback.
"""

from __future__ import annotations

from typing import Any


def market_impact_sigmoid(
    notional: float,
    *,
    adv: float,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Estimate market impact (bps) via a sigmoid participation-rate model.

    The model:
        participation = notional / adv
        impact_bps    = alpha / (1 + exp(−beta × (participation − gamma)))

    where ``alpha``, ``beta``, ``gamma`` must be present in *params*.

    Composites used:
        1. oprim.risk_limit_check — validates that required parameters are
           within acceptable bounds before computation.
        2. oprim.zscore_signal   — normalises the participation rate against
           a reference distribution when ``adv_series`` is supplied.

    Args:
        notional: Trade size in USD (or native currency).
        adv: Average daily volume in the same currency.
        params: Model parameters dict.  Required keys:

            - ``alpha``  – Maximum impact in basis points (must be > 0).
            - ``beta``   – Steepness of the sigmoid (must be > 0).
            - ``gamma``  – Inflection point (participation rate).

            Optional keys:

            - ``adv_series`` – Historical ADV list for z-score normalisation.
            - ``max_impact_bps`` – Hard cap; impact is clipped to this value.

    Returns:
        Dict with keys:

        - ``impact_bps``       – Estimated market impact in basis points.
        - ``participation``    – notional / adv.
        - ``alpha``, ``beta``, ``gamma`` – Parameters used.
        - ``capped``           – True if ``max_impact_bps`` was applied.

    Raises:
        ValueError: If ``alpha``, ``beta``, or ``gamma`` is missing from
            *params*, or if *adv* ≤ 0.
    """
    import math  # noqa: PLC0415

    from oprim.risk_limit_check import risk_limit_check  # noqa: PLC0415

    # Validate required params — raise immediately, never fall back to 100bps
    for key in ("alpha", "beta", "gamma"):
        if key not in params:
            raise ValueError(f"market_impact_sigmoid: missing required param {key!r}")

    alpha = float(params["alpha"])
    beta = float(params["beta"])
    gamma = float(params["gamma"])

    if alpha <= 0:
        raise ValueError(f"alpha must be > 0, got {alpha}")
    if beta <= 0:
        raise ValueError(f"beta must be > 0, got {beta}")
    if adv <= 0:
        raise ValueError(f"adv must be > 0, got {adv}")

    # Composite 1: risk_limit_check to validate param bounds
    gate = risk_limit_check(
        alpha,
        max_position=100_000.0,  # alpha in bps should be well below this
        rules=[
            {"name": "alpha_positive", "limit": 0.0, "value": alpha, "direction": "below"},
            {"name": "beta_positive", "limit": 0.0, "value": beta, "direction": "below"},
        ],
    )
    if not gate["pass"]:
        raise ValueError(f"Invalid param detected by risk_limit_check: {gate['violated_rule']}")

    participation = notional / adv

    # Composite 2: optional z-score normalisation of participation rate
    adv_series = params.get("adv_series")
    if adv_series and len(adv_series) >= 2:
        from oprim.zscore_signal import zscore_signal  # noqa: PLC0415

        lookback = min(len(adv_series), 20)
        zs = zscore_signal(adv_series, lookback=lookback)
        # Adjust participation by ADV z-score: high ADV day → lower impact
        adv_z = zs["zscore"]
        participation = participation * (1.0 / (1.0 + max(0.0, adv_z) * 0.1))

    # Sigmoid — strictly no square-root law
    impact_bps = alpha / (1.0 + math.exp(-beta * (participation - gamma)))

    max_impact = params.get("max_impact_bps")
    capped = False
    if max_impact is not None and impact_bps > float(max_impact):
        impact_bps = float(max_impact)
        capped = True

    return {
        "impact_bps": impact_bps,
        "participation": participation,
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma,
        "capped": capped,
    }
