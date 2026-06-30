import json
import logging
import re
from pathlib import Path
from typing import Any

from omodul.agentic_longvideo_pipeline import agentic_longvideo_pipeline

from hevi.observability import track_video_generation
from hevi.pipeline.config_builder import build_longvideo_config
from hevi.pipeline.result_mapper import map_longvideo_result

logger = logging.getLogger(__name__)

_SHOT_INDEX_RE = re.compile(r"shot[_-]?(\d+)")


def _safe_size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return -1


def _order_and_dedup_shots(paths: list[Path]) -> list[Path]:
    """Order shots by numeric index and keep one variant per shot (RFC-001 P0-2).

    omodul (v1.28.0) names shots ``shot_XXXX_vN.mp4`` and the pipeline collects
    them with ``glob("*.mp4")`` — filesystem order, UNSORTED, keeping every
    retry/variant. Assembled as-is the video plays shots out of order and each
    shot appears 2×. Here we sort by shot index and, per index, keep the largest
    file (proxy for the most-complete / consistency-selected render). Paths with
    no parseable index are appended in name order, unchanged (no dedup).
    """
    indexed: dict[int, Path] = {}
    unparsed: list[Path] = []
    for p in paths:
        m = _SHOT_INDEX_RE.search(p.name)
        if not m:
            unparsed.append(p)
            continue
        idx = int(m.group(1))
        cur = indexed.get(idx)
        if cur is None or _safe_size(p) > _safe_size(cur):
            indexed[idx] = p
    ordered = [indexed[i] for i in sorted(indexed)]
    ordered.extend(sorted(unparsed, key=lambda p: p.name))
    return ordered

# Test-only hook: set this to a dict of provider overrides before calling run_task.
# orchestrate_longvideo reads this at call time (not import time), so task_service
# picks it up even though it imported the function reference earlier.
# Must be reset to None after the test.
_PROVIDERS_OVERRIDE: dict[str, Any] | None = None


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
    quality_profile: str = "standard",
    transition: str = "fade",
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

    # RFC-002 item 3: 解析目标分辨率/帧率(成片规格)。装配器据此重编码统一规格;
    # 本地 wan 按朝向夹取到 480p 级生成,装配器再缩放到目标。
    from hevi.video.quality_profile import get_quality_profile
    try:
        _qp = get_quality_profile(quality_profile)
    except ValueError:
        _qp = get_quality_profile("standard")
    _target_w, _target_h = _qp.resolution
    _target_fps = _qp.fps
    _is_local_video = "_local" in video_provider or video_provider in ("wan_local", "ltx2_local")

    def _wan_size_for_orientation() -> tuple[int, int]:
        if _target_w < _target_h:
            return (480, 832)
        if _target_w > _target_h:
            return (832, 480)
        return (576, 576)

    # For hevi-only "short" archetype, monkey-patch target duration so the LLM writes a
    # minimal single-shot script instead of a full 180-second production.
    _short_patch_active = False
    if duration_archetype == "short":
        import omodul.agentic_longvideo_pipeline as _omodul_m
        _orig_dur_fn = _omodul_m._duration_archetype_to_seconds
        _omodul_m._duration_archetype_to_seconds = lambda _: 10.0  # type: ignore[assignment]
        _short_patch_active = True

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
                    
                    class ModelDict(dict[str, Any]):
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
            return await storyboard_planner(script=wrapped_script, llm=llm)  # type: ignore[arg-type]

        # SaaS-2/P10.F2 Fix: omodul has a hardcoded import for vibevoice_synthesize that fails.
        # We inject the actual audio provider from the registry.
        async def injected_audio_fn(*, script: list[Any], output_path: Any) -> None:
            from obase.provider_registry import ProviderRegistry
            caller = ProviderRegistry.get().generic("audio", audio_provider)
            await caller(script=script, output_path=output_path)
            # RFC-002 item 2: 落盘旁白总时长 side-channel,供装配器做音频驱动时长
            # (使成片总长 == 旁白总长,杜绝 -shortest 截断/漂移)。
            try:
                from hevi.assembly.assembler import probe_duration
                ap = Path(output_path)
                total = await probe_duration(ap)
                if total > 0:
                    manifest = ap.with_suffix(ap.suffix + ".timing.json")
                    manifest.write_text(json.dumps({"total": total}))
            except Exception as me:  # 非致命: 装配器有回退
                logger.warning(f"audio timing manifest skipped: {me}")

        # SaaS-3/P10.F3: Inject video_fn to allow registry-based overrides and chaos monkey.
        # We MUST use the registry directly to avoid oprim.video_generate's hardcoded dispatch.
        async def injected_video_fn(
            *,
            prompt: str,
            output_path: Path,
            reference_image: Path | None = None,
            **kw: Any,
        ) -> Path:
            from obase.provider_registry import ProviderRegistry
            try:
                # Use video_provider from orchestrate_longvideo closure
                caller = ProviderRegistry.get().generic("video", video_provider)

                # RFC-001 P1-3: omodul's per-shot LLM prompt otherwise bypasses all
                # hevi prompt engineering. Re-apply provider adaptation + style here
                # so every shot gets the provider suffix and a consistent look.
                try:
                    from hevi.prompt.prompt_pipeline import engineer_prompt_from_preset
                    prompt = await engineer_prompt_from_preset(
                        raw_prompt=prompt,
                        target_provider=video_provider,
                        preset_name=style_preset,
                        style=prompt_style,
                        lighting=prompt_lighting,
                        camera=prompt_camera,
                        color_grade=prompt_color_grade,
                    )
                except Exception as pe:  # never fail a shot over prompt polishing
                    logger.warning(f"per-shot prompt engineering skipped: {pe}")

                # RFC-001 P0-1: omodul v1.33+ passes the selected reference frame.
                # When present, condition generation on it via i2v for shot-to-shot
                # continuity; when None, stay on t2v (omit the kwarg so providers
                # that don't accept it aren't handed reference_image=None).
                if reference_image is not None:
                    kw["reference_image"] = reference_image
                    kw.setdefault("mode", "i2v")

                # RFC-002 item 3: 本地 wan 按目标朝向夹取生成尺寸(480p 级)。
                if _is_local_video:
                    kw.setdefault("size", _wan_size_for_orientation())

                res = await caller(prompt=prompt, output_path=output_path, **kw)
                return Path(res) if res else output_path
            except Exception as e:
                logger.error(f"injected_video_fn FAILED for {video_provider}: {e}")
                raise

        # RFC-002 item 2/4/5/14: hevi 原生装配器为主路径 —— 音频驱动镜头时长 +
        # xfade 转场重编码 + 旁白 loudnorm。取代旧的硬切 + 整轨 -shortest 盲贴。
        async def bridged_assembler_fn(
            *,
            shot_videos: list[Path],
            audio_path: Path | None = None,
            subtitle_path: Path | None = None,
            output_path: Path,
        ) -> None:
            valid_shots = [p for p in shot_videos if p.exists() and p.stat().st_size > 64]
            # RFC-001 P0-2: omodul globs shots unsorted and keeps every variant —
            # order by shot index + keep one variant each before assembling.
            valid_shots = _order_and_dedup_shots(valid_shots)
            if not valid_shots:
                output_path.write_bytes(b"\x00" * 64)
                return

            from hevi.assembly.assembler import (
                ShotSegment,
                assemble_longvideo,
                load_timing_manifest,
                probe_duration,
            )

            has_audio = audio_path is not None and audio_path.exists()
            # RFC-002 item 2: 按各镜头原时长比例分配旁白总时长 → 成片总长 == 旁白总长。
            native = [await probe_duration(p) for p in valid_shots]
            total_audio = 0.0
            if has_audio:
                assert audio_path is not None
                manifest = load_timing_manifest(audio_path)
                total_audio = manifest[0] if manifest else await probe_duration(audio_path)
            segments: list[ShotSegment] = []
            sum_native = sum(d for d in native if d > 0) or float(len(valid_shots))
            for p, nat in zip(valid_shots, native, strict=False):
                if total_audio > 0:
                    share = (nat if nat > 0 else sum_native / len(valid_shots)) / sum_native
                    segments.append(ShotSegment(p, target_duration=max(0.8, total_audio * share)))
                else:
                    segments.append(ShotSegment(p, target_duration=None))

            try:
                await assemble_longvideo(
                    shots=segments,
                    output_path=output_path,
                    narration_audio=audio_path if has_audio else None,
                    subtitle_path=subtitle_path,
                    width=_target_w,
                    height=_target_h,
                    fps=_target_fps,
                    transition=transition,
                )
            except Exception as ae:
                # 装配失败兜底: 统一规格硬切(仍重编码,不用 -c:v copy 防花屏)。
                logger.error(f"hevi assembler failed, fallback to hard-cut: {ae}")
                await assemble_longvideo(
                    shots=[ShotSegment(p) for p in valid_shots],
                    output_path=output_path,
                    narration_audio=audio_path if has_audio else None,
                    width=_target_w, height=_target_h, fps=_target_fps,
                    transition="cut",
                )

        # omodul._default_llm() calls ProviderRegistry.get(category=...) which is
        # incompatible with obase's singleton .get(). Inject the registered LLM directly.
        # LLM is stored in _llms dict (via register_llm), not _generic — use .llm() not .generic().
        from obase.provider_registry import ProviderRegistry as _PR
        _llm = _PR.get().llm("default")

        _providers: dict[str, Any] = {
            "llm": _llm,
            "storyboard_fn": patched_storyboard_fn,
            "video_fn": injected_video_fn,
            "assembler_fn": bridged_assembler_fn,
        }
        if audio_provider != "ltx2_native":
            _providers["audio_fn"] = injected_audio_fn

        # Test-only: merge overrides injected via _PROVIDERS_OVERRIDE module var.
        import hevi.pipeline.longvideo_orchestrator as _self
        if _self._PROVIDERS_OVERRIDE:
            _providers.update(_self._PROVIDERS_OVERRIDE)

        try:
            result = await agentic_longvideo_pipeline(
                config=lv_config,
                _providers=_providers
            )
        finally:
            if _short_patch_active:
                _omodul_m._duration_archetype_to_seconds = _orig_dur_fn

        # SaaS-3/P10.F3 Fix: omodul suppresses shot failures by returning placeholders.
        # We must detect this to trigger Hevi's provider-level fallback.
        if result.video_path.exists() and result.video_path.stat().st_size < 1024:
            raise RuntimeError(f"Pipeline produced placeholder/empty output with {video_provider}")

        return map_longvideo_result(result)
