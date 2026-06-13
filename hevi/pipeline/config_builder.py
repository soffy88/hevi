from pathlib import Path
from typing import Any

from omodul.agentic_longvideo_pipeline import LongVideoConfig

from hevi.audio import AudioProvider
from hevi.video import DURATION_ARCHETYPES, VideoProvider


def build_longvideo_config(
    *,
    topic: str,
    duration_archetype: str,
    video_provider: str | VideoProvider,
    audio_provider: str | AudioProvider,
    style: str = "cinematic",
    num_characters: int = 1,
    language: str = "zh",
    output_dir: Path | None = None,
    fallback_video_provider: str | VideoProvider | None = None,
    **kwargs: Any,
) -> LongVideoConfig:
    """Map hevi business parameters to omodul.LongVideoConfig."""

    if duration_archetype not in DURATION_ARCHETYPES:
        raise ValueError(f"Unknown duration archetype: {duration_archetype}")

    # Normalize providers
    v_provider = str(video_provider)
    a_provider = str(audio_provider)
    fb_v_provider = str(fallback_video_provider) if fallback_video_provider else None

    # Validate providers against enums if they are strings
    valid_video = [v.value for v in VideoProvider]
    if v_provider not in valid_video:
        raise ValueError(f"Invalid video provider: {v_provider}")

    valid_audio = [a.value for a in AudioProvider]
    if a_provider not in valid_audio:
        raise ValueError(f"Invalid audio provider: {a_provider}")

    return LongVideoConfig(
        topic=topic,
        duration_archetype=duration_archetype,  # type: ignore[arg-type]
        video_provider=v_provider,
        audio_provider=a_provider,
        style=style,
        num_characters=num_characters,
        language=language,
        output_dir=output_dir or Path("output/hevi_v2"),
        fallback_video_provider=fb_v_provider,
        **kwargs,
    )
