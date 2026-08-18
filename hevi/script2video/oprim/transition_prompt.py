"""机位过渡视频的文本条件。

3O 归属(待上游): `oprim.transition_prompt`。
"""

from __future__ import annotations


def build_transition_prompt(
    first_shot_visual_desc: str,
    second_shot_visual_desc: str,
    *,
    missing_info: str | None = None,
    duration_s: float = 2.0,
) -> str:
    parts = [
        "Two shots. The transition between the shots is a cut to. "
        "The style of the two shots should be consistent.",
        f"The first shot description: {first_shot_visual_desc}.",
        f"The second shot description: {second_shot_visual_desc}.",
        f"Duration: {duration_s:.1f}s.",
    ]
    if missing_info:
        parts.append(f"The transition should naturally introduce: {missing_info}.")
    parts.append("Maintain visual continuity and consistent lighting throughout.")
    return " ".join(parts)
