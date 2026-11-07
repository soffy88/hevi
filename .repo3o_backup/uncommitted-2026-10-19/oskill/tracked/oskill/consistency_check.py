"""oskill.consistency_check — LLM-based character/scene consistency check.

Example:
    >>> from oskill.consistency_check import consistency_check
    >>> report = await consistency_check(shots=plans, llm=llm)

Raises:
    ConsistencyCheckError: Check failed.
"""

from __future__ import annotations

import json
from typing import Any

from oskill._schemas import ConsistencyReport, ShotPlan


class ConsistencyCheckError(Exception):
    """Consistency check failed."""


async def consistency_check(
    *,
    shots: list[ShotPlan],
    llm: Any,
) -> ConsistencyReport:
    """Check character and scene consistency across shots.

    Args:
        shots: List of ShotPlan objects to check.
        llm: LLMCaller protocol instance.

    Returns:
        ConsistencyReport with issues and overall_score.

    Raises:
        ConsistencyCheckError: On empty shots or LLM failure.

    Example:
        >>> report = await consistency_check(shots=plans, llm=llm)
    """
    if not shots:
        raise ConsistencyCheckError("shots must not be empty")

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "Check consistency of characters, scenes, and style across shots. "
                'Return JSON: {"issues": [{"shot_id", "description", "severity"}], '
                '"overall_score": 0.0-1.0}'
            ),
        },
        {
            "role": "user",
            "content": json.dumps([s.model_dump() for s in shots], ensure_ascii=False),
        },
    ]

    result = llm(messages=messages)
    content = result.get("content", "")

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ConsistencyCheckError(f"LLM returned invalid JSON: {content[:200]}") from exc

    try:
        return ConsistencyReport.model_validate(data)
    except Exception as exc:
        raise ConsistencyCheckError(f"Report validation failed: {exc}") from exc
