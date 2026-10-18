"""oskill.video_assembler — Assemble final video from parts.

Example:
    >>> from oskill.video_assembler import video_assembler
    >>> path = await video_assembler(avatar_videos=[...], output_path=Path("final.mp4"))

Raises:
    VideoAssemblerError: Assembly failed.
"""

from __future__ import annotations

from pathlib import Path


class VideoAssemblerError(Exception):
    """Video assembly failed."""


async def video_assembler(
    *,
    avatar_videos: list[Path],
    bgm_path: Path | None,
    subtitle_path: Path | None,
    output_path: Path,
) -> Path:
    """Assemble final video: concat shots + BGM + subtitle burn.

    Args:
        avatar_videos: List of per-shot mp4 files.
        bgm_path: Optional background music file.
        subtitle_path: Optional subtitle file to burn.
        output_path: Final output video path.

    Returns:
        The output_path on success.

    Raises:
        VideoAssemblerError: On empty inputs or assembly failure.

    Example:
        >>> path = await video_assembler(avatar_videos=[...], bgm_path=None, ...)
    """
    if not avatar_videos:
        raise VideoAssemblerError("avatar_videos must not be empty")

    for v in avatar_videos:
        if not v.exists():
            raise VideoAssemblerError(f"Video file not found: {v}")

    from oprim.video_concat import video_concat

    # Step 1: Concat all shot videos
    if len(avatar_videos) == 1:
        concat_path = avatar_videos[0]
    else:
        concat_path = output_path.parent / f"{output_path.stem}_concat.mp4"
        await video_concat(inputs=avatar_videos, output_path=concat_path)

    current = concat_path

    # Step 2: Mix BGM if provided
    if bgm_path and bgm_path.exists():
        from oprim import audio_mix

        mixed_audio = output_path.parent / f"{output_path.stem}_bgm.wav"
        await audio_mix(inputs=[current, bgm_path], weights=[1.0, 0.3], output_path=mixed_audio)

        from oprim import audio_video_merge

        merged = output_path.parent / f"{output_path.stem}_merged.mp4"
        await audio_video_merge(video_path=current, audio_path=mixed_audio, output_path=merged)
        current = merged

    # Step 3: Burn subtitles if provided
    if subtitle_path and subtitle_path.exists():
        from oprim import subtitle_burn

        await subtitle_burn(video_path=current, srt_paths=[subtitle_path], output_path=output_path)
    elif current != output_path:
        import shutil

        shutil.copy2(current, output_path)

    if not output_path.exists():
        raise VideoAssemblerError(f"Assembly did not produce output: {output_path}")

    return output_path
