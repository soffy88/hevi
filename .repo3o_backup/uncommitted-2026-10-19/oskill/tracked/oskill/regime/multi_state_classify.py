"""Multi-state regime classification using rule-based state definitions."""

from __future__ import annotations

from oskill.classifier.rule_based import rule_based_classifier

STABILITY = "experimental"


def multi_state_classify(
    indicators: dict[str, float],
    state_definitions: list[dict],
    transition_rules: dict | None = None,
    prev_state: str | None = None,
    n_states_constraint: int | None = None,
) -> dict:
    """Classify the current regime state based on indicators and rule-based state definitions.

    Parameters
    ----------
    indicators : current observation, e.g. {"limit_up_count": 50, "broken_rate": 0.3}
    state_definitions : list of state rules, each like:
                       {"name": "hot", "conditions": [...], "priority": 1}
                       (passed to rule_based_classifier)
    transition_rules : optional Markov transition matrix for state filtering
                       (e.g. allow "hot" only if prev_state in {"warm", "hot"})
    prev_state : optional previous state for transition validation
    n_states_constraint : if provided, validate len(state_definitions) == n_states_constraint

    Returns
    -------
    {
        "current_state": str,
        "confidence": float,
        "matched_states": list[str],
        "transition_valid": bool
    }

    Methodology
    -----------
    Combines rule-based classifier with optional Markov transition validation.
    State definitions are caller-provided (market-agnostic):
    - A-share emotion 6-state: caller provides 6 state defs
    - China macro 8-indicator -> 3 tags: caller provides 8 indicator rules
    - US sector rotation: caller provides sector rules

    Uses: oskill.classifier.rule_based.rule_based_classifier,
          oprim.regime.regime_transition_matrix (if transitions provided)

    Reference
    ---------
    Hamilton, J. D. (1989). A new approach to the economic analysis of
    nonstationary time series. Econometrica, 57(2), 357-384.
    """
    rule_table = [
        {
            "label": sd["name"],
            "conditions": sd.get("conditions", []),
            "exclusive": sd.get("exclusive", True),
        }
        for sd in state_definitions
    ]

    if n_states_constraint is not None and len(state_definitions) != n_states_constraint:
        raise ValueError(
            f"n_states_constraint={n_states_constraint} but got {len(state_definitions)} state_definitions"
        )

    classification = rule_based_classifier(indicators, rule_table)
    matched_states = classification["matched_labels"]
    scores = classification["scores"]

    if matched_states:
        sorted_states = sorted(
            state_definitions,
            key=lambda sd: sd.get("priority", 999),
        )
        selected_state = None
        confidence = 0.0
        for sd in sorted_states:
            if sd["name"] in matched_states:
                selected_state = sd["name"]
                confidence = scores.get(sd["name"], 1.0)
                break

        if selected_state is None:
            selected_state = matched_states[0]
            confidence = scores.get(selected_state, 1.0)
    else:
        selected_state = "unknown"
        confidence = 0.0

    transition_valid = True
    if transition_rules is not None and prev_state is not None and selected_state != "unknown":
        allowed_next = set(transition_rules.get(prev_state, {selected_state}))
        transition_valid = selected_state in allowed_next

    return {
        "current_state": selected_state,
        "confidence": confidence,
        "matched_states": matched_states,
        "transition_valid": transition_valid,
        "n_states": len(state_definitions),
    }
