"""B7 — LLM batch classification."""

from __future__ import annotations

import json
from typing import Any, Protocol


class LLMCaller(Protocol):
    def call(self, prompt: str) -> str: ...


def llm_batch_classify(
    *,
    items: list[dict[str, Any]],
    labels: list[str],
    llm: LLMCaller,
    batch_size: int = 10,
    multi_label: bool = False,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """Classify items into labels using LLM in batches.

    Parameters
    ----------
    items : list of dicts to classify (each must have 'text' or 'content' key)
    labels : available classification labels
    llm : object with .call(prompt) -> str method
    batch_size : items per LLM call
    multi_label : allow multiple labels per item
    system_prompt : optional system prompt override

    Returns
    -------
    dict with: results (list of {item, labels, confidence}), errors, cost_usd
    """
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    total_cost = 0.0

    if not items:
        return {"results": [], "errors": [], "cost_usd": 0.0}

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        prompt = _build_prompt(batch, labels, multi_label, system_prompt)

        try:
            response = llm.call(prompt)
            parsed = _parse_response(response, batch, labels, multi_label)
            results.extend(parsed)
            total_cost += 0.001 * len(batch)  # Approximate cost
        except Exception as e:
            for item in batch:
                errors.append({"item": item, "error": str(e)})

    return {"results": results, "errors": errors, "cost_usd": round(total_cost, 6)}


def _build_prompt(
    batch: list[dict[str, Any]],
    labels: list[str],
    multi_label: bool,
    system_prompt: str | None,
) -> str:
    items_text = "\n".join(
        f"{i + 1}. {item.get('text', item.get('content', str(item)))}"
        for i, item in enumerate(batch)
    )
    label_str = ", ".join(labels)
    mode = "one or more" if multi_label else "exactly one"
    base = system_prompt or "You are a classifier."
    return f"""{base}

Classify each item into {mode} of these labels: [{label_str}]

Items:
{items_text}

Respond in JSON: [{{"item_idx": 1, "labels": ["label1"]}}]"""


def _parse_response(
    response: str,
    batch: list[dict[str, Any]],
    labels: list[str],
    multi_label: bool,
) -> list[dict[str, Any]]:
    """Parse LLM response, with fallback."""
    try:
        # Try to extract JSON from response
        start = response.find("[")
        end = response.rfind("]") + 1
        if start >= 0 and end > start:
            parsed = json.loads(response[start:end])
        else:
            parsed = json.loads(response)
    except (json.JSONDecodeError, ValueError):
        # Fallback: assign first label to all
        return [
            {"item": item, "labels": [labels[0]] if labels else [], "confidence": 0.0}
            for item in batch
        ]

    results = []
    for entry in parsed:
        idx = entry.get("item_idx", 0) - 1
        if 0 <= idx < len(batch):
            item_labels = entry.get("labels", [])
            if not multi_label and len(item_labels) > 1:
                item_labels = item_labels[:1]
            results.append({"item": batch[idx], "labels": item_labels, "confidence": 0.8})

    # Fill missing items
    {r.get("item", {}).get("_idx") for r in results}
    for i, item in enumerate(batch):
        if i not in {
            entry.get("item_idx", 0) - 1 for entry in (parsed if isinstance(parsed, list) else [])
        }:
            if len(results) < len(batch):
                results.append(
                    {"item": item, "labels": [labels[0]] if labels else [], "confidence": 0.0}
                )

    return results[: len(batch)]
