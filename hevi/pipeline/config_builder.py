from pathlib import Path
from typing import Any

from omodul.agentic_longvideo_pipeline import LongVideoConfig

from hevi.audio import AudioProvider
from hevi.video import DURATION_ARCHETYPES, VideoProvider

__all__ = ["build_longvideo_config", "build_longvideo_config_with_prompt"]


_OMODUL_ARCHETYPE_MAP: dict[str, str] = {
    "short": "1-5min",
}

# Per-archetype overrides for LongVideoConfig fields not exposed in the hevi API.
# "short" disables shot retries to keep total Wan2GP runs to 2×N_shots instead of 6×N.
_ARCHETYPE_CONFIG_OVERRIDES: dict[str, dict[str, Any]] = {
    "short": {"max_shot_retries": 0},
}


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

    # omodul only accepts the four production archetypes; map hevi-only archetypes
    omodul_archetype = _OMODUL_ARCHETYPE_MAP.get(duration_archetype, duration_archetype)

    # Merge per-archetype config overrides (caller kwargs take precedence)
    archetype_overrides = _ARCHETYPE_CONFIG_OVERRIDES.get(duration_archetype, {})
    merged = {**archetype_overrides, **kwargs}

    return LongVideoConfig(
        topic=topic,
        duration_archetype=omodul_archetype,  # type: ignore[arg-type]
        video_provider=v_provider,
        audio_provider=a_provider,
        style=style,
        num_characters=num_characters,
        language=language,
        output_dir=output_dir or Path("output/hevi_v2"),
        fallback_video_provider=fb_v_provider,
        **merged,
    )


async def build_longvideo_config_with_prompt(
    *,
    topic: str,
    duration_archetype: str,
    video_provider: str | VideoProvider,
    audio_provider: str | AudioProvider,
    style_preset: str | None = None,
    prompt_style: str | None = None,
    prompt_lighting: str | None = None,
    prompt_camera: str | None = None,
    prompt_color_grade: str | None = None,
    **kwargs: Any,
) -> LongVideoConfig:
    """Build LongVideoConfig after running prompt engineering on the topic.

    Calls engineer_prompt_from_preset to apply visual-style injection and
    provider-specific adaptation before handing the topic to M8.

    Prompt engineering scope — hevi layer only:
    - Processes the *top-level* topic/style description supplied by the caller.
    - M8's internal shot-level prompt generation is not touched.
    """
    from hevi.prompt.prompt_pipeline import engineer_prompt_from_preset

    engineered_topic = await engineer_prompt_from_preset(
        raw_prompt=topic,
        target_provider=str(video_provider),
        preset_name=style_preset,
        style=prompt_style,
        lighting=prompt_lighting,
        camera=prompt_camera,
        color_grade=prompt_color_grade,
    )
    return build_longvideo_config(
        topic=engineered_topic,
        duration_archetype=duration_archetype,
        video_provider=video_provider,
        audio_provider=audio_provider,
        **kwargs,
    )
