"""Reference limits for multi-modal shot generation."""

from __future__ import annotations

from typing import Any

MAX_REFERENCES = {"images": 9, "videos": 3, "audios": 3}
MAX_PROMPT_CHARS = 5000


def validate_multimodal_references(
    *,
    images: list[str] | None = None,
    videos: list[str] | None = None,
    audios: list[str] | None = None,
    prompt: str = "",
) -> list[str]:
    errors: list[str] = []
    values = {"images": images or [], "videos": videos or [], "audios": audios or []}
    for kind, items in values.items():
        if len(items) > MAX_REFERENCES[kind]:
            errors.append(f"{kind} reference limit is {MAX_REFERENCES[kind]}")
    if len(prompt) > MAX_PROMPT_CHARS:
        errors.append(f"prompt exceeds {MAX_PROMPT_CHARS} characters")
    return errors


def reference_grid(*, images: list[str], columns: int = 3) -> dict[str, Any]:
    if columns < 1:
        raise ValueError("columns must be positive")
    return {
        "images": list(images),
        "columns": columns,
        "rows": (len(images) + columns - 1) // columns,
        "mode": "first_frame_grid",
    }


__all__ = ["MAX_PROMPT_CHARS", "MAX_REFERENCES", "reference_grid", "validate_multimodal_references"]
