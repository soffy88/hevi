"""短剧真实渲染桥接 —— StoryGraph + EpisodePlan → 复用通鉴 L2-L8 已验证的对白+口型
渲染管线,产出真实成片。见 STATUS.md 2026-07-12 条目:短剧此前接的是通用长视频管线
(`hevi/pipeline/longvideo_orchestrator.py`),那条线没有"对白 vs 旁白"的区分能力,
产出的是纯第三人称诗化旁白,零人物对话——用户反馈"比通鉴差远了"。通鉴的
`hevi/tongjian/scene_render_avatar.py`(cloud_avatar 渲染路径)已经验证过真实可用
(角色参考图锁脸 + happyhorse 数字人配音口型 + 旁白/对白分工),本模块只做一件事:
把 StoryGraph/EpisodePlan 的结构"翻译"成通鉴 L0/L1 的产物形状(ChapterIR/Constitution),
换成短剧口吻的现代白话戏剧化台词提示词,再原样调用通鉴已跑通的 L2(剧本)→L3(配音)→
L4(分镜)→L6(画面,cloud_avatar)→L7(音乐,可降级)→L8(装配) 这几层,不重新发明。

跟通鉴 L0/L1 的差异只在**不需要 LLM 抽取/立意**——StoryGraph 已经是抽取结果,
EpisodePlan 已经是"立意"(分幕/情感弧),这里全是确定性字段搬运,零 LLM 调用、零成本。
真正花钱/需要 LLM 的地方从 L2(剧本戏剧化)才开始,跟通鉴一致。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hevi.director.editor import REFERENCE_MISMATCH
from hevi.season_planner.schemas import EpisodePlan
from hevi.storygraph.schemas import StoryGraph
from hevi.tongjian.schemas import (
    Act,
    ChapterIR,
    ChapterMeta,
    CharacterBible,
    CharacterBibleEntry,
    CharacterIR,
    Constitution,
    EventIR,
    LayerConfig,
    LocationHint,
    QuoteIR,
    VisualStyle,
)

logger = logging.getLogger(__name__)

# 短剧默认视觉基调:现代都市/校园写实剧情,不是通鉴的水墨、也不强制卡通——
# 三者是三套独立预设,互不干扰(见 scene_render_avatar.py 的 style 参数化改造)。
DEFAULT_SHORTDRAMA_STYLE = "现代都市剧情片质感,写实电影摄影,自然光效,浅景深,柔和色调,竖屏构图"
DEFAULT_ASPECT_RATIO = "9:16"  # 短剧默认竖屏(手机观看),不是通鉴历史解说的 16:9
# scene_render_avatar.py 的旁白角色默认长相是"古装说书人史官"(须发斑白/素色长袍/
# 书卷薄雾)——那是资治通鉴专用形象,跟画风词(style)一样跟场景耦合,不能对短剧这种
# 现代都市题材硬套。短剧旁白改成当代讲述者形象,通过 LayerConfig.params["narrator_desc"]
# 覆盖(见该模块 build_frame_manifest_avatar 的 _p(config, "narrator_desc", ...))。
DEFAULT_SHORTDRAMA_NARRATOR_DESC = "一位气质沉稳的当代讲述者,便装,面容平和自然,近景半身像,背景虚化"
# hevi/tongjian/script.py 的 L2 剧本 prompt 人设默认是"历史正剧编剧(对标《大秦帝国》
# 《贞观之治》)"——原样照抄给短剧用会让 LLM 一直以为自己在写历史解说。2026-07-12
# 短剧真实反馈"大部分都是旁白,没有对话"根因之一就在这里(另一半是 script.py 新加的
# _check_dialogue_coverage 强制门,不是靠人设软提示)。
DEFAULT_SHORTDRAMA_SCREENWRITER_PERSONA = (
    "都市情感短剧编剧(对标热门竖屏短剧),擅长写现代年轻人的日常对话与冲突,"
    "台词要接地气、有来有回,不要写成播音腔解说"
)


def story_to_chapter_ir(story: StoryGraph) -> ChapterIR:
    """StoryGraph → ChapterIR 的确定性字段搬运(无 LLM),供 L2 build_script 复用。"""
    characters = [
        CharacterIR(
            character_id=c.char_id,
            canonical_name=c.name,
            aliases=list(c.aliases),
            role_in_chapter=c.role,
            faction=c.faction,
            source_spans=list(c.source_spans),
        )
        for c in story.characters
    ]
    events = [
        EventIR(
            event_id=e.event_id,
            summary=e.summary,
            actors=list(e.actors),
            location=e.location,
            causes=list(e.causes),
            effects=list(e.effects),
            dramatic_weight=e.dramatic_weight,
            source_span=e.source_span,
        )
        for e in story.events
    ]
    quotes = [
        QuoteIR(
            quote_id=q.quote_id,
            speaker=q.speaker,
            original=q.original,
            modern=q.modern,
            event_id=q.event_id,
            emotion=q.emotion,
        )
        for q in story.quotes
    ]
    locations = [
        LocationHint(
            scene_hint_id=loc.location_id,
            name=loc.name,
            type=loc.type,
            events=list(loc.events),
        )
        for loc in story.locations
    ]
    return ChapterIR(
        meta=ChapterMeta(source=story.meta.source, char_count=story.meta.char_count),
        characters=characters,
        events=events,
        quotes=quotes,
        locations=locations,
    )


def episode_to_constitution(
    ep: EpisodePlan,
    *,
    target_duration_sec: int,
    style: str = DEFAULT_SHORTDRAMA_STYLE,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
) -> Constitution:
    """EpisodePlan(已经是"立意"结果)→ Constitution,单幕对应一整集(短剧一集不需要
    再分三幕),不跑 L1 的 LLM 立意生成——那一步剧集规划器已经做过了。"""
    return Constitution(
        thesis=ep.target_emotion_arc,
        logline=ep.title,
        narrative_stance="第三人称限知视角,贴近当代都市/校园生活质感",
        tone=[ep.target_emotion_arc] if ep.target_emotion_arc else [],
        visual_style=VisualStyle(art_direction=style, aspect_ratio=aspect_ratio),
        act_structure=[
            Act(
                act=1,
                title=ep.title,
                events=list(ep.event_ids),
                emotion_curve=ep.target_emotion_arc,
            )
        ],
        forbidden=[],
        target_duration_sec=target_duration_sec,
    )


def character_bible_for_episode(
    ep: EpisodePlan, story: StoryGraph, subject_ref_paths: dict[str, str] | None = None
) -> CharacterBible:
    """本集出场角色的外形描述——直接用 StoryGraph 抽取时已经填好的 description,不再
    额外调 LLM 生成一遍(B0 抽取 prompt 本来就要求"外貌与性格的可视化特征")。

    `subject_ref_paths`(char_id → 该角色绑定 Subject 的参考图路径,通常是
    `reference_images[0]`,即"设封面"约定里下游锁脸用的那张):填进
    `CharacterBibleEntry.ref_image`——这个字段 scene_render_avatar.py 的 `_canonical()`
    本来就设计成"优先用它",此前只是没人在短剧这条路上填过,变成了摆设。填上后
    角色 canonical 像直接复用真实参考图,不再靠"文字描述+固定seed"重新生成。
    """
    by_id = {c.char_id: c for c in story.characters}
    entries = []
    for cid in ep.characters_present:
        c = by_id.get(cid)
        if c is None:
            continue
        entries.append(
            CharacterBibleEntry(
                character_id=c.char_id,
                name=c.name,
                appearance=c.description or f"{c.name},{c.role or '角色'}",
                ref_image=(subject_ref_paths or {}).get(cid),
            )
        )
    return CharacterBible(characters=entries)


async def render_episode(
    ep: EpisodePlan,
    story: StoryGraph,
    *,
    run_dir: Path,
    target_duration_sec: int = 180,
    style: str = DEFAULT_SHORTDRAMA_STYLE,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    resolution: str = "720P",
    llm: Any = None,
    tts_fn: Any = None,
    dramatize: bool = True,
    subject_ref_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    """本集真实渲染主入口:StoryGraph/EpisodePlan → 通鉴 L2-L8(cloud_avatar)→ 真实成片。

    复用 hevi.tongjian.* 已验证的 build_script/build_voiceover/build_shotlist/
    build_frame_manifest_avatar/build_music_plan/build_final_video,只是输入换成从
    StoryGraph/EpisodePlan 确定性搬运出的 ChapterIR/Constitution(不重新经过通鉴的
    L0 抽取/L1 立意生成——那两层的等价物已经是 B0 抽取 + 剧集规划器的产物)。

    返回 {"final_video": FinalVideo, "shots": [task_service._persist_shots 认的形状],
    "gate_reports": {layer: GateResult}}。任何一层失败都向上抛,由调用方(shortdrama
    路由)落 status=failed + error。
    """
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("qwen_cloud")
    if tts_fn is None:
        from obase.provider_registry import ProviderRegistry

        # L3 配音显式选 edge_tts,不用 build_voiceover 的默认值——那个默认值是
        # "cosyvoice"(其实注册成 vibevoice 的别名,见 providers/registry.py),要吃
        # 本机共享的、反复从 PCIe 总线掉线的 3080。通鉴自己验证过真实可用的"云水墨
        # 数字人"配置(_apply_cloud_avatar_preset)明确把 L3 换成 edge_tts(云端、零
        # GPU 依赖),这里跟着用同一份已验证配置,不要用回本地模型。
        tts_fn = ProviderRegistry.get().generic("audio", "edge_tts")

    run_dir.mkdir(parents=True, exist_ok=True)

    from hevi.tongjian.assemble import build_final_video
    from hevi.tongjian.music_plan import build_music_plan
    from hevi.tongjian.scene_render_avatar import build_frame_manifest_avatar, gate_avatar_manifest
    from hevi.tongjian.script import build_script
    from hevi.tongjian.shotlist import build_shotlist
    from hevi.tongjian.voiceover import build_voiceover

    chapter_ir = story_to_chapter_ir(story)
    constitution = episode_to_constitution(
        ep, target_duration_sec=target_duration_sec, style=style, aspect_ratio=aspect_ratio
    )
    gate_reports: dict[str, Any] = {}

    script, g2 = await build_script(
        constitution,
        chapter_ir,
        llm=llm,
        dramatize=dramatize,
        screenwriter_persona=DEFAULT_SHORTDRAMA_SCREENWRITER_PERSONA,
        include_commentary=False,  # "史论(臣光曰)"是通鉴专属概念,短剧没有这个体裁
    )
    gate_reports["script"] = g2
    if not script.lines:
        raise RuntimeError(f"剧本生成为空壳(L2 门:{g2.errors})")

    timeline, g3 = await build_voiceover(
        script=script, constitution=constitution, output_dir=run_dir, tts_fn=tts_fn
    )
    gate_reports["voiceover"] = g3

    character_bible = character_bible_for_episode(ep, story, subject_ref_paths)

    # event_id → 地点名,供 build_shotlist 判断场景连贯性(同地点连续事件不误切场景,
    # 见 shotlist.py::_infer_scene_id 的 2026-07-12 改动)。StoryGraph 抽取时已经填了
    # 这个字段,story_to_chapter_ir 原样搬运过来,这里直接建映射,零额外成本。
    event_locations = {e.event_id: e.location for e in chapter_ir.events if e.location}

    shotlist, g4 = await build_shotlist(
        timeline=timeline,
        script=script,
        character_bible=character_bible,
        llm=llm,
        event_locations=event_locations,
        split_long_shots=False,  # 数字人管线每镜重生成音频,长镜头拆子镜头会重复配音
    )
    gate_reports["shotlist"] = g4

    frame_manifest = await build_frame_manifest_avatar(
        shotlist=shotlist,
        script=script,
        character_bible=character_bible,
        constitution=constitution,
        run_dir=run_dir,
        config=LayerConfig(
            model="cloud_avatar",
            params={
                "style": style,
                "resolution": resolution,
                "narrator_desc": DEFAULT_SHORTDRAMA_NARRATOR_DESC,
            },
        ),
    )
    g6 = gate_avatar_manifest(frame_manifest)
    gate_reports["avatar_manifest"] = g6

    try:
        music_plan, g7 = await build_music_plan(
            shotlist=shotlist, timeline=timeline, constitution=constitution
        )
        gate_reports["music_plan"] = g7
    except Exception as e:  # noqa: BLE001 — L7 非致命,降级到无音乐(同通鉴 router 惯例)
        logger.warning("shortdrama render: L7 音乐规划失败,降级无音乐: %s", e)
        from hevi.tongjian.schemas import MusicPlan

        music_plan = MusicPlan()

    final_video, g8 = await build_final_video(
        shotlist=shotlist,
        frame_manifest=frame_manifest,
        timeline=timeline,
        script=script,
        music_plan=music_plan,
        constitution=constitution,
        audio_dir=run_dir,
        output_dir=run_dir,
    )
    gate_reports["final"] = g8

    shots = _frame_manifest_to_shot_states(frame_manifest)
    return {"final_video": final_video, "shots": shots, "gate_reports": gate_reports}


def _frame_manifest_to_shot_states(
    frame_manifest: Any, *, consistency_floor: float = 0.75
) -> list[dict[str, Any]]:
    """FrameManifest.frames → task_service._persist_shots() 认的 shot 字典形状,供
    SeasonBoard 既有的逐镜头卡片(taskApi.shots())直接复用,不用改前端一行代码。

    shot_states.shot_index 是整数列,按 frame_manifest 顺序(= shotlist 顺序)编号,
    不用 shot.shot_id(那是 "1-1" 这种字符串,给人看的,不是数据库列的形状)。

    2026-07-12 补:`character_consistency`(scene_render_avatar.py 新算的 CLIP 漂移分)
    此前只是透传,从不影响 passed/diagnosis_category——生成时锚定了身份,但没人事后
    校验有没有漂移。分数低于 floor 时按 `hevi.director.editor` 同一套诊断分类标记
    REFERENCE_MISMATCH(阈值复用 editor.review() 的默认 consistency_floor=0.75,同一
    套语义,不是另定一个标准),SeasonBoard 现有的"重新生成选中"就能对上这些镜头。
    生成调用本身失败(degraded)优先级更高,不会被一个巧合的低分覆盖。
    """
    out: list[dict[str, Any]] = []
    for idx, frame in enumerate(frame_manifest.frames):
        score = frame.character_consistency
        drifted = not frame.degraded and score is not None and score < consistency_floor
        diagnosis = frame.degrade_reason or (REFERENCE_MISMATCH if drifted else None)
        out.append(
            {
                "index": idx,
                "path": frame.clip_path or frame.frame_path or None,
                "passed": not frame.degraded and not drifted,
                "provider": "cloud_avatar",
                "consistency_score": score,
                "diagnosis_category": diagnosis,
                "retry_count": 0,
            }
        )
    return out
