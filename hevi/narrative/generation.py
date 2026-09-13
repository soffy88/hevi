"""Bounded handling for structured LLM output completion."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from hevi.narrative.models import GenerationCompletionStatus


class NarrativeGenerationError(ValueError):
    """Structured output could not be accepted."""


@dataclass(frozen=True)
class GenerationResult:
    payload: dict[str, Any]
    completion: GenerationCompletionStatus


def parse_structured_output(raw: str, completion: GenerationCompletionStatus) -> GenerationResult:
    if completion.status != "COMPLETE":
        raise NarrativeGenerationError(f"LLM_{completion.status}: structured output is not commit-ready")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NarrativeGenerationError("NARRATIVE_SCHEMA_INVALID") from exc
    if not isinstance(payload, dict) or not payload:
        raise NarrativeGenerationError("LLM_INVALID_STRUCTURE")
    return GenerationResult(payload, completion)


def bounded_continuation(chunks: list[str], max_continuations: int = 2) -> str:
    """Join bounded continuation chunks while removing exact overlap."""
    if len(chunks) - 1 > max_continuations:
        raise NarrativeGenerationError("REVISION_LIMIT")
    result = ""
    for chunk in chunks:
        overlap = _overlap(result, chunk)
        result += chunk[overlap:]
    return result


def _overlap(left: str, right: str) -> int:
    for size in range(min(len(left), len(right)), 0, -1):
        if left.endswith(right[:size]):
            return size
    return 0
