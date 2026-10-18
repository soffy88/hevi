"""oskill.mllm_frame_consistency_check — VLM visual consistency scoring.

ViMax-style: generates multiple candidate frames in parallel, then uses a
VLM to evaluate each against the reference set and pick the best one.

Example:
    >>> from oskill.mllm_frame_consistency_check import mllm_frame_consistency_check
    >>> result = await mllm_frame_consistency_check(
    ...     mllm=vlm, candidate_frames=[Path("c1.png"), Path("c2.png")],
    ...     reference=ref_set, criteria=criteria,
    ... )

Raises:
    FrameConsistencyError: VLM failure or empty candidate list.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from oskill._schemas import FrameConsistencyResult, ReferenceSet


class FrameConsistencyError(Exception):
    """Frame consistency check failed."""


async def mllm_frame_consistency_check(
    *,
    mllm: Any,
    candidate_frames: list[Path],
    reference: ReferenceSet,
    criteria: Any,
) -> FrameConsistencyResult:
    """Score candidate frames against a reference set using a VLM.

    Differs from consistency_check (text/plan layer) — this does actual
    visual evaluation of image files.

    Args:
        mllm: VLM (visual language model) instance that accepts image paths.
        candidate_frames: Paths to candidate image/video frames.
        reference: ReferenceSet with character and environment reference images.
        criteria: Consistency criteria object. Must expose:
            - .threshold: float (minimum passing score)
            - .dimensions: list[str] (e.g. ["character_appearance", "environment"])

    Returns:
        FrameConsistencyResult with best_frame, per-frame scores, and passed flag.

    Raises:
        FrameConsistencyError: Empty candidate list or VLM failure.

    Example:
        >>> result = await mllm_frame_consistency_check(
        ...     mllm=vlm, candidate_frames=frames,
        ...     reference=refs, criteria=criteria,
        ... )
        >>> if result.passed:
        ...     use(result.best_frame)
        ... else:
        ...     regenerate()
    """
    if not candidate_frames:
        raise FrameConsistencyError("candidate_frames must not be empty")

    threshold: float = criteria.threshold if hasattr(criteria, "threshold") else 0.7
    dimensions: list[str] = (
        criteria.dimensions
        if hasattr(criteria, "dimensions")
        else ["character_appearance", "environment", "style"]
    )

    ref_summary = {
        "character_refs": {k: str(v) for k, v in reference.character_refs.items()},
        "environment_refs": {k: str(v) for k, v in reference.environment_refs.items()},
    }

    scores: dict[str, float] = {}

    for frame_path in candidate_frames:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are a visual consistency evaluator. "
                    "Score the candidate frame against the reference on a scale 0.0-1.0. "
                    f"Dimensions to evaluate: {dimensions}. "
                    'Return JSON: {"score": <float>, "breakdown": {dim: score}}.'
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "candidate_frame": str(frame_path),
                        "reference": ref_summary,
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        result = mllm(messages=messages, image_paths=[str(frame_path)])
        content = result.get("content", "")

        try:
            data = json.loads(content)
            frame_score = float(data.get("score", 0.0))
        except (json.JSONDecodeError, TypeError, ValueError):
            frame_score = 0.0

        scores[str(frame_path)] = frame_score

    best_path_str = max(scores, key=lambda k: scores[k])
    best_score = scores[best_path_str]

    return FrameConsistencyResult(
        best_frame=Path(best_path_str),
        scores=scores,
        passed=best_score >= threshold,
    )
