"""Long video shot continuity compiler."""

from __future__ import annotations


def normalize_shot_prompts(prompts: list[str] | tuple[str, ...]) -> list[dict[str, object]]:
    return [
        {
            "shot_index": index,
            "prompt": str(prompt).strip(),
            "continuity": "carry_previous_last_frame" if index else "initial_frame",
        }
        for index, prompt in enumerate(prompts)
        if str(prompt).strip()
    ]


__all__ = ["normalize_shot_prompts"]
