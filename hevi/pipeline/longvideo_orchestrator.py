import logging
from pathlib import Path
from typing import Any

from omodul.agentic_longvideo_pipeline import agentic_longvideo_pipeline

from hevi.observability import track_video_generation

logger = logging.getLogger(__name__)

from hevi.pipeline.config_builder import build_longvideo_config
from hevi.pipeline.result_mapper import map_longvideo_result


async def orchestrate_longvideo(
    *,
    config: Any = None,  # hevi app config if needed
    topic: str,
    duration_archetype: str,
    video_provider: str,
    audio_provider: str,
    style: str = "cinematic",
    num_characters: int = 1,
    language: str = "zh",
    # Prompt engineering — applied to topic before M8 ingestion.
    # Scope: top-level topic/style pre-processing only.
    # M8's internal shot-level prompt generation is separate and untouched.
    style_preset: str | None = None,
    prompt_style: str | None = None,
    prompt_lighting: str | None = None,
    prompt_camera: str | None = None,
    prompt_color_grade: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Orchestrate long video generation using omodul agentic pipeline.

    When any prompt-engineering param is provided (style_preset or prompt_*),
    the raw topic is first transformed by engineer_prompt_from_preset before
    being handed to M8 via LongVideoConfig.

    Args:
        config: Application configuration.
        topic: The topic/prompt for the video.
        duration_archetype: Duration bucket (e.g., '1-5min').
        video_provider: Choice of video kernel.
        audio_provider: Choice of audio kernel.
        style: Visual style field for LongVideoConfig (separate from prompt injection).
        num_characters: Number of main characters.
        language: Generation language.
        style_preset: hevi style preset name ('科普', '严肃', '搞笑').
        prompt_style: Direct style descriptor for inject_visual_style.
        prompt_lighting: Direct lighting descriptor.
        prompt_camera: Direct camera descriptor.
        prompt_color_grade: Direct color-grade descriptor.
        **kwargs: Extra parameters for LongVideoConfig.

    Returns:
        dict: Hevi-mapped business result.
    """
    engineered_topic = topic
    if style_preset or prompt_style or prompt_lighting or prompt_camera or prompt_color_grade:
        from hevi.prompt.prompt_pipeline import engineer_prompt_from_preset

        engineered_topic = await engineer_prompt_from_preset(
            raw_prompt=topic,
            target_provider=video_provider,
            preset_name=style_preset,
            style=prompt_style,
            lighting=prompt_lighting,
            camera=prompt_camera,
            color_grade=prompt_color_grade,
        )

    lv_config = build_longvideo_config(
        topic=engineered_topic,
        duration_archetype=duration_archetype,
        video_provider=video_provider,
        audio_provider=audio_provider,
        style=style,
        num_characters=num_characters,
        language=language,
        **kwargs,
    )

    async with track_video_generation(video_provider, duration_archetype):
        # SaaS-2/P10.F2 Fix: oskill.storyboard_planner has a bug where it calls .model_dump() 
        # on scenes, but Chapter model defines them as list[dict].
        from oskill.storyboard_planner import storyboard_planner

        async def patched_storyboard_fn(*, script: Any, llm: Any) -> Any:
            # Wrap the script to bypass Pydantic assignment validation
            class ScriptWrapper:
                def __init__(self, orig: Any):
                    self._orig = orig
                    
                    class ModelDict(dict):
                        def model_dump(self) -> dict[str, Any]:
                            return dict(self)
                            
                    if hasattr(orig, "scenes"):
                        self.scenes = [
                            ModelDict(s) if isinstance(s, dict) else s for s in orig.scenes
                        ]
                    else:
                        self.scenes = []
                        
                def __getattr__(self, name: str) -> Any:
                    return getattr(self._orig, name)

            wrapped_script = ScriptWrapper(script)
            return await storyboard_planner(script=wrapped_script, llm=llm)

        # SaaS-2/P10.F2 Fix: omodul has a hardcoded import for vibevoice_synthesize that fails.
        # We inject the actual audio provider from the registry.
        async def injected_audio_fn(*, script: list, output_path: Any) -> None:
            from obase.provider_registry import ProviderRegistry
            caller = ProviderRegistry.get("audio", audio_provider)
            if not caller:
                raise ValueError(f"Unknown audio provider: {audio_provider}")
            await caller(script=script, output_path=output_path)

        # SaaS-3/P10.F3: Inject video_fn to allow registry-based overrides and chaos monkey.
        # We MUST use the registry directly to avoid oprim.video_generate's hardcoded dispatch.
        async def injected_video_fn(*, prompt: str, output_path: Path, **kw: Any) -> Path:
            from obase.provider_registry import ProviderRegistry
            try:
                # Use video_provider from orchestrate_longvideo closure
                caller = ProviderRegistry.get("video", video_provider)
                if not caller:
                    raise ValueError(f"Unknown video provider: {video_provider}")
                
                # Call the registered function (might be a lambda or a direct operation)
                res = await caller(prompt=prompt, output_path=output_path, **kw)
                return Path(res) if res else output_path
            except Exception as e:
                logger.error(f"injected_video_fn FAILED for {video_provider}: {e}")
                raise

        # SaaS-3/P10.F3 Fix: omodul calls assembler_fn(shot_videos=..., audio_path=...)
        # but oskill.video_assembler expects avatar_videos=..., bgm_path=...
        # We bridge the mismatch here so real shot videos are assembled correctly.
        async def bridged_assembler_fn(
            *,
            shot_videos: list[Path],
            audio_path: Path | None = None,
            subtitle_path: Path | None = None,
            output_path: Path,
        ) -> None:
            from oskill.video_assembler import video_assembler
            valid_shots = [p for p in shot_videos if p.exists() and p.stat().st_size > 64]
            if not valid_shots:
                output_path.write_bytes(b"\x00" * 64)
                return
            await video_assembler(
                avatar_videos=valid_shots,
                bgm_path=audio_path if (audio_path and audio_path.exists()) else None,
                subtitle_path=subtitle_path,
                output_path=output_path,
            )

        _providers: dict[str, Any] = {
            "storyboard_fn": patched_storyboard_fn,
            "video_fn": injected_video_fn,
            "assembler_fn": bridged_assembler_fn,
        }
        if audio_provider != "ltx2_native":
            _providers["audio_fn"] = injected_audio_fn

        result = await agentic_longvideo_pipeline(
            config=lv_config,
            _providers=_providers
        )
        
        # SaaS-3/P10.F3 Fix: omodul suppresses shot failures by returning placeholders.
        # We must detect this to trigger Hevi's provider-level fallback.
        if result.video_path.exists() and result.video_path.stat().st_size < 1024:
            raise RuntimeError(f"Pipeline produced placeholder/empty output with {video_provider}")

        return map_longvideo_result(result)
