"""oskill.video_self_assess — VLM-based video quality self-assessment.

Combines oprim.video_quality_metrics + frame extraction + oprim.vlm_video_analyze.

Example:
    >>> from oskill.video_self_assess import video_self_assess
    >>> score = await video_self_assess(
    ...     video_path=Path("video.mp4"), script=script, vlm=my_vlm,
    ... )

Raises:
    VideoSelfAssessError: Assessment failed.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from oskill._schemas import Script


class VideoSelfAssessError(Exception):
    """Video self-assessment failed."""


class VideoQualityScore(BaseModel):
    """Multi-dimensional video quality score."""

    script_score: float
    visual_score: float
    pacing_score: float
    overall_score: float
    issues: list[str]
    suggestions: list[str]


async def video_self_assess(
    *,
    video_path: Path,
    script: Script,
    vlm: Any,
    sample_frames_count: int = 10,
) -> VideoQualityScore:
    """Assess video quality using VLM + technical metrics.

    Steps:
    1. Extract technical metrics via oprim.video_quality_metrics
    2. Sample N frames via ffmpeg
    3. Send frames + script to VLM for scoring

    Args:
        video_path: Path to video file.
        script: The script used to generate the video.
        vlm: VLM callable (prompt=str, media_paths=list[Path]) -> dict.
        sample_frames_count: Number of frames to extract for VLM.

    Returns:
        VideoQualityScore with multi-dimensional scores.

    Raises:
        VideoSelfAssessError: Video not found, extraction failed, or VLM error.

    Example:
        >>> score = await video_self_assess(video_path=Path("v.mp4"), script=s, vlm=vlm)
    """
    if not video_path.exists():
        raise VideoSelfAssessError(f"Video not found: {video_path}")

    if sample_frames_count < 1:
        raise VideoSelfAssessError("sample_frames_count must be >= 1")

    # Step 1: Technical metrics
    from oprim import VideoQualityError, video_quality_metrics

    try:
        metrics = await video_quality_metrics(video_path=video_path)
    except VideoQualityError as exc:
        raise VideoSelfAssessError(f"Metrics extraction failed: {exc}") from exc

    # Step 2: Extract frames
    frames = await _extract_frames(video_path, sample_frames_count, metrics.duration_s)

    # Step 3: VLM scoring
    prompt = (
        f"Score this video (0-100) on: script_score, visual_score, pacing_score. "
        f"Script title: {script.title}. Duration: {metrics.duration_s:.1f}s. "
        f"Resolution: {metrics.width}x{metrics.height}. "
        f'Return JSON: {{"script_score": float, "visual_score": float, '
        f'"pacing_score": float, "issues": [str], "suggestions": [str]}}'
    )

    try:
        result = vlm(prompt=prompt, media_paths=frames)
    except Exception as exc:
        raise VideoSelfAssessError(f"VLM call failed: {exc}") from exc

    content = result.get("content", "") if isinstance(result, dict) else str(result)

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise VideoSelfAssessError(f"VLM returned invalid JSON: {content[:200]}") from exc

    # Compute overall as weighted average
    s_score = float(data.get("script_score", 0))
    v_score = float(data.get("visual_score", 0))
    p_score = float(data.get("pacing_score", 0))
    overall = s_score * 0.4 + v_score * 0.35 + p_score * 0.25

    return VideoQualityScore(
        script_score=s_score,
        visual_score=v_score,
        pacing_score=p_score,
        overall_score=round(overall, 2),
        issues=data.get("issues", []),
        suggestions=data.get("suggestions", []),
    )


async def _extract_frames(video_path: Path, count: int, duration_s: float) -> list[Path]:
    """Extract evenly-spaced frames from video via ffmpeg."""
    tmpdir = Path(tempfile.mkdtemp(prefix="vsa_frames_"))
    interval = max(duration_s / (count + 1), 0.1)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"fps=1/{interval:.2f}",
        "-frames:v",
        str(count),
        str(tmpdir / "frame_%03d.png"),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    frames = sorted(tmpdir.glob("frame_*.png"))
    return frames[:count]
