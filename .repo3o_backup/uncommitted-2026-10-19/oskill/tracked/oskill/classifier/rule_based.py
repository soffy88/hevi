"""Rule-based classification primitives.

Multi-source feature -> exclusive label mapping using deterministic
threshold rules (not ML). Used in regime classification, financial
veto checks, anomaly tagging, etc.
"""

from __future__ import annotations

import oprim

STABILITY = "experimental"


def rule_based_classifier(
    features: dict[str, float | str | bool],
    rule_table: list[dict],
) -> dict:
    """Apply a sequence of rules to features, return matched labels.

    Parameters
    ----------
    features : observation dict, e.g. {"limit_up_count": 50, "broken_rate": 0.3}
    rule_table : list of rule dicts, each like:
                 {"label": "label_name", "conditions": [
                     {"field": "field_name", "op": "gte", "value": 80},
                     ...
                 ], "exclusive": True}

    Returns
    -------
    {
        "matched_labels": list[str],   # all rules that triggered
        "scores": dict[str, float],    # per-label match strength (0-1)
        "exclusive_winner": str | None # if any exclusive rule matched, the first one
    }

    Uses: oprim.predicate.evaluate_threshold_condition

    Reference
    ---------
    Standard rule engine pattern; e.g. CLIPS, Drools.
    """
    matched_labels: list[str] = []
    scores: dict[str, float] = {}
    exclusive_winner: str | None = None

    for rule in rule_table:
        label = rule.get("label", "")
        conditions = rule.get("conditions", [])
        is_exclusive = rule.get("exclusive", False)

        if not conditions:
            continue

        n_satisfied = 0
        for cond in conditions:
            field = cond.get("field", "")
            op = cond.get("op", "eq")
            threshold = cond.get("value")

            if field not in features:
                break
            feature_val = features[field]

            if isinstance(feature_val, bool) or isinstance(feature_val, str):
                satisfied = (feature_val == threshold) if op == "eq" else (feature_val != threshold)
            else:
                satisfied = oprim.evaluate_threshold_condition(
                    float(feature_val), float(threshold), op
                )

            if satisfied:
                n_satisfied += 1
            else:
                break
        else:
            if n_satisfied == len(conditions):
                matched_labels.append(label)
                scores[label] = n_satisfied / len(conditions) if conditions else 0.0
                if is_exclusive and exclusive_winner is None:
                    exclusive_winner = label

    return {
        "matched_labels": matched_labels,
        "scores": scores,
        "exclusive_winner": exclusive_winner,
    }


def rule_based_veto_check(
    facts: dict[str, float | bool],
    veto_rules: list[dict],
) -> dict:
    """Check if any veto rule triggers based on facts.

    Parameters
    ----------
    facts : observation dict
    veto_rules : list like:
                [{"name": "ST_flag",
                  "condition": {"field": "is_st", "op": "eq", "value": True},
                  "severity": "hard"}, ...]

    Returns
    -------
    {
        "triggered_vetos": [{"name": str, "severity": str, "detail": dict}, ...],
        "hard_veto": bool,   # True if any "hard" severity rule triggered
        "soft_veto_count": int
    }

    Uses: oprim.predicate.evaluate_threshold_condition
    """
    triggered_vetos: list[dict] = []
    hard_veto = False
    soft_veto_count = 0

    for rule in veto_rules:
        name = rule.get("name", "")
        condition = rule.get("condition", {})
        severity = rule.get("severity", "soft")

        field = condition.get("field", "")
        op = condition.get("op", "eq")
        threshold = condition.get("value")

        if field not in facts:
            continue

        fact_val = facts[field]

        if isinstance(fact_val, bool) or isinstance(fact_val, str):
            triggered = (fact_val == threshold) if op == "eq" else (fact_val != threshold)
        else:
            triggered = oprim.evaluate_threshold_condition(float(fact_val), float(threshold), op)

        if triggered:
            triggered_vetos.append(
                {
                    "name": name,
                    "severity": severity,
                    "detail": {"field": field, "value": fact_val, "threshold": threshold, "op": op},
                }
            )
            if severity == "hard":
                hard_veto = True
            else:
                soft_veto_count += 1

    return {
        "triggered_vetos": triggered_vetos,
        "hard_veto": hard_veto,
        "soft_veto_count": soft_veto_count,
    }
