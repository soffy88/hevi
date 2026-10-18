"""oskill.reference_generator — Generate detailed image prompts per shot.

Example:
    >>> from oskill.reference_generator import reference_generator
    >>> refs = await reference_generator(shots=plans, llm=llm, style_prompt="cinematic")

Raises:
    ReferenceGeneratorError: Generation failed.
"""

from __future__ import annotations

import json
from typing import Any

from oskill._schemas import ReferenceDescription, ShotPlan


class ReferenceGeneratorError(Exception):
    """Reference generation failed."""


async def reference_generator(
    *,
    shots: list[ShotPlan],
    llm: Any,
    style_prompt: str = "",
) -> list[ReferenceDescription]:
    """Generate detailed image generation prompts for each shot.

    Args:
        shots: List of ShotPlan objects.
        llm: LLMCaller protocol instance.
        style_prompt: Global style directive to inject.

    Returns:
        List of ReferenceDescription aligned with shots.

    Raises:
        ReferenceGeneratorError: On empty shots or LLM failure.

    Example:
        >>> refs = await reference_generator(shots=plans, llm=llm)
    """
    if not shots:
        raise ReferenceGeneratorError("shots must not be empty")

    system = (
        "For each shot, generate a detailed image prompt with style tags. "
        'Return JSON array: [{"shot_id", "detailed_prompt", "style_tags": []}]'
    )
    if style_prompt:
        system += f"\nGlobal style: {style_prompt}"

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
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
        raise ReferenceGeneratorError(f"LLM returned invalid JSON: {content[:200]}") from exc

    if len(data) != len(shots):
        raise ReferenceGeneratorError(f"Count mismatch: got {len(data)}, expected {len(shots)}")

    try:
        return [ReferenceDescription.model_validate(item) for item in data]
    except Exception as exc:
        raise ReferenceGeneratorError(f"Validation failed: {exc}") from exc
