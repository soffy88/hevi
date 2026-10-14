"""OMQUALITY appearance layer — public API for the post-render review gate.

A thin facade over :mod:`hevi.layer4_legacy.review`.  Same idiom as
``hevi.talkcraft`` (which sits over ``hevi.layer4_legacy.talkcraft``): callers
import the omodul-backed function from the top-level module.
"""

from __future__ import annotations

from typing import Any

from hevi.layer4_legacy.review.omodul_impl.review_workflow import (
    REVIEW_OPS,
    ReviewUnavailable,
    review_finished_video_workflow,
)

__all__ = [
    "REVIEW_OPS",
    "ReviewUnavailable",
    "review_finished_video",
]


def review_finished_video(
    *,
    input_path: str,
    output_dir: str,
    config: dict[str, Any] | None = None,
    input_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience wrapper for :func:`review_finished_video_workflow`."""
    return review_finished_video_workflow(
        dict(config or {}), dict(input_data or {"input_path": input_path}), output_dir
    )
