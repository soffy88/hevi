"""JSON extraction from LLM response (LLMs sometimes wrap in markdown)."""

from __future__ import annotations

import json
import re


def extract_json(text: str) -> dict | None:
    """Try to parse JSON from LLM response.

    Handles:
    - Pure JSON: {...}
    - Markdown wrapped: ```json\\n{...}\\n```
    - Leading/trailing prose: "Sure! Here is the JSON:\\n{...}"

    Returns dict on success, None on any failure (caller decides fallback).
    """
    if not text:
        return None

    # Try direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # Try markdown extraction
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try first {...} block (greedy across whole text)
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    return None


def coerce_confidence(parsed: dict | None, default: float = 50.0) -> float:
    """Extract confidence field, clamp to [0, 100]."""
    if not parsed:
        return default
    val = parsed.get("confidence", default)
    try:
        v = float(val)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(100.0, v))
