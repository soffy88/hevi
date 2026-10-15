"""一句话 → 自动补全 StoryPlan（规则 + 模板，不调付费 API）。"""

from __future__ import annotations

import re
from typing import Any
from hevi.storyplan.model import (
    HookSpec,
    NarrativeLayer,
    Scene,
    Sequence,
    Shot,
    ShotLayer,
    StoryBeat,
    StoryPlan,
    TimelineClip,
    TimelineTrack,
    TimelineLayer,
)


def autofill_story_plan(
    topic: str,
    *,
    aspect: str = "16:9",
    fps: int = 30,
    hook_type: str = "question",
    audience: str = "kids_2_6",
) -> StoryPlan:
    """给定一句话主题，无需付费 API，按规则与模板全自动补全三层结构 StoryPlan。"""
    clean_topic = topic.strip()
    if not clean_topic:
        clean_topic = "小水滴去哪儿了"

    # 1) 生成顺口播稿 (幼儿片语速较慢，约 2.5 ~ 3.0 字/秒，重复和节奏感强)
    if "水" in clean_topic or "云" in clean_topic:
        narration = (
            "小水滴躺在大海里，太阳公公一晒，它就变成了轻飘飘的水蒸气，飞到了天上。 "
            "小水滴变成了一朵白云，在天空散步。遇到冷空气，它变成小雨点，又落回了大地。 "
            "小朋友，你们知道小水滴最后去哪儿了吗？它回到了清澈的小河里，去找小伙伴玩啦！"
        )
        hook_text = "小水滴最后去哪儿了呢？"
        hook_kind = "result_first"  # 倒叙钩子：先看到云/结果
    elif "手" in clean_topic or "洗" in clean_topic:
        narration = (
            "小熊玩完泥巴回来，肚子咕噜咕噜叫，抓起苹果就要吃。 "
            "哎呀！小手上有好多看不见的细菌呢。如果把细菌吃进肚子，肚子就会痛痛哦。 "
            "小熊为什么要洗手呢？因为洗干净小手，才能健健康康、开开心心吃苹果呀！"
        )
        hook_text = "小熊为什么吃苹果前一定要先洗手呢？"
        hook_kind = "question"  # 提问钩子
    else:
        narration = (
            f"今天我们要讲的故事是：{clean_topic}。 "
            "小动物们遇到了一个有趣的问题，大家一起开动脑筋来解决它。 "
            "通过努力，大家终于明白了其中的秘密。小朋友，你学会了吗？"
        )
        hook_text = f"你知道{clean_topic}的秘密是什么吗？"
        hook_kind = hook_type

    sentences = [s.strip() for s in re.split(r"[。！？；]", narration) if s.strip()]
    if not sentences:
        sentences = [narration]

    total_chars = sum(len(s) for s in sentences)
    # 幼儿语速 ≤ 3.5 字/秒，此处按 2.8 字/秒估算时长
    duration_sec = max(8.0, round(total_chars / 2.8, 1))
    total_ms = int(duration_sec * 1000)

    # 2) 叙事层：beats（起因→经过→结果）+ 开场钩子
    beats = [
        StoryBeat(
            beat_id="beat_1_cause",
            phase="cause",
            summary=sentences[0] if len(sentences) > 0 else "起因：提出情境与核心问题",
            expectation=hook_text,
            start_ms=0,
            end_ms=int(total_ms * 0.3),
            semantic_refs=["topic_intro"],
        ),
        StoryBeat(
            beat_id="beat_2_process",
            phase="process",
            summary=sentences[1] if len(sentences) > 1 else "经过：尝试、探索与转折",
            expectation="寻找解决办法",
            start_ms=int(total_ms * 0.3),
            end_ms=int(total_ms * 0.75),
            semantic_refs=["exploration"],
        ),
        StoryBeat(
            beat_id="beat_3_result",
            phase="result",
            summary=sentences[2] if len(sentences) > 2 else "结果：问题解决与主题升华",
            expectation="回应开头期待与互动问句",
            start_ms=int(total_ms * 0.75),
            end_ms=total_ms,
            semantic_refs=["closure"],
        ),
    ]

    hook = HookSpec(
        hook_type=hook_kind,
        text=hook_text,
        start_ms=0,
        end_ms=min(3500, int(total_ms * 0.35)),
        shown_in=["voice", "subtitle", "visual"],
    )

    narrative = NarrativeLayer(
        hook=hook,
        beats=beats,
        closing_response=sentences[-1] if sentences else "小朋友，我们一起来记住这个好习惯吧！",
    )

    # 3) 镜头层：Sequence → Scene → Shot（六项必填齐全，动作有明确结束状态）
    shots = [
        Shot(
            shot_id="shot_01",
            scene_id="scene_1",
            sequence_id=1,
            purpose="开场钩子与交代环境",
            start_state="画面静止，背景温馨明亮，主角登场",
            action="主角向镜头挥手问候并提出开场疑问，动作平缓展开直至站定微笑",
            end_state="主角站定面向观众，疑问字幕保持在上方安全区",
            sound="旁白温柔发问，带有温和背景音乐",
            acceptance="前3秒内画面与声音双重呈现问题，无快切，语速合规",
            roll_role="A_main",
            b_roll_function="交代环境",
            shot_type="establishing",
            material_source="generated",
            new_info=[clean_topic, "主角登场", "提出问题"],
            start_ms=0,
            end_ms=int(total_ms * 0.3),
        ),
        Shot(
            shot_id="shot_02",
            scene_id="scene_1",
            sequence_id=1,
            purpose="发展推进与尝试（允许失败一次或探索）",
            start_state="主角处于探索状态，身处场景中央",
            action="主角进行尝试动作，遇到小波折后思考并找到正确方法，动作平稳过渡",
            end_state="主角露出恍然大悟的表情，双手叉腰或指向前方",
            sound="旁白讲解经过，音效轻柔伴随",
            acceptance="镜头时长≥2.5秒，动作状态有清晰起止，无冗余空转",
            roll_role="A_main",
            b_roll_function="补充说明",
            shot_type="character",
            material_source="generated",
            new_info=["探索过程", "核心知识点", "转折点"],
            start_ms=int(total_ms * 0.3),
            end_ms=int(total_ms * 0.75),
        ),
        Shot(
            shot_id="shot_03",
            scene_id="scene_1",
            sequence_id=1,
            purpose="闭环收束与复述互动",
            start_state="主角微笑站在画面中央，周围环境和谐",
            action="主角做出总结性动作（如点赞/合十/挥手），伴随结尾互动复述",
            end_state="画面渐隐收尾，主角保持微笑定格2秒",
            sound="旁白总结主题并留出互动空白，音乐柔和淡出",
            acceptance="开头问题在结尾得到明确回应，时间线闭环无黑场",
            roll_role="A_main",
            b_roll_function="衔接",
            shot_type="character",
            material_source="generated",
            new_info=["主题复述", "互动问句", "闭环"],
            start_ms=int(total_ms * 0.75),
            end_ms=total_ms,
        ),
    ]

    scene = Scene(scene_id="scene_1", location="温馨动画绘本舞台", time_of_day="day", shots=shots)
    sequence = Sequence(sequence_id=1, name="main_sequence", scenes=[scene])
    shot_layer = ShotLayer(sequences=[sequence])

    # 4) 时间线层：多轨（video, voice, music, sfx, subtitle）
    dt_seg = total_ms / max(1, len(sentences))
    voice_clips = []
    subtitle_clips = []
    for i, s in enumerate(sentences):
        st = int(i * dt_seg)
        et = int((i + 1) * dt_seg)
        voice_clips.append(TimelineClip(clip_id=f"v_{i}", track_kind="voice", start_ms=st, end_ms=et, text=s))
        subtitle_clips.append(TimelineClip(clip_id=f"sub_{i}", track_kind="subtitle", start_ms=st, end_ms=et, text=s))

    video_clips = [
        TimelineClip(clip_id=f"vid_{j}", track_kind="video", start_ms=sh.start_ms, end_ms=sh.end_ms, source_ref=sh.shot_id)
        for j, sh in enumerate(shots)
    ]
    music_clips = [
        TimelineClip(clip_id="mus_0", track_kind="music", start_ms=0, end_ms=total_ms, source_ref="bgm_warm_bed")
    ]
    sfx_clips = [
        TimelineClip(clip_id="sfx_0", track_kind="sfx", start_ms=0, end_ms=500, source_ref="chime_soft")
    ]

    tracks = [
        TimelineTrack(track_kind="video", clips=video_clips),
        TimelineTrack(track_kind="voice", clips=voice_clips),
        TimelineTrack(track_kind="music", clips=music_clips),
        TimelineTrack(track_kind="sfx", clips=sfx_clips),
        TimelineTrack(track_kind="subtitle", clips=subtitle_clips),
    ]
    timeline = TimelineLayer(duration_ms=total_ms, tracks=tracks)

    return StoryPlan(
        title=clean_topic,
        aspect=aspect,
        fps=fps,
        duration_sec=duration_sec,
        audience=audience,
        language="zh",
        narration_text=narration,
        narrative=narrative,
        shots=shot_layer,
        timeline=timeline,
        metadata={"generator": "hevi.storyplan.autofill", "hook_type": hook_kind},
    )
