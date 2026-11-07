"""oskill.storyboard_planner — Break script into shots.

Example:
    >>> from oskill.storyboard_planner import storyboard_planner
    >>> board = await storyboard_planner(script=script, llm=llm)

Raises:
    StoryboardPlannerError: Planning failed.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

from oprim.lighting_control_prompt import lighting_control_prompt
from oprim.style_marker_prompt import style_marker_prompt

from oskill._schemas import Script, Storyboard, SubjectRef


class StoryboardPlannerError(Exception):
    """Storyboard planning failed."""


async def storyboard_planner(
    *,
    script: Script,
    llm: Any,
    shots_per_scene_min: int = 3,
    shots_per_scene_max: int = 10,
    subjects: list[SubjectRef] | None = None,
    style_marker: str | None = None,
    lighting_control: str | None = None,
) -> Storyboard:
    """Break a script into a shot-level storyboard.

    Args:
        script: Input Script model.
        llm: LLMCaller protocol instance.
        shots_per_scene_min: Minimum shots per scene.
        shots_per_scene_max: Maximum shots per scene.
        subjects: Optional character/subject references. When provided, each
            subject's name and description are injected into the system prompt
            so the LLM assigns characters to shots. Default None (backward compat).
        style_marker: Overall visual style ("科普" / "严肃" / "搞笑" etc.).
            Injected via oprim.style_marker_prompt into the system prompt.
            Default None — no style injection (backward compat).
        lighting_control: Overall lighting mood ("暖" / "冷" / "戏剧" etc.).
            Injected via oprim.lighting_control_prompt into the system prompt.
            Default None — no lighting injection (backward compat).

    Returns:
        Storyboard with list of Shot objects.

    Raises:
        StoryboardPlannerError: On empty script, LLM failure, or invalid response.

    Example:
        >>> board = await storyboard_planner(script=script, llm=llm)
        >>> board = await storyboard_planner(
        ...     script=script, llm=llm,
        ...     style_marker="科普", lighting_control="暖",
        ... )
    """
    if not script.scenes:
        raise StoryboardPlannerError("script has no scenes")

    system_content = (
        f"Break each scene into {shots_per_scene_min}-{shots_per_scene_max} shots. "
        'Return JSON: {"shots": [{"shot_id", "scene_index", "visual_description", '
        '"narration", "duration_s", "importance", '
        "\"motion\": str|null (e.g. 'pan_left', 'zoom_in', 'static', or null)}]}"
    )

    # P7-B4: inject subjects, style and lighting into system prompt
    if subjects:
        char_lines = "\n".join(
            f"{s.name}: {s.description}" if s.description else s.name for s in subjects
        )
        system_content = system_content + f"\n以下角色将出现在分镜中:\n{char_lines}"

    if style_marker is not None:
        system_content = style_marker_prompt(
            base_prompt=system_content,
            style=style_marker,  # type: ignore[arg-type]
        )

    if lighting_control is not None:
        system_content = lighting_control_prompt(
            base_prompt=system_content,
            lighting=lighting_control,  # type: ignore[arg-type]
        )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_content},
        {
            "role": "user",
            # B7: script.scenes 可能是 list[dict](Chapter.scenes)或 list[Scene](Script.scenes);
            # dict 无 model_dump,故按需转换,不再无条件调用 .model_dump()。
            "content": json.dumps(
                [s.model_dump() if hasattr(s, "model_dump") else s for s in script.scenes],
                ensure_ascii=False,
            ),
        },
    ]

    result = llm(messages=messages)
    if inspect.isawaitable(result):
        result = await result
    content = result.get("content", "")

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise StoryboardPlannerError(f"LLM returned invalid JSON: {content[:200]}") from exc

    try:
        return Storyboard.model_validate(data)
    except Exception as exc:
        raise StoryboardPlannerError(f"Storyboard validation failed: {exc}") from exc
