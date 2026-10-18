"""oskill.shot_generator — Generate image prompts and TTS text per shot.

Example:
    >>> from oskill.shot_generator import shot_generator
    >>> plans = await shot_generator(storyboard=board, llm=llm)

Raises:
    ShotGeneratorError: Generation failed.
"""

from __future__ import annotations

import json
from typing import Any

from oskill._schemas import ShotPlan, Storyboard


class ShotGeneratorError(Exception):
    """Shot generation failed."""


async def shot_generator(
    *,
    storyboard: Storyboard,
    llm: Any,
) -> list[ShotPlan]:
    """Generate image prompt and TTS text for each shot.

    Args:
        storyboard: Input Storyboard model.
        llm: LLMCaller protocol instance.

    Returns:
        List of ShotPlan objects aligned with storyboard shots.

    Raises:
        ShotGeneratorError: On empty storyboard, LLM failure, or count mismatch.

    Example:
        >>> plans = await shot_generator(storyboard=board, llm=llm)
    """
    if not storyboard.shots:
        raise ShotGeneratorError("storyboard has no shots")

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "For each shot, generate an image_prompt and tts_text. "
                'Return JSON array: [{"shot_id", "image_prompt", "tts_text", "duration_s"}]'
            ),
        },
        {
            "role": "user",
            "content": json.dumps([s.model_dump() for s in storyboard.shots], ensure_ascii=False),
        },
    ]

    result = llm(messages=messages)
    content = result.get("content", "")

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ShotGeneratorError(f"LLM returned invalid JSON: {content[:200]}") from exc

    if not isinstance(data, list):
        raise ShotGeneratorError("Expected JSON array from LLM")

    if len(data) != len(storyboard.shots):
        raise ShotGeneratorError(
            f"Shot count mismatch: got {len(data)}, expected {len(storyboard.shots)}"
        )

    try:
        return [ShotPlan.model_validate(item) for item in data]
    except Exception as exc:
        raise ShotGeneratorError(f"ShotPlan validation failed: {exc}") from exc
