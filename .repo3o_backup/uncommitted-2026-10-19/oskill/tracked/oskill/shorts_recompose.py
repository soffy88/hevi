"""oskill.shorts_recompose — Long video → shorts by importance selection.

Example:
    >>> from oskill.shorts_recompose import shorts_recompose
    >>> path = await shorts_recompose(full_video_path=Path("full.mp4"), storyboard=board, ...)

Raises:
    ShortsRecomposeError: Recomposition failed.
"""

from __future__ import annotations

from pathlib import Path

from oskill._schemas import Storyboard


class ShortsRecomposeError(Exception):
    """Shorts recomposition failed."""


async def shorts_recompose(
    *,
    full_video_path: Path,
    storyboard: Storyboard,
    target_duration_s: float = 45.0,
    output_path: Path,
) -> Path:
    """Create a short-form video from a long video by selecting important shots.

    Args:
        full_video_path: Source long video.
        storyboard: Storyboard with shot importance scores.
        target_duration_s: Target shorts duration (30-60s).
        output_path: Destination file.

    Returns:
        The output_path on success.

    Raises:
        ShortsRecomposeError: On validation failure or processing error.

    Example:
        >>> path = await shorts_recompose(full_video_path=Path("full.mp4"), storyboard=board, ...)
    """
    if not full_video_path.exists():
        raise ShortsRecomposeError(f"Video not found: {full_video_path}")

    if not storyboard.shots:
        raise ShortsRecomposeError("storyboard has no shots")

    if target_duration_s < 30 or target_duration_s > 60:
        raise ShortsRecomposeError("target_duration_s must be 30-60")

    # Select shots by importance until target duration reached
    sorted_shots = sorted(storyboard.shots, key=lambda s: s.importance, reverse=True)
    selected_duration = 0.0
    selected_shots = []
    for shot in sorted_shots:
        if selected_duration + shot.duration_s > target_duration_s:
            break
        selected_shots.append(shot)
        selected_duration += shot.duration_s

    if not selected_shots:
        raise ShortsRecomposeError("No shots fit within target duration")

    # Re-order by scene_index for narrative coherence
    selected_shots.sort(key=lambda s: (s.scene_index, s.shot_id))

    from oprim import video_recompose

    # Recompose to vertical format
    await video_recompose(
        input_path=full_video_path,
        output_path=output_path,
        target_width=1080,
        target_height=1920,
    )

    return output_path
