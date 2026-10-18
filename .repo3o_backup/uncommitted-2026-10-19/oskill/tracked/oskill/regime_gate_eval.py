"""oskill.regime_gate_eval — Gate a trading signal by current market regime.

Composites:
    - oskill.hmm_regime_detect  (decode current regime)
    - oprim.risk_limit_check    (enforce desirable-regime threshold)
"""

from __future__ import annotations

from typing import Any


def regime_gate_eval(
    features: Any,
    *,
    desirable_regimes: list[int],
    trained_model: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate whether the current regime is suitable for trading.

    Composites used:
        1. oskill.hmm_regime_detect — decodes the most-likely current regime
           from *features* using a pre-trained HMM.
        2. oprim.risk_limit_check  — applies a custom rule to reject the
           current bar when the active regime is not in *desirable_regimes*.

    Args:
        features: Recent observation array-like passed to hmm_regime_detect.
        desirable_regimes: List of regime integer labels deemed tradeable.
        trained_model: Pre-fitted model dict (output of hmm_regime_detect
            or hmm_baum_welch).

    Returns:
        Dict with keys:

        - ``gate_open``       – True when the current regime is desirable.
        - ``current_regime``  – Integer label of the detected regime.
        - ``desirable_regimes`` – The list passed as input.
        - ``regime_result``   – Full hmm_regime_detect output.
        - ``risk_check``      – Full risk_limit_check output.
    """
    from oprim.risk_limit_check import risk_limit_check  # noqa: PLC0415

    from oskill.hmm_regime_detect import hmm_regime_detect  # noqa: PLC0415

    regime_result = hmm_regime_detect(
        features,
        n_regimes=trained_model.get("n_states", 2),
        trained_model=trained_model,
    )
    current_regime = regime_result["current_regime"]

    # Encode desirability as a custom rule:
    # value = 1.0 if current_regime is desirable, 0.0 otherwise.
    # The rule fails (below 1.0) when the regime is undesirable.
    is_desirable = 1.0 if current_regime in desirable_regimes else 0.0
    risk_check = risk_limit_check(
        0.0,  # position_value placeholder (not used for this gate)
        max_position=1.0,
        rules=[
            {
                "name": "regime_gate",
                "limit": 1.0,
                "value": is_desirable,
                "direction": "below",
            }
        ],
    )

    gate_open = risk_check["pass"]

    return {
        "gate_open": gate_open,
        "current_regime": current_regime,
        "desirable_regimes": desirable_regimes,
        "regime_result": regime_result,
        "risk_check": risk_check,
    }
