"""Multi-model ensemble — aggregate responses from multiple LLM models."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from typing import Any, Literal

from oprim import canonical_json, sha256_hash


def multi_model_ensemble(
    prompt_template: str,
    variables: dict[str, Any],
    client_fns: dict[str, Callable[..., dict]],
    *,
    model_configs: dict[str, dict],
    aggregation: Literal[
        "majority_vote", "weighted_vote", "score_averaging", "agreement_only"
    ] = "majority_vote",
    weights: dict[str, float] | None = None,
    response_format: Literal["text", "json", "label"] = "label",
    label_extractor: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Aggregate responses from multiple LLMs using ensemble voting.

    Workflow:
        1. Validate client_fns.keys() == model_configs.keys()
        2. Format prompt from template + variables
        3. Call each client_fn with its model config
        4. Extract label/score from each response
        5. Aggregate per method (majority_vote / weighted_vote / score_averaging /
           agreement_only)
        6. Compute ensemble_fingerprint via oprim.canonical_json + oprim.sha256_hash

    Parameters
    ----------
    prompt_template : str
        Prompt template with {variable} placeholders.
    variables : dict
        Values for template placeholders.
    client_fns : dict[str, callable]
        Mapping from model_key → (messages, model, **kwargs) -> dict.
    model_configs : dict[str, dict]
        Mapping from model_key → kwargs to pass to client_fn (must include 'model').
    aggregation : str
        Aggregation method.
    weights : dict[str, float] or None
        Per-model weight for weighted_vote aggregation.
    response_format : str
        Expected response format.
    label_extractor : callable or None
        Custom (str) -> str to extract label from response text.

    Returns
    -------
    dict with keys: 'consensus_label', 'agreement_score', 'per_model_responses',
    'aggregation_method', 'is_unanimous', 'has_consensus', 'ensemble_fingerprint'

    Raises
    ------
    ValueError
        If client_fns and model_configs keys don't match, invalid aggregation,
        or weights keys mismatch.
    """
    valid_aggregations = {"majority_vote", "weighted_vote", "score_averaging", "agreement_only"}
    if aggregation not in valid_aggregations:
        raise ValueError(
            f"Invalid aggregation: {aggregation!r}. Must be one of {sorted(valid_aggregations)}"
        )

    # 1. Validate keys match
    fn_keys = set(client_fns.keys())
    cfg_keys = set(model_configs.keys())
    if fn_keys != cfg_keys:
        raise ValueError(
            f"client_fns keys {sorted(fn_keys)} do not match model_configs keys {sorted(cfg_keys)}"
        )

    if weights is not None:
        w_keys = set(weights.keys())
        if w_keys != fn_keys:
            raise ValueError(
                f"weights keys {sorted(w_keys)} do not match client_fns keys {sorted(fn_keys)}"
            )

    # 2. Format prompt
    prompt_rendered = prompt_template.format(**variables)
    messages = [{"role": "user", "content": prompt_rendered}]

    # 3. Call each client_fn
    per_model_responses: dict[str, Any] = {}
    per_model_labels: dict[str, str] = {}

    # Keep deterministic ordering (sort keys)
    ordered_keys = sorted(client_fns.keys())

    for key in ordered_keys:
        cfg = dict(model_configs[key])  # copy to avoid mutation
        model_id = cfg.pop("model", key)
        result = client_fns[key](messages, model_id, **cfg)
        content = result.get("content", "")

        # 4. Extract label/score
        label = _extract_label(content, response_format, label_extractor)

        per_model_responses[key] = {
            "content": content,
            "label": label,
            "model": model_id,
            "stop_reason": result.get("stop_reason"),
            "input_tokens": result.get("input_tokens"),
            "output_tokens": result.get("output_tokens"),
        }
        per_model_labels[key] = label

    # 5. Aggregate
    consensus_label, agreement_score, is_unanimous, has_consensus = _aggregate(
        per_model_labels, aggregation, weights
    )

    # 6. Compute fingerprint
    fingerprint_payload = {
        "per_model_responses": per_model_responses,
        "aggregation": aggregation,
        "model_configs": {k: model_configs[k] for k in ordered_keys},
        "prompt_template": prompt_template,
        "variables": variables,
    }
    ensemble_fingerprint = sha256_hash(canonical_json(fingerprint_payload))

    return {
        "consensus_label": consensus_label,
        "agreement_score": agreement_score,
        "per_model_responses": per_model_responses,
        "aggregation_method": aggregation,
        "is_unanimous": is_unanimous,
        "has_consensus": has_consensus,
        "ensemble_fingerprint": ensemble_fingerprint,
    }


def _extract_label(
    content: str,
    response_format: str,
    label_extractor: Callable[[str], str] | None,
) -> str:
    """Extract a label from raw LLM output."""
    if label_extractor is not None:
        return label_extractor(content)

    if response_format == "json":
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return str(parsed.get("label", parsed.get("answer", content)))
            return content
        except (json.JSONDecodeError, TypeError):
            return content.strip()

    # For "label" and "text" formats: use the content directly (stripped)
    return content.strip()


def _aggregate(
    per_model_labels: dict[str, str],
    aggregation: str,
    weights: dict[str, float] | None,
) -> tuple[str, float, bool, bool]:
    """Aggregate labels. Returns (consensus_label, agreement_score, is_unanimous, has_consensus)."""
    labels = list(per_model_labels.values())
    n = len(labels)

    if n == 0:
        return "no_consensus", 0.0, False, False

    if aggregation == "majority_vote":
        counter = Counter(labels)
        # Stable tie-breaking: among tied labels, pick the one that appears first
        # in sorted(per_model_labels.items()) ordering
        max_count = counter.most_common(1)[0][1]
        tied_labels = [lbl for lbl, cnt in counter.items() if cnt == max_count]
        if len(tied_labels) == 1:
            consensus_label = tied_labels[0]
        else:
            # Preserve first-occurrence order
            for lbl in labels:
                if lbl in tied_labels:
                    consensus_label = lbl
                    break
            else:
                consensus_label = tied_labels[0]
        agreement_score = max_count / n
        is_unanimous = max_count == n
        has_consensus = True

    elif aggregation == "weighted_vote":
        if weights is None:
            # Equal weights fallback
            weights = {k: 1.0 for k in per_model_labels}
        weighted_sums: dict[str, float] = {}
        for key, label in per_model_labels.items():
            w = weights.get(key, 1.0)
            weighted_sums[label] = weighted_sums.get(label, 0.0) + w
        consensus_label = max(weighted_sums, key=lambda k: weighted_sums[k])
        total_weight = sum(weights.values())
        agreement_score = weighted_sums[consensus_label] / total_weight if total_weight > 0 else 0.0
        counter = Counter(labels)
        is_unanimous = len(set(labels)) == 1
        has_consensus = True

    elif aggregation == "score_averaging":
        scores: list[float] = []
        for label in labels:
            try:
                # Try to parse as float directly
                score = float(label)
            except (ValueError, TypeError):
                # Try to parse as JSON and extract 'score'
                try:
                    parsed = json.loads(label)
                    score = float(parsed.get("score", 0.0)) if isinstance(parsed, dict) else 0.0
                except (json.JSONDecodeError, TypeError, ValueError):
                    score = 0.0
            scores.append(score)
        mean_score = sum(scores) / len(scores) if scores else 0.0
        consensus_label = str(mean_score)
        agreement_score = 1.0 - (max(scores) - min(scores)) / (max(abs(s) for s in scores) + 1e-9)
        agreement_score = max(0.0, min(1.0, agreement_score))
        is_unanimous = len(set(scores)) == 1
        has_consensus = True

    elif aggregation == "agreement_only":
        unique_labels = set(labels)
        if len(unique_labels) == 1:
            consensus_label = labels[0]
            agreement_score = 1.0
            is_unanimous = True
            has_consensus = True
        else:
            consensus_label = "no_consensus"
            agreement_score = 0.0
            is_unanimous = False
            has_consensus = False
    else:
        raise ValueError(f"Unknown aggregation: {aggregation!r}")

    return consensus_label, agreement_score, is_unanimous, has_consensus
