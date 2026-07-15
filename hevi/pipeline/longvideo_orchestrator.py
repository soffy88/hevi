import asyncio
import contextlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from omodul.agentic_longvideo_pipeline import agentic_longvideo_pipeline

from hevi.observability import track_video_generation
from hevi.pipeline.config_builder import build_longvideo_config
from hevi.pipeline.result_mapper import map_longvideo_result

logger = logging.getLogger(__name__)

_SHOT_INDEX_RE = re.compile(r"shot[_-]?(\d+)")
# 舞台提示/动作说明括号(中英文),如"（一把拽过胳膊）"——是给分镜看的动作描述,
# 不是要念出来或打进字幕的台词,配音/字幕两处都剥掉。
_STAGE_DIR_RE = re.compile(r"[（(][^）)]*[）)]")


def _strip_stage_directions(text: str) -> str:
    return _STAGE_DIR_RE.sub("", text or "").strip()


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
    mood: str | None = None,  # 情绪基调:独立于 20 个 style_preset 的额外视觉维度
    genre: str | None = None,  # 题材类型(剧情/科普/广告/vlog…):影响内容而非画面,注入 topic
    narrative_hook: str | None = None,  # 叙事钩子:开场 3 秒抓手,注入 topic(LLM 指令而非硬切)
    scene_notes: str | None = None,  # 场景设定(地点/室内外/时间):注入 topic(全片级,非逐镜)
    props: str | None = None,  # 关键道具/陈设:注入 topic
    characters: str | None = None,  # 角色名+人设roster文本(由多角色绑定解析而来):注入 topic
    character_voices: dict[str, str] | None = None,  # {"speaker_0": voice_ref_path, ...} 尽力而为
    # 的角色→音色映射:script_writer 提示 LLM 用 speaker_0/speaker_1... 做对白说话人标签,
    # 但 LLM 输出是自由文本、不保证严格对应 —— 匹配上就换音色克隆,没匹配上就走默认音色,
    # 不报错。仅 audio_provider=vibevoice 生效(voice_ref 零样本声音克隆)。
    extra_negative: str | None = None,  # 角色专属负向提示(如"避免多指"),并入每镜负向
    quality_profile: str = "standard",
    aspect_ratio: str = "9:16",  # 画幅:9:16 竖 / 16:9 横 / 1:1 方(解锁 portrait 锁死)
    bgm: str | None = None,  # 背景音乐:情绪名(→assets/audio/bgm/<mood>/)或文件路径;装配器压于旁白下
    sfx: str | None = None,  # 音效名(→assets/audio/sfx/,前缀匹配)或文件路径;混入成片(不 duck)
    voice_rate: str | None = None,  # 旁白语速,edge_tts 格式如 "+15%"/"-20%";仅 edge_tts 生效
    voice_pitch: str | None = None,  # 旁白音高,edge_tts 格式如 "+2Hz";仅 edge_tts 生效
    voice_name: str | None = None,  # 旁白音色(edge_tts 神经语音 ID),覆盖语言自动选音色
    # SPEC-002 B1(主线情绪配音,opt-in——涉及一次额外 LLM 调用,默认关不改变现有
    # 行为/成本):开启后台词批量推断逐行情绪,驱动 edge_tts 逐行 rate/pitch,跟
    # tongjian 已验证的效果对齐。仅 audio_provider=edge_tts 生效(vibevoice 无
    # rate/pitch 概念)。见 injected_audio_fn 里的 emotion_aware_voiceover 分支。
    emotion_aware_voiceover: bool = False,
    subtitle_style: str = "default",  # 字幕烧录样式:default/bold_yellow/large_white/compact
    bilingual_language: str | None = None,  # 双语字幕:目标语种(如 "en"),与原字幕逐行合并
    intro_clip: str | None = None,  # 片头视频文件路径,装配前拼接
    outro_clip: str | None = None,  # 片尾视频文件路径,装配后拼接
    transition: str = "fade",
    # route v2(设计 §3 L0):逐镜头选 provider。开启后按每个镜头 prompt 判质量需求
    # (主角特写→云高质量 / 空镜 B-roll→免费本地 wan),而非全片一个 provider。默认关,
    # 不改既有行为。
    per_shot_routing: bool = False,
    avatar_portrait: str | None = None,  # RFC-002 item 11: 数字人讲解肖像图路径
    # SaaS-4:逐阶段进度回调 async (stage:str, pct:float, completed_shots=None,
    # total_shots=None)。必须为显式参数,否则会落入 **kwargs → LongVideoConfig 报错。
    progress_cb: Any = None,
    # 角色库(2D 参考锁定):选定角色的参考图路径。设置后,**每个镜头**都以它做 i2v
    # 参考图,锁定角色身份 → 视频里始终是同一个人(治"驴头不对马嘴")。为显式参数。
    character_reference: str | None = None,
    # SPEC-002 B2:风格参考图(不是身份锁脸)。见上面 engineered_topic 前的 VLM 拆解
    # 逻辑(全 provider 通用,派生文本字段)+ injected_video_fn 里 happyhorse_1_1_maas_lock
    # 专属的真实图片条件化(仅该 provider,更强但覆盖更窄)。为显式参数。
    style_reference_image: str | None = None,
    # SPEC-002 B3(主线欠账:每镜头首尾两张条件图):{shot_idx: {"first_frame": path,
    # "last_frame": path, "duration_s": 可选}}。命中的镜头整个绕开单图 i2v,走首尾帧
    # 生视频(见 injected_video_fn 里的 shot_keyframes 路由,alibaba_maas_keyframe_lock_generate)。
    # 纯 hevi 侧字典,不触 oskill 的 ShotPlan schema。未命中的镜头零影响。为显式参数。
    shot_keyframes: dict[int, dict[str, str]] | None = None,
    # SPEC-003 主线导演流水线:①-④已在 director_pipeline.py 走完人审核锁定的 ShotList
    # (dict 形式,JSON 可序列化,见 hevi/director/pipeline_schemas.py::ShotList)。存在时,
    # oskill 自己的 script_writer/storyboard_planner/shot_generator 整段跳过,直接用锁定
    # 内容——见 patched_storyboard_fn 之后的 _locked_script_fn/_locked_storyboard_fn 与
    # _counting_shot_gen_fn 里的 locked_shot_list 分支。None(默认)= 旧路径,零回归。
    locked_shot_list: dict[str, Any] | None = None,
    # 配合 locked_shot_list:{0-based 镜头序号: [该镜头出场角色的参考图文件路径,...]}。
    # 命中的镜头绕开全片统一的 character_reference,改用该镜头自己的角色参考图(2+ 张走
    # qwen-image-edit 多图合成,复用 SPEC-002 B2 已验证的同一原语)。由调用方
    # (director_pipeline.py 的 produce)预先把 DesignList 锁定的 subject_id 解析成参考图
    # 路径——orchestrator 侧不做数据库查询,只处理文件路径,跟 character_reference 现有
    # 处理方式保持一致。
    shot_character_refs: dict[int, list[str]] | None = None,
    # C3 verdict→定向返工:仅重生成这些镜头(shot_hints[idx] 并入 prompt),其余复用既有产物。
    # None/空 = 正常整片生成。需该 task 已跑过一次(output_dir 有 per-shot 边车)。
    regenerate_shot_ids: list[int] | None = None,
    shot_hints: dict[int, str] | None = None,
    # shot_verdict 版本快照(HEVI 路线图 Phase1):调用方(task_service)在跑之前解析出
    # 当前 subject/stylepack 的 id+version,这里只透传给 map_longvideo_result 做快照写入,
    # 不参与生成本身——必须为显式参数,否则会落入 **kwargs → LongVideoConfig 报错。
    subject_id: str | None = None,
    subject_version: int | None = None,
    style_pack_id: str | None = None,
    style_pack_version: int | None = None,
    # 非完美事件库(HEVI 路线图 Phase3 #38):verité/真实感类预设专用,opt-in(默认关,
    # 不改变现有行为)。开启后逐镜头插一个不重复的非完美感描述,全片(这一次调用)
    # 范围内不重复;库存量有限,用完就不再插,不强行重复凑数。
    imperfection_events: bool = False,
    # SPEC-001 §5:跨集角色关系一致性守护(Tier0)。short 剧通道的 dispatch_season 把这三样
    # 塞进 config_json(hevi/season_planner/dispatch.py)——task_service 侧拿不到 StoryGraph
    # 对象,只能这样把它需要的一小份数据带过来。为显式参数,否则会落入 **kwargs →
    # LongVideoConfig 报错(同上面 character_reference 等参数的既有惯例)。
    story_relationships: list[dict[str, Any]] | None = None,
    story_characters: list[dict[str, Any]] | None = None,
    episode_plan: dict[str, Any] | None = None,
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
    # SPEC-002 B3:config_json 走 JSONB 落库/回读(task_service.py 的 **task["config_json"]
    # 惯例),JSON 对象的 key 只能是字符串——dict[int,...] 在 DB 往返后会变成
    # dict[str,...]。归一化成 int key,injected_video_fn 才能用 int 型 _idx 查到。
    # 直接 Python 调用传 int key(如测试里那样)也兼容,这行是幂等的。
    if shot_keyframes:
        shot_keyframes = {int(k): v for k, v in shot_keyframes.items()}
    # 同上,SPEC-003 的 shot_character_refs 也是走 config_json JSONB 落库/回读的
    # int-keyed dict,同样需要归一化。
    if shot_character_refs:
        shot_character_refs = {int(k): v for k, v in shot_character_refs.items()}

    async def _report(
        stage: str, pct: float, completed: int | None = None, total: int | None = None
    ) -> None:
        """安全上报进度;进度回写绝不可影响生成主链路。"""
        if progress_cb is None:
            return
        try:
            await progress_cb(stage, pct, completed, total)
        except Exception as _pe:
            logger.debug("progress_cb failed: %s", _pe)

    await _report("准备生成", 3.0)

    # 立意/场景/角色层:题材/钩子/场景/道具/角色 roster 是"内容该拍什么"而非"画面怎么调",
    # 作为 LLM 指令前缀并入 topic(同 storyboard/script_writer 已有的 subjects 注入模式)——
    # 影响整片叙事走向,是软指令而非硬性保证(与其它 19 个 style_preset 同性质)。
    _directives: list[str] = []
    if narrative_hook:
        _directives.append(f"开场 3 秒需以强钩子抓住观众:{narrative_hook}")
    if genre:
        _directives.append(f"题材类型:{genre}")
    if characters:
        _directives.append(f"角色:{characters}")
    if scene_notes:
        _directives.append(f"场景设定:{scene_notes}")
    if props:
        _directives.append(f"关键道具/陈设:{props}")
    if _directives:
        topic = "。".join(_directives) + "。" + topic

    # SPEC-002 B2("额外风格参考图条件化"主线欠账):给一张风格参考图,自动推导
    # style/lighting/camera/color_grade(本地 VLM 拆解,复用 tongjian 侧已验证的
    # draft_style_from_reference,见 hevi/style/draft_from_reference.py——不重造)。
    # 只在用户没手填任一对应文本字段时才用推导值补空,用户显式填的文本字段永远优先,
    # 不会被图片派生值覆盖。best-effort:VLM 不可用/拆解失败不阻断生成,只是拿不到
    # 风格草稿(与 identity_embedding 同一降级哲学)。这条覆盖全部 7 个主线 provider
    # (文本字段走既有的 engineer_prompt_from_preset,provider 无关);另见下面
    # injected_video_fn 里 happyhorse_1_1_maas_lock 专属的真实图片条件化(覆盖更小,
    # 但更强)。
    if style_reference_image and not any(
        [prompt_style, prompt_lighting, prompt_camera, prompt_color_grade]
    ):
        try:
            _sref = Path(style_reference_image)
            if _sref.exists():
                from hevi.providers.local_qwen_vl_adapter import (
                    local_qwen_vl_adapter,
                    vl_model_available,
                )
                from hevi.style.draft_from_reference import draft_style_from_reference

                if vl_model_available():
                    _draft = await draft_style_from_reference(_sref, vlm=local_qwen_vl_adapter)
                    prompt_style = _draft.get("style") or prompt_style
                    prompt_lighting = _draft.get("lighting") or prompt_lighting
                    prompt_camera = _draft.get("camera") or prompt_camera
                    prompt_color_grade = _draft.get("color_grade") or prompt_color_grade
                else:
                    logger.info("style_reference_image 提供但本地 VL 模型不可用,跳过风格拆解")
        except Exception as _se:
            logger.warning("style_reference_image 风格拆解失败,跳过: %s", _se)

    engineered_topic = topic
    if (
        style_preset
        or prompt_style
        or prompt_lighting
        or prompt_camera
        or prompt_color_grade
        or mood
    ):
        from hevi.prompt.prompt_pipeline import engineer_prompt_from_preset

        engineered_topic = await engineer_prompt_from_preset(
            raw_prompt=topic,
            target_provider=video_provider,
            preset_name=style_preset,
            style=prompt_style,
            lighting=prompt_lighting,
            camera=prompt_camera,
            color_grade=prompt_color_grade,
            mood=mood,
        )

    # RFC-002 item 3: 解析目标分辨率/帧率(成片规格)。装配器据此重编码统一规格;
    # 本地 wan 按朝向夹取到 480p 级生成,装配器再缩放到目标。
    from hevi.video.quality_profile import get_quality_profile

    try:
        _qp = get_quality_profile(quality_profile)
    except ValueError:
        _qp = get_quality_profile("standard")
    # 画幅按 aspect_ratio 重排朝向(档位定清晰度,画幅定横竖)。
    from hevi.video.quality_profile import resolve_resolution

    _target_w, _target_h = resolve_resolution(quality_profile, aspect_ratio)
    _target_fps = _qp.fps

    # BGM/音效:情绪名或文件名/路径 → 具体文件(装配器已内建旁白 ducking 混音)。无素材则
    # None,静默跳过,不报错(素材库允许空)。
    from hevi.audio.bgm_library import BGMLibrary

    _bgm_lib = BGMLibrary()
    _bgm_path = None
    if bgm:
        try:
            _bgm_path = _bgm_lib.select_bgm(bgm)
            if _bgm_path is None:
                logger.info("bgm mood %r 无素材,跳过配乐", bgm)
        except Exception as _be:
            logger.warning("bgm 解析失败,跳过: %s", _be)
    _sfx_path = None
    if sfx:
        try:
            direct = Path(sfx)
            _sfx_path = direct if direct.is_file() else _bgm_lib.get_sfx(sfx)
            if _sfx_path is None:
                logger.info("sfx %r 无素材,跳过音效", sfx)
        except Exception as _se:
            logger.warning("sfx 解析失败,跳过: %s", _se)

    # 片头/片尾:文件路径存在则用于装配前后拼接(不存在则静默跳过)。
    _intro_path = Path(intro_clip) if intro_clip and Path(intro_clip).is_file() else None
    _outro_path = Path(outro_clip) if outro_clip and Path(outro_clip).is_file() else None

    _is_local_video = "_local" in video_provider or video_provider in ("wan_local", "ltx2_local")

    # RFC/SaaS-4 item 5(提速):omodul 每镜头硬编码生成 2 变体(v0/v1)再选优,
    # 且镜头数由 LLM storyboard 决定 —— 非 short 档(如 1-5min 常规划 14+ 镜头)因此
    # 每镜头 2× 云调用、顺序执行,曾出现 1-5min 视频跑 60+ 分钟。
    # 决策(质量为王 vs 功能至上的平衡):高清/超清档保留 2 变体保画质;short 与标清
    # 档降为单变体(v1 复用 v0),云调用减半。short 另叠加单镜头。
    _single_variant = duration_archetype == "short" or quality_profile == "standard"

    # 镜头总数(由 _counting_shot_gen_fn 预统计,供逐镜头进度百分比 + total_shots)。
    _shot_stats: dict[str, int] = {"total": 0}

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

            await _report("规划分镜脚本", 15.0)
            wrapped_script = ScriptWrapper(script)
            return await storyboard_planner(script=wrapped_script, llm=llm)  # type: ignore[arg-type]

        # SPEC-003(主线导演流水线):locked_shot_list 存在时,①-④级已经在
        # hevi/api/routers/director_pipeline.py 走完人审核锁定,不需要 oskill 自己的
        # script_writer/storyboard_planner/shot_generator 再规划一遍(省钱,且锁定内容
        # 才是唯一真相源)。三个规划期钩子都替换成"直接转换锁定数据"的版本:
        #   script_fn      → 台词行(带 speaker)转 SpeakerLine,喂进全片配音轨(音频侧
        #                     真正的对白来源是 chapter.dialogues,不是 ShotPlan.tts_text,
        #                     见 SPEC-003 plan 里对 omodul 源码的实测)。
        #                     不改 character_voices 的既有消费逻辑,只是这里 speaker_id
        #                     现在真的按角色区分,不再全部落到同一个默认说话人。
        #   storyboard_fn  → 返回一个占位 Storyboard,不做真实 LLM 规划调用(下面
        #                     shot_gen_fn 分支根本不读它的内容)。
        #   shot_gen_fn    → 见 _counting_shot_gen_fn 内的 locked_shot_list 分支。
        if locked_shot_list is not None:
            from oskill._schemas import Chapter, ChapterScript, SpeakerLine, Storyboard

            async def _locked_script_fn(**_kw: Any) -> Any:
                # 2026-07-14 用户要求:彻底不要旁白。只保留有说话人的对白行
                # (character_name 非空);旁白行(character_name 为空)完全丢弃,不进配音轨。
                # 台词里的舞台提示括号也剥掉(不是要念的话)。speaker_id 用角色名,命中
                # produce 传入的 character_voices 就换成该角色专属音色(见 injected_audio_fn)。
                dialogues = []
                for shot in locked_shot_list.get("shots", []):
                    for line in shot.get("dialogue_lines", []):
                        speaker = (line.get("character_name") or "").strip()
                        if not speaker:
                            continue
                        text = _strip_stage_directions(line.get("text", ""))
                        if text:
                            dialogues.append(SpeakerLine(speaker_id=speaker, text=text))
                chapter = Chapter(chapter_id="locked", title="", scenes=[], dialogues=dialogues)
                return ChapterScript(
                    chapters=[chapter],
                    total_duration_s=sum(
                        float(s.get("duration_s") or 0) for s in locked_shot_list.get("shots", [])
                    ),
                    characters=[],
                )

            async def _locked_storyboard_fn(**_kw: Any) -> Any:
                return Storyboard(shots=[])

            _providers_script_fn = _locked_script_fn
            _providers_storyboard_fn = _locked_storyboard_fn
        else:
            _providers_script_fn = None
            _providers_storyboard_fn = patched_storyboard_fn

        # SaaS-2/P10.F2 Fix: omodul has a hardcoded import for vibevoice_synthesize that fails.
        # We inject the actual audio provider from the registry.
        async def injected_audio_fn(*, script: list[Any], output_path: Any) -> None:
            from obase.provider_registry import ProviderRegistry

            # 音色/语速/音高覆盖:仅 edge_tts 支持(vibevoice 无 rate/pitch 参数),且仅当
            # 调用方显式给了其中之一才走 hevi 自有实现;否则用回 registry 默认,零行为变化。
            # SPEC-002 B1(主线情绪配音):emotion_aware_voiceover 开启时也走这条路——
            # 逐行情绪需要 synthesize_with_voice_control 读每行 .emotion,registry 默认
            # provider(edge_tts_synthesize_smart)只接受整批一个 emotion,做不到逐行。
            # character_voices(2026-07-14):edge_tts 也要按角色换音色。此前只有 vibevoice
            # 分支消费 character_voices,edge_tts 多角色对白全是一个默认声音(用户实测抱怨
            # "对话也像旁白")。有 character_voices 就走 synthesize_with_voice_control,逐行
            # 按说话人挑音色(见下面 _script 构造 + edge_tts_custom.py 的每行 .voice 支持)。
            _voice_ctrl = audio_provider == "edge_tts" and (
                voice_rate
                or voice_pitch
                or voice_name
                or emotion_aware_voiceover
                or character_voices
            )
            if _voice_ctrl:
                from hevi.audio.edge_tts_custom import synthesize_with_voice_control

                async def caller(*, config: dict[str, Any], script: Any, output_path: Any) -> Any:
                    return await synthesize_with_voice_control(
                        config=config,
                        script=script,
                        output_path=output_path,
                        rate=voice_rate,
                        pitch=voice_pitch,
                        voice=voice_name,
                    )
            else:
                caller = ProviderRegistry.get().generic("audio", audio_provider)
            await _report("合成配音旁白", 82.0)

            # 角色专属音色(仅 vibevoice):script_writer 提示 LLM 用 speaker_0/speaker_1...
            # 做对白说话人标签(尽力而为,非严格保证)。speaker_id 命中 character_voices
            # 就换成该角色的声音参考(零样本克隆);没命中保留原样,走该说话人默认音色。
            _script = script
            if audio_provider == "vibevoice" and character_voices:
                from types import SimpleNamespace

                _script = [
                    SimpleNamespace(
                        speaker_id=getattr(line, "speaker_id", "host"),
                        text=getattr(line, "text", str(line)),
                        voice_ref=character_voices.get(
                            getattr(line, "speaker_id", ""), getattr(line, "voice_ref", None)
                        ),
                    )
                    for line in script
                ]
            elif (
                audio_provider == "edge_tts"
                and (emotion_aware_voiceover or character_voices)
                and script
            ):
                # SPEC-002 B1(情绪)+ 2026-07-14(角色音色):edge_tts 逐行包进 hevi 自己的
                # SimpleNamespace。.voice = 该行说话人在 character_voices 里分到的音色键
                # (synthesize_with_voice_control 逐行读 .voice,见 edge_tts_custom.py);
                # emotion 仅在 emotion_aware_voiceover 开启时补(全片一次批量分类)。
                # best-effort:任一推断失败 → 退化为默认音色/中性语气,不影响出片。
                from types import SimpleNamespace

                _emotions: list[str] = [""] * len(script)
                if emotion_aware_voiceover:
                    from hevi.prompt.emotion_inference import infer_line_emotions

                    try:
                        _texts = [getattr(line, "text", str(line)) for line in script]
                        _emotions = await infer_line_emotions(_texts)
                    except Exception as ee:
                        logger.warning("emotion_aware_voiceover: 情绪推断失败,跳过: %s", ee)
                        _emotions = [""] * len(script)
                _cv = character_voices or {}
                _script = [
                    SimpleNamespace(
                        speaker_id=getattr(line, "speaker_id", "host"),
                        text=getattr(line, "text", str(line)),
                        voice=_cv.get(getattr(line, "speaker_id", "")),
                        voice_ref=getattr(line, "voice_ref", None),
                        emotion=_emotions[i] if i < len(_emotions) else "",
                    )
                    for i, line in enumerate(script)
                ]

            # SaaS-4 Fix: omodul 对 audio_fn 无容错(pipeline.py:180 直接 await,
            # 抛异常即整条链崩)。旁白合成属"增强"而非"必需" —— TTS 不可用(如
            # vibevoice 模型缺失/显存不足)时降级为纯视频出片:不落 audio.wav,
            # bridged_assembler_fn 的 has_audio 检测到文件缺失即走无旁白装配路径。
            # 保证"点生成必出片",而非因配音失败整任务失败。
            try:
                # config 透传 language,edge_tts 据此选音色(vibevoice 忽略多余键)。
                await caller(
                    config={"language": language},
                    script=_script,
                    output_path=output_path,
                )
            except Exception as ae:
                logger.error(
                    f"audio synthesis failed ({audio_provider}); degrading to "
                    f"video-only (no narration): {ae}"
                )
                # 清掉可能的半成品,确保 has_audio == False。
                with contextlib.suppress(OSError):
                    Path(output_path).unlink(missing_ok=True)
                return
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

            outp = Path(output_path)
            # SPEC-002 B3(每镜头首尾帧):镜头索引改成每次调用(v0/v1 都要)都算,不再
            # 只在 v0 分支里算——下面的 shot_keyframes 路由两个变体都要能查到同一个 idx。
            _m = _SHOT_INDEX_RE.search(outp.name)
            _idx = int(_m.group(1)) if _m else 0

            # item 5(单变体提速):omodul 对同一镜头以 _v0/_v1 连调本函数两次。
            # 单变体模式下,_v1 直接复用已生成的 _v0(同 prompt/同 ref),省一半
            # 云调用;consistency_fn 仍能在等价候选上正常选优。
            if _single_variant and outp.name.endswith("_v1.mp4"):
                v0 = outp.with_name(outp.name[: -len("_v1.mp4")] + "_v0.mp4")
                if v0.exists() and v0.stat().st_size > 1024:
                    import shutil as _sh

                    _sh.copy2(v0, outp)
                    logger.info("single-variant: reuse v0 → %s (skip 2nd gen)", outp.name)
                    return outp

            # 逐镜头进度:仅在首个变体(v0)上报一次,避免 v1 重复计数。
            # 总镜头数由 _counting_shot_gen_fn 预先统计(_shot_stats["total"]),据此
            # 给出真实的 "第 N/总 个镜头" 文案 + 在 25–75% 区间按 N/总 线性推进,
            # 修复此前从第 7 镜头起恒显 75%("看着卡住")的问题。
            if outp.name.endswith("_v0.mp4"):
                _total = _shot_stats.get("total", 0)
                if _total > 0:
                    _label = f"生成第 {_idx + 1}/{_total} 个镜头"
                    _pct = 25.0 + 50.0 * (_idx / _total)
                else:
                    _label = f"生成第 {_idx + 1} 个镜头"
                    _pct = min(75.0, 25.0 + _idx * 8.0)
                await _report(_label, _pct, completed=_idx, total=_total or None)

            # route v2:逐镜头选 provider(开启时)。i2v/t2v 由是否有参考图判定;质量需求
            # 从镜头 prompt 启发式分类。失败/未开 → 回退全片 video_provider。在 checkpoint
            # 之前算好,使 marker 比对与 provider 后缀都用逐镜头结果。
            _prov = video_provider
            if per_shot_routing:
                try:
                    from hevi.cost.shot_router import route_shot_provider

                    _prov = await route_shot_provider(
                        prompt=prompt,
                        duration_archetype=duration_archetype,
                        audio_provider=audio_provider,
                        mode="i2v" if reference_image else "t2v",
                    )
                    if _prov != video_provider:
                        logger.info(
                            "route v2: shot %s → %s (task provider %s)",
                            outp.name,
                            _prov,
                            video_provider,
                        )
                except Exception as re:
                    logger.warning("route v2 failed, using task provider: %s", re)
                    _prov = video_provider

            # RFC-002 item 7: 镜头级 checkpoint。已成功生成且 marker 记录的 provider
            # 与当前一致 → 跳过重生成(resume 提速);provider 不同(fallback/route v2)→
            # 重生成,不复用旧 provider 的废片。marker 落盘在镜头文件旁。
            marker = outp.with_suffix(outp.suffix + ".done.json")
            if outp.exists() and outp.stat().st_size > 1024 and marker.exists():
                try:
                    if json.loads(marker.read_text()).get("provider") == _prov:
                        logger.info("shot checkpoint hit, skip regen: %s", outp.name)
                        return outp
                except json.JSONDecodeError, OSError:
                    pass

            # SPEC-002 B3(主线欠账:每镜头首尾两张条件图):shot_keyframes 是 hevi 侧的
            # 纯字典(不触 oskill 的 ShotPlan schema),按上面已经算出的 _idx 查——命中
            # 且首尾帧文件都存在时,这一个镜头整个绕开正常的 "video" category caller,
            # 直接走 image_to_video 类别的首尾帧生视频(见 alibaba_maas_keyframe_lock_generate,
            # SPEC-002 B3/首尾帧关键帧 provider)。查不到/文件缺失/生成失败 → 原样落回
            # 正常单图 i2v 生成,不阻断整个镜头(best-effort,同 identity_embedding 的
            # 降级哲学)。
            _kf = (shot_keyframes or {}).get(_idx)
            if _kf and _kf.get("first_frame") and _kf.get("last_frame"):
                _ff, _lf = Path(_kf["first_frame"]), Path(_kf["last_frame"])
                if _ff.exists() and _lf.exists():
                    try:
                        from hevi.video.alibaba_maas_service import (
                            alibaba_maas_keyframe_lock_generate,
                        )

                        _kf_timeout = float(os.getenv("HEVI_SHOT_TIMEOUT_S", "240"))
                        res = await asyncio.wait_for(
                            alibaba_maas_keyframe_lock_generate(
                                first_frame=_ff,
                                last_frame=_lf,
                                duration_s=float(_kf.get("duration_s") or 5.0),
                                output_path=output_path,
                                timeout_s=_kf_timeout,
                            ),
                            timeout=_kf_timeout,
                        )
                        final = Path(res) if res else output_path
                        if final.exists() and final.stat().st_size > 1024:
                            with contextlib.suppress(OSError):
                                final.with_suffix(final.suffix + ".done.json").write_text(
                                    json.dumps({"provider": "wan22_kf2v_maas"})
                                )
                            return final
                    except Exception as kfe:
                        logger.warning(
                            "shot %s 首尾帧生视频失败,回退正常单图 i2v: %s", outp.name, kfe
                        )

            try:
                caller = ProviderRegistry.get().generic("video", _prov)

                # 角色库锁定优先:选定角色时,**每个镜头**都以角色参考图做 i2v →
                # 视频里始终是同一个人(治跨镜头身份漂移)。角色参考覆盖 omodul 的逐镜头
                # "上一帧"参考。仅当参考图文件存在时启用,避免把不存在的路径传给 provider。
                # 提到 prompt 工程之前算,因为下面的身份锁定句注入需要知道是否锁了角色。
                _char_ref = None
                if character_reference:
                    _cr = Path(character_reference)
                    if _cr.exists():
                        _char_ref = _cr

                # SPEC-003:这一镜若在 shot_character_refs 里有自己的角色参考图,覆盖掉
                # 上面全片统一的 _char_ref——根治"人物/场景乱跳"(每镜头锁自己该出场的
                # 角色,而不是全片焊死一张参考图)。1 张直接用;2+ 张走跟 SPEC-002 B2
                # 同一个 qwen-image-edit 多图合成原语,按镜头缓存,避免同一镜的 v0/v1
                # 两次调用重复合成。查不到/文件不存在/合成失败 → 静默回退上面的全片参考图,
                # 不阻断这一镜。
                _shot_refs = (shot_character_refs or {}).get(_idx)
                if _shot_refs:
                    _existing_refs = [p for p in _shot_refs if Path(p).exists()]
                    if len(_existing_refs) == 1:
                        _char_ref = Path(_existing_refs[0])
                    elif len(_existing_refs) >= 2:
                        _roster = Path(lv_config.output_dir) / f"shot_{_idx}_character_roster.png"
                        if _roster.exists():
                            _char_ref = _roster
                        else:
                            try:
                                from hevi.image.qwen_image_service import qwen_image_edit

                                await qwen_image_edit(
                                    image_path=[Path(p) for p in _existing_refs[:3]],
                                    instruction=(
                                        f"这{min(len(_existing_refs), 3)}张图分别是不同角色"
                                        "各自的真实长相,把他们排列在同一张图里,每个人物的"
                                        "相貌、服饰都要跟各自对应的参考图保持一致,自然站姿,"
                                        "正面半身"
                                    ),
                                    output_path=_roster,
                                )
                                _char_ref = _roster
                            except Exception as _rce:
                                logger.warning(
                                    "shot %s 角色参考图合成失败,回退全片统一参考图: %s",
                                    outp.name,
                                    _rce,
                                )

                # SPEC-002 B2:风格参考图的真实图片条件化——只有 happyhorse_1_1_maas_lock
                # 认识 style_reference_image 这个 kwarg(见该 provider 函数文档),其余
                # provider(wan/ltx2/veo3/kling/…)不认识,不会被塞进去,零回归。
                _style_ref = None
                if style_reference_image and _prov == "happyhorse_1_1_maas_lock":
                    _sr = Path(style_reference_image)
                    if _sr.exists():
                        _style_ref = _sr

                # RFC-001 P1-3: omodul's per-shot LLM prompt otherwise bypasses all
                # hevi prompt engineering. Re-apply provider adaptation + style here
                # so every shot gets the provider suffix and a consistent look.
                from hevi.video.provider_config import FAL_PREMIUM_PROVIDERS

                # 生成前 lint(HEVI 路线图 §4.2,#28):这个 provider 会不会实际消费
                # negative_prompt——和下面下发负向的判定条件保持同一套,不该对本来就
                # 不支持负向的 provider(如 ltx2_cloud 基础版)误报"负向词块为空"。
                _negative_expected = _is_local_video or video_provider in FAL_PREMIUM_PROVIDERS
                try:
                    from hevi.prompt.prompt_pipeline import (
                        engineer_prompt_pair_from_preset,
                        ensure_identity_lock_sentence,
                        lint_engineered_prompt,
                    )

                    prompt, _neg = await engineer_prompt_pair_from_preset(
                        raw_prompt=prompt,
                        target_provider=_prov,
                        preset_name=style_preset,
                        style=prompt_style,
                        lighting=prompt_lighting,
                        camera=prompt_camera,
                        color_grade=prompt_color_grade,
                        mood=mood,
                        # 角色专属负向(如"避免多指")并入预设负向,同一条合并逻辑。
                        negative_prompt=extra_negative or "",
                    )
                    # 身份锁定句(seedance-prompt 方法论的直接应用):角色锁定的镜头
                    # prompt 里显式加一句"全程保持一致的身份/服装/发型/外貌"。
                    if _char_ref is not None:
                        prompt = ensure_identity_lock_sentence(prompt)
                    # 非完美事件库(HEVI 路线图 Phase3 #38):verité/真实感类预设专用,
                    # opt-in。库存量有限,用完(pick 返回 None)就不再插,不强行重复。
                    if imperfection_events:
                        from hevi.style.imperfection_library import pick_imperfection_event

                        _event = pick_imperfection_event(used=_used_imperfections)
                        if _event:
                            prompt = f"{prompt}, {_event}"
                    # RFC-002 item 8 + SaaS-4:负向逐镜头下发 —— 本地 provider 与高写实
                    # 云 provider(Veo3/Kling v2/海螺,均原生支持 negative_prompt)。
                    # ltx2_cloud 基础版 API 不收负向,故不下发(避免报错)。
                    if _neg and _negative_expected:
                        kw.setdefault("negative_prompt", _neg)
                    # 高写实云 provider 支持朝向:按成片规格给 aspect_ratio(9:16/16:9/1:1)。
                    if video_provider in FAL_PREMIUM_PROVIDERS:
                        _ar = (
                            "9:16"
                            if _target_w < _target_h
                            else ("16:9" if _target_w > _target_h else "1:1")
                        )
                        kw.setdefault("aspect_ratio", _ar)

                    _lint_violations = lint_engineered_prompt(
                        prompt,
                        negative_prompt=kw.get("negative_prompt", ""),
                        character_locked=_char_ref is not None,
                        negative_expected=_negative_expected,
                    )
                    if _lint_violations:
                        logger.warning(
                            "prompt lint(shot=%s): %s", outp.name, "; ".join(_lint_violations)
                        )
                except Exception as pe:  # never fail a shot over prompt polishing
                    logger.warning(f"per-shot prompt engineering skipped: {pe}")

                if _char_ref is not None:
                    kw["reference_image"] = _char_ref
                    kw.setdefault("mode", "i2v")
                    if _style_ref is not None:
                        kw["style_reference_image"] = _style_ref
                # RFC-001 P0-1: 无角色锁定时,回退 omodul 选中的参考帧(镜头间连续性)。
                elif reference_image is not None:
                    kw["reference_image"] = reference_image
                    kw.setdefault("mode", "i2v")

                # RFC-002 item 3: 本地 wan 按目标朝向夹取生成尺寸(480p 级)。
                if _is_local_video:
                    kw.setdefault("size", _wan_size_for_orientation())

                # SaaS-4 修复"永久卡 75%":oprim 的 fal 轮询是无总超时的 while True,
                # fal 任务若卡在队列/处理中会**无限轮询 → 整任务永久挂在某镜头**。
                # 这里给单镜头生成加总超时(默认 240s,本地推理放宽);超时抛
                # TimeoutError → omodul 逐变体 except 捕获 → 重试/fallback/占位,
                # 任务继续或干净失败,而非无限挂起。
                _shot_timeout = float(
                    os.getenv("HEVI_SHOT_TIMEOUT_S", "600" if _is_local_video else "240")
                )
                try:
                    res = await asyncio.wait_for(
                        caller(prompt=prompt, output_path=output_path, **kw),
                        timeout=_shot_timeout,
                    )
                except TimeoutError as _te:
                    logger.error(
                        "shot %s timed out after %.0fs (provider=%s) — 触发重试/fallback",
                        outp.name,
                        _shot_timeout,
                        video_provider,
                    )
                    raise RuntimeError(f"shot generation timeout ({_shot_timeout:.0f}s)") from _te
                final = Path(res) if res else output_path
                # item 7: 落盘 checkpoint marker(记录生成 provider)。
                if final.exists() and final.stat().st_size > 1024:
                    with contextlib.suppress(OSError):
                        final.with_suffix(final.suffix + ".done.json").write_text(
                            json.dumps({"provider": _prov})
                        )
                return final
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
            await _report("装配合成成片", 92.0)
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
            # 时长驱动修复:旁白通常应与画面时长相当;但脚本旁白过短时(如 qwen 给
            # 1-5min 目标只写出 ~7s 旁白),绝不能把整段画面压到旁白长度 —— 会变成每
            # 镜头零点几秒的闪切(曾致 14 镜头压成 6s)。取 max(旁白, 画面自然总长):
            # 旁白更长 → 拉伸镜头填满(原音画同步行为);旁白更短 → 保画面自然时长,
            # 旁白在前段播放、其后由装配器 apad 补静音。
            effective_total = max(total_audio, sum_native) if total_audio > 0 else 0.0
            for p, nat in zip(valid_shots, native, strict=False):
                if effective_total > 0:
                    share = (nat if nat > 0 else sum_native / len(valid_shots)) / sum_native
                    segments.append(
                        ShotSegment(p, target_duration=max(0.8, effective_total * share))
                    )
                else:
                    segments.append(ShotSegment(p, target_duration=None))

            # RFC-002 item 6: 旁白存在 → ASR 强制对齐字幕(取代 omodul 规划时长字幕)。
            # bilingual_language 给了 → 转写+翻译合并成双语字幕(每条 cue 两行,同时间码)。
            sub = subtitle_path
            if has_audio:
                assert audio_path is not None
                try:
                    if bilingual_language:
                        from hevi.assembly.subtitle_align import align_subtitles_bilingual

                        asr_srt = await align_subtitles_bilingual(
                            audio_path,
                            output_path.parent / "subtitles_bilingual.srt",
                            source_language=language,
                            target_language=bilingual_language,
                        )
                    else:
                        from hevi.assembly.subtitle_align import align_subtitles

                        asr_srt = await align_subtitles(
                            audio_path,
                            output_path.parent / "subtitles_asr.srt",
                            language=language,
                        )
                    if asr_srt is not None:
                        sub = asr_srt
                except Exception as se:
                    logger.warning(f"ASR subtitle alignment skipped: {se}")

            # 片头/片尾:装配前后拼接(保原时长,不参与音频驱动时长分配)。
            intro_seg = [ShotSegment(_intro_path)] if _intro_path is not None else []
            outro_seg = [ShotSegment(_outro_path)] if _outro_path is not None else []

            try:
                await assemble_longvideo(
                    shots=[*intro_seg, *segments, *outro_seg],
                    output_path=output_path,
                    narration_audio=audio_path if has_audio else None,
                    bgm_path=_bgm_path,
                    sfx_path=_sfx_path,
                    subtitle_path=sub,
                    subtitle_style=subtitle_style,
                    width=_target_w,
                    height=_target_h,
                    fps=_target_fps,
                    transition=transition,
                )
            except Exception as ae:
                # 装配失败兜底: 统一规格硬切(仍重编码,不用 -c:v copy 防花屏)。
                logger.error(f"hevi assembler failed, fallback to hard-cut: {ae}")
                await assemble_longvideo(
                    shots=[*intro_seg, *[ShotSegment(p) for p in valid_shots], *outro_seg],
                    output_path=output_path,
                    narration_audio=audio_path if has_audio else None,
                    bgm_path=_bgm_path,
                    sfx_path=_sfx_path,
                    width=_target_w,
                    height=_target_h,
                    fps=_target_fps,
                    transition="cut",
                )

            # RFC-002 item 11: 数字人讲解接入 —— 提供肖像图且有旁白时,用 Duix 由旁白
            # 驱动生成讲解口型视频,再与 B-roll 成片做画中画合成(数字人角落叠加)。
            if avatar_portrait and has_audio:
                assert audio_path is not None
                try:
                    from hevi.assembly.assembler import compose_avatar_broll
                    from hevi.audio.avatar_service import generate_avatar_clip

                    av_clip = output_path.parent / "avatar.mp4"
                    await generate_avatar_clip(
                        config=config or {},
                        portrait_image=Path(avatar_portrait),
                        audio_path=audio_path,
                        output_path=av_clip,
                    )
                    if av_clip.exists() and av_clip.stat().st_size > 1024:
                        composed = output_path.parent / "with_avatar.mp4"
                        await compose_avatar_broll(
                            broll_video=output_path,
                            avatar_video=av_clip,
                            output_path=composed,
                        )
                        import shutil as _sh

                        _sh.move(str(composed), str(output_path))
                except Exception as av_e:  # 数字人非关键路径, 失败仍出 B-roll 成片
                    logger.error(f"avatar compose skipped: {av_e}")

        # omodul._default_llm() calls ProviderRegistry.get(category=...) which is
        # incompatible with obase's singleton .get(). Inject the registered LLM directly.
        # LLM is stored in _llms dict (via register_llm), not _generic — use .llm() not .generic().
        from obase.provider_registry import ProviderRegistry as _PR

        # "default" 在本机通常退化成本地 ollama(hevi/providers/local_qwen_adapter.py:225,
        # 公共 DashScope 欠费停用后的既定回退),对结构化分镜脚本(script→scenes)不可靠——
        # 同 tongjian L0-L5 当年撞过的坑(e2e-local-llm-json-blocker)。这里比照 tongjian
        # 的解法,优先选非欠费的 qwen_cloud(阿里云百炼 workspace 端点);没注册才退回 default。
        try:
            _llm = _PR.get().llm("qwen_cloud")
        except Exception:
            _llm = _PR.get().llm("default")

        _providers: dict[str, Any] = {
            "llm": _llm,
            "storyboard_fn": _providers_storyboard_fn,
            "video_fn": injected_video_fn,
            "assembler_fn": bridged_assembler_fn,
        }
        if _providers_script_fn is not None:
            _providers["script_fn"] = _providers_script_fn
        if audio_provider != "ltx2_native":
            _providers["audio_fn"] = injected_audio_fn

        # 3O manifest §C2:注入本地 Qwen-VL 作 mllm。omodul 无 mllm 时回退文本 llm,
        # 而文本 qwen 丢帧图 → 双变体一致性选优退化为"选第一个"。有 VL 则真·看图选优。
        # 探针失败(模型未拉/ollama 挂)→ 不注入,行为回退旧态(无回归)。
        from hevi.providers.local_qwen_vl_adapter import (
            local_qwen_vl_adapter,
            vl_model_available,
        )

        if vl_model_available():
            _providers["mllm"] = local_qwen_vl_adapter
            logger.info("mllm: 本地 Qwen-VL 已注入 —— 双变体一致性选优走视觉")
        else:
            logger.warning("mllm: 本地 VL 不可用 → 一致性回退文本 llm(选第一个)")

        # 计数 shot 生成器(所有档位):预统计总镜头数 → total_shots + 逐镜头百分比,
        # 修复"停在 75%"的显示问题。short 档另叠加:真·单镜头 + 免逐镜头
        # select_reference / consistency 视觉-LLM 调用(单镜头无跨镜一致性可言)。
        from omodul.agentic_longvideo_pipeline import _default_shot_generator

        _is_short = duration_archetype == "short"
        _shot_budget = {"left": 1}  # short 跨章节总镜头预算(真·单镜头)
        # SPEC-001 §5:旁路收集每个 shot_plan 的台词/旁白文本(oskill.ShotPlan.tts_text),
        # 供生成完成后跑 Tier0 跨集关系一致性守护——consistency_fn 那条管线只拿得到渲染完的
        # 视频帧(见 hevi/verdict/scorecard.py::check_relationship_consistency 顶部注释),
        # 台词文本只有在这里(shot_gen_fn 阶段)才有。
        _dialogue_texts: list[str] = []

        def _shot_plans_from_locked_shot_list() -> list[Any]:
            """SPEC-003:locked_shot_list 的每一镜转成 ShotPlan 兼容对象(鸭子类型——
            下游只按属性访问,见本文件 injected_video_fn/_dialogue_texts 收集逻辑,不需要
            真的是 oskill.ShotPlan 实例)。short 档的单镜头预算裁剪在这条分支不生效——
            用户已经在④分镜级人工锁定了具体镜头数,不该被自动裁到 1 镜。"""
            from types import SimpleNamespace

            out = []
            for shot in locked_shot_list.get("shots", []):  # type: ignore[union-attr]
                # 2026-07-14 用户要求:字幕也彻底不要旁白——只收有说话人的对白,且不带
                # "角色名:" 前缀(像正片字幕那样只显示台词本身),舞台提示括号剥掉。
                dialogue_bits = [
                    _strip_stage_directions(ln.get("text", ""))
                    for ln in shot.get("dialogue_lines", [])
                    if (ln.get("character_name") or "").strip()
                ]
                dialogue_bits = [t for t in dialogue_bits if t]
                out.append(
                    SimpleNamespace(
                        shot_id=shot.get("shot_id", ""),
                        image_prompt=shot.get("visual_prompt", ""),
                        tts_text="。".join(dialogue_bits),
                        duration_s=float(shot.get("duration_s") or 5.0),
                    )
                )
            return out

        async def _counting_shot_gen_fn(*, storyboard: Any, llm: Any) -> Any:
            if locked_shot_list is not None:
                plans = _shot_plans_from_locked_shot_list()
            else:
                plans = await _default_shot_generator(storyboard=storyboard, llm=llm)
                if _is_short:
                    if _shot_budget["left"] <= 0:
                        return []
                    plans = plans[: _shot_budget["left"]] if plans else plans
                    _shot_budget["left"] -= len(plans) if plans else 0
            _shot_stats["total"] += len(plans) if plans else 0
            await _report("规划分镜脚本", 20.0, completed=0, total=_shot_stats["total"] or None)
            for p in plans or []:
                text = getattr(p, "tts_text", "") or getattr(p, "image_prompt", "")
                if text:
                    _dialogue_texts.append(text)
            return plans

        _providers["shot_gen_fn"] = _counting_shot_gen_fn

        if _is_short:
            from types import SimpleNamespace

            async def _noop_select_ref_fn(**_kw: Any) -> Any:
                # 返回 None → _select_ref_image(None)=None → t2v,不发 select LLM。
                return None

            async def _passthrough_consistency_fn(*, candidate_frames: Any, **_kw: Any) -> Any:
                # 单镜头直接采纳首个候选,跳过 mllm 帧一致性(视觉-LLM)调用。
                first = candidate_frames[0] if candidate_frames else None
                return SimpleNamespace(passed=True, best_frame=first)

            _providers["select_ref_fn"] = _noop_select_ref_fn
            _providers["consistency_fn"] = _passthrough_consistency_fn

        # 3O §C4:角色锁定时注入"身份锚评分卡"consistency_fn —— 双变体按"更像锁定角色"
        # 选优(C1 向量真·图对图,补 C2 遗留:mllm 一致性只把 reference 当文本发)。仅非
        # short(short 已真单镜头);参考图向量算失败则不注入,回退 mllm/omodul 默认一致性。
        # shot_verdict(HEVI 路线图 Phase1):consistency_fn 打完分即被 omodul 丢弃大半信息
        # (只透传 identity_score),这个字典按 shot index 旁路收集完整 Scorecard,供下面
        # map_longvideo_result 补全 style_score/vlm_score/诊断分类。
        _scorecards: dict[int, Any] = {}
        # 非完美事件库(#38):跟这一次 orchestrate_longvideo 调用同生命周期,不是
        # 全局/跨视频共享——不同视频各自从空集合开始,"不重复"只在这一部影片范围内。
        _used_imperfections: set[str] = set()
        if not _is_short and character_reference:
            _cref = Path(character_reference)
            if _cref.exists():

                def _embed_ref() -> tuple[list[float] | None, list[float] | None]:
                    """多区域(HEVI 路线图 Phase2 #34):全图 + 脸部区域裁剪各算一份,
                    scorecard 打分时两者都比一次取更像的那个(见 scorecard.py::_score_one)。
                    """
                    from hevi.subjects.subject_embed import SubjectEmbedError, subject_embed

                    whole: list[float] | None = None
                    face: list[float] | None = None
                    try:
                        whole = subject_embed(image_path=_cref, kind="style")
                    except SubjectEmbedError as _e:
                        logger.warning("scorecard: 角色参考图全图向量失败: %s", _e)
                    try:
                        face = subject_embed(image_path=_cref, kind="face")
                    except SubjectEmbedError as _e:
                        logger.warning("scorecard: 角色参考图脸部区域向量失败: %s", _e)
                    return whole, face

                _ref_emb, _ref_emb_face = await asyncio.to_thread(_embed_ref)
                if _ref_emb or _ref_emb_face:
                    from hevi.verdict import make_scorecard_consistency_fn

                    _providers["consistency_fn"] = make_scorecard_consistency_fn(
                        _ref_emb, subject_ref_embedding_face=_ref_emb_face, capture=_scorecards
                    )
                    logger.info("consistency_fn: 身份锚评分卡已注入(角色锁定 → 双变体按身份选优)")

        # Test-only: merge overrides injected via _PROVIDERS_OVERRIDE module var.
        import hevi.pipeline.longvideo_orchestrator as _self

        if _self._PROVIDERS_OVERRIDE:
            _providers.update(_self._PROVIDERS_OVERRIDE)

        try:
            if regenerate_shot_ids:
                # C3 verdict→返工:复用已建好的 _providers,只重生成指定镜头(hints 并入 prompt)。
                from omodul.agentic_longvideo_pipeline import regenerate_shots as _regen

                result = await _regen(
                    task_dir=lv_config.output_dir,
                    shot_ids=regenerate_shot_ids,
                    hints=shot_hints or {},
                    config=lv_config,
                    _providers=_providers,
                )
            else:
                result = await agentic_longvideo_pipeline(config=lv_config, _providers=_providers)
        finally:
            if _short_patch_active:
                _omodul_m._duration_archetype_to_seconds = _orig_dur_fn

        # SaaS-3/P10.F3 Fix: omodul suppresses shot failures by returning placeholders.
        # We must detect this to trigger Hevi's provider-level fallback.
        if result.video_path.exists() and result.video_path.stat().st_size < 1024:
            raise RuntimeError(f"Pipeline produced placeholder/empty output with {video_provider}")

        # RFC-002 item 13 / §7-4:成片质量体检纳入主链路。规格/连续性写日志 **并透出到结果**,
        # 供 task_service 判定交付/驱动返工(此前 rep.passed/violations 算了只 log 就丢)。
        # 仍不在此硬拒成片(已花算力);把裁决权交上层。
        _quality: dict[str, Any] | None = None
        try:
            from hevi.video.quality_check import quality_report

            # Tier0 字幕对齐率(HEVI 路线图 Phase1):omodul 把烧录字幕写在
            # output_dir/subtitles.srt(固定文件名约定,LongVideoResult 本身不带这个
            # 路径字段),存在才传,不存在就跳过这一项(不阻断体检)。
            _subtitle_path = Path(lv_config.output_dir) / "subtitles.srt"
            rep = await quality_report(
                result.video_path,
                expected_resolution=(_target_w, _target_h),
                require_audio=(audio_provider != "ltx2_native"),
                subtitle_path=_subtitle_path if _subtitle_path.exists() else None,
            )
            _quality = {
                "passed": rep.passed,
                "violations": list(rep.violations),
                "consistency": rep.consistency,
                "loudness_lufs": rep.loudness_lufs,
                "subtitle_alignment_rate": rep.subtitle_alignment_rate,
            }
            logger.info(
                "quality_report: %.2fs %dx%d fps=%.1f audio=%s consistency=%.2f "
                "loudness=%s subtitle_alignment=%s passed=%s %s",
                rep.stats.duration,
                rep.stats.width,
                rep.stats.height,
                rep.stats.fps,
                rep.stats.has_audio,
                rep.consistency,
                f"{rep.loudness_lufs:.1f}LUFS" if rep.loudness_lufs is not None else "n/a",
                f"{rep.subtitle_alignment_rate:.0%}"
                if rep.subtitle_alignment_rate is not None
                else "n/a",
                rep.passed,
                ("violations=" + "; ".join(rep.violations)) if rep.violations else "",
            )
        except Exception as qe:
            logger.warning(f"quality_report skipped: {qe}")

        # SPEC-001 §5:跨集角色关系一致性守护(Tier0,确定性,无 VLM)。同 quality_report
        # 一样是整片级检查(没有逐镜头拆分依据),AND 进同一个 `_quality["passed"]`——
        # 漂移只标记"这集需要人工复核",不会像逐镜头一致性分那样定向触发某个镜头返工
        # (漂移出在哪句台词、该重生成哪个镜头,现阶段判断不出来)。story_relationships
        # 为空(没走短剧通道派发,或 StoryGraph 本没抽出关系)时静默跳过,不影响其它调用方。
        if story_relationships:
            try:
                from hevi.storygraph.schemas import StoryCharacter, StoryRelationship
                from hevi.verdict.scorecard import check_relationship_consistency

                rel_check = check_relationship_consistency(
                    dialogue_texts=_dialogue_texts,
                    relationships=[StoryRelationship(**r) for r in story_relationships],
                    characters=[StoryCharacter(**c) for c in (story_characters or [])],
                    episode_event_ids=(episode_plan or {}).get("event_ids", []),
                )
                if rel_check["drifts"]:
                    logger.warning("跨集关系一致性守护(Tier0)发现漂移: %s", rel_check["drifts"])
                if _quality is None:
                    _quality = {"passed": rel_check["passed"], "violations": []}
                else:
                    _quality["passed"] = _quality["passed"] and rel_check["passed"]
                _quality["relationship_drifts"] = rel_check["drifts"]
            except Exception as re_:
                logger.warning(f"check_relationship_consistency skipped: {re_}")

        mapped = map_longvideo_result(
            result,
            scorecards=_scorecards,
            subject_id=subject_id,
            subject_version=subject_version,
            style_pack_id=style_pack_id,
            style_pack_version=style_pack_version,
            tier0_passed=(_quality.get("passed") if _quality is not None else None),
        )
        if _quality is not None:
            mapped["quality"] = _quality
        return mapped
