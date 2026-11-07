"""oskill.metadata_generate — Generate platform-agnostic video metadata via LLM.

Example:
    >>> from oskill.metadata_generate import metadata_generate
    >>> meta = await metadata_generate(script=script, storyboard=board, llm=llm, ...)

Raises:
    MetadataGenerateError: Generation failed.
"""

from __future__ import annotations

import json
from typing import Any

from oskill._schemas import Metadata, MetadataConstraints, Script, Storyboard


class MetadataGenerateError(Exception):
    """Metadata generation failed."""


async def metadata_generate(
    *,
    script: Script,
    storyboard: Storyboard,
    llm: Any,
    constraints: MetadataConstraints,
    style_prompt: str,
) -> Metadata:
    """Generate video metadata (title, description, tags, topics).

    Args:
        script: Video script.
        storyboard: Video storyboard.
        llm: LLMCaller protocol instance.
        constraints: Platform constraints (max chars, max tags, etc.).
        style_prompt: Tone/style directive.

    Returns:
        Metadata model with title, description, tags, topics.

    Raises:
        MetadataGenerateError: On empty script or LLM failure.

    Example:
        >>> meta = await metadata_generate(script=script, storyboard=board, llm=llm, ...)
    """
    if not script.scenes:
        raise MetadataGenerateError("script has no scenes")

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                f"Generate video metadata. Style: {style_prompt}. "
                f"Constraints: title≤{constraints.title_max_chars} chars, "
                f"description≤{constraints.description_max_chars} chars, "
                f"≤{constraints.tags_max_count} tags (each ≤{constraints.tag_max_chars} chars). "
                'Return JSON: {"title", "description", "tags": [], "topics": []}'
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "script_title": script.title,
                    "script_description": script.description,
                    "scenes_count": len(script.scenes),
                    "shots_count": len(storyboard.shots),
                }
            ),
        },
    ]

    result = llm(messages=messages)
    content = result.get("content", "")

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise MetadataGenerateError(f"LLM returned invalid JSON: {content[:200]}") from exc

    try:
        meta = Metadata.model_validate(data)
    except Exception as exc:
        raise MetadataGenerateError(f"Metadata validation failed: {exc}") from exc

    # Enforce constraints with truncation fallback
    meta.title = meta.title[: constraints.title_max_chars]
    meta.description = meta.description[: constraints.description_max_chars]
    meta.tags = [t[: constraints.tag_max_chars] for t in meta.tags[: constraints.tags_max_count]]

    return meta
