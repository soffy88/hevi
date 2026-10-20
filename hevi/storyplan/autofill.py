"""一句话 → 自动补全 StoryPlan（规则 + 模板，随主题多变，不调付费 API）。"""

from __future__ import annotations

import re
from typing import Any
from hevi.storyplan.model import (
    ChangeStage,
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
    change_stages: list[ChangeStage | dict] | None = None,
) -> StoryPlan:
    """给定一句话主题，无需付费 API，按规则与模板全自动补全三层结构 StoryPlan（产物随主题深度变化）。"""
    clean_topic = topic.strip()
    if not clean_topic:
        clean_topic = "小水滴去哪儿了"

    # 1) 分主题动态生成口播稿与钩子（FIX-4: 拒绝千篇一律的通用模板）
    if "水" in clean_topic or "云" in clean_topic or "雨" in clean_topic:
        narration = (
            "小水滴躺在大海里，太阳公公一晒，它就变成了轻飘飘的水蒸气，飞到了天上。 "
            "小水滴变成了一朵白云，在天空散步。遇到冷空气，它变成小雨点，又落回了大地。 "
            "小朋友，你们知道小水滴最后去哪儿了吗？它回到了清澈的小河里，去找小伙伴玩啦！"
        )
        hook_text = "小水滴最后去哪儿了呢？"
        hook_kind = "result_first"
        domain = "nature"
    elif "手" in clean_topic or "洗" in clean_topic or "干净" in clean_topic:
        narration = (
            "小熊玩完泥巴回来，肚子咕噜咕噜叫，抓起苹果就要吃。 "
            "哎呀！小手上有好多看不见的细菌呢。如果把细菌吃进肚子，肚子就会痛痛哦。 "
            "小熊为什么要洗手呢？因为洗干净小手，才能健健康康、开开心心吃苹果呀！"
        )
        hook_text = "小熊为什么吃苹果前一定要先洗手呢？"
        hook_kind = "question"
        domain = "habit"
    elif "树" in clean_topic or "高" in clean_topic or "植物" in clean_topic or "花" in clean_topic:
        narration = (
            "小树苗每天站在泥土里，大口大口喝着雨水，晒着暖洋洋的太阳。 "
            "它伸展着绿油油的小叶子，一天一天往高处长。 "
            "小朋友，你们知道小树为什么能长得这么高吗？因为它有阳光和雨露的陪伴呀！"
        )
        hook_text = "小树为什么能够长得这么高呢？"
        hook_kind = "curiosity_image"
        domain = "plant"
    elif "早睡" in clean_topic or "觉" in clean_topic or "晚" in clean_topic or "星" in clean_topic:
        narration = (
            "月亮姐姐升上了夜空，星星眨着眼睛准备睡觉了。小兔子还在蹦蹦跳跳不肯躺下。 "
            "如果晚上不早睡，明天早上就没有精神和小伙伴一起跑步啦。 "
            "小朋友，我们为什么要早早睡觉呢？因为充足的睡眠能让我们长高高哦！"
        )
        hook_text = "小朋友为什么要乖乖早睡觉呢？"
        hook_kind = "question"
        domain = "habit"
    elif "太空" in clean_topic or "宇航" in clean_topic or "星" in clean_topic or "月" in clean_topic:
        narration = (
            "浩瀚的太空里有闪烁的银河、圆圆的地球和神秘的宇宙飞船。 "
            "宇航员叔叔穿上宇航服，在无重力的太空中开心地飘来飘去。 "
            "小朋友，太空里究竟有什么好玩的秘密呢？让我们一起乘坐火箭去探索吧！"
        )
        hook_text = "神秘的太空里面到底有什么呢？"
        hook_kind = "conflict"
        domain = "space"
    else:
        # 散列动态模板生成，确保不同非预设主题拥有独特的文本结构与叙事细节
        h_hash = abs(hash(clean_topic)) % 3
        if h_hash == 0:
            narration = (
                f"在美丽的森林里，大家都在讨论关于{clean_topic}的奇妙故事。 "
                f"小松鼠遇到了困难，通过仔细观察和动脑筋，终于找到了答案。 "
                f"小朋友，{clean_topic}究竟隐藏着什么奥秘呢？让我们一起来揭晓吧！"
            )
            hook_text = f"你知道{clean_topic}背后藏着什么秘密吗？"
            hook_kind = "question"
        elif h_hash == 1:
            narration = (
                f"清晨的阳光洒满大地，小动物们对{clean_topic}充满了好奇。 "
                f"大家齐心协力迈出探索的第一步，克服了重重小关卡。 "
                f"通过这次有趣的经历，大家终于弄明白了{clean_topic}是怎么回事啦！"
            )
            hook_text = f"为什么大家对{clean_topic}这么好奇呢？"
            hook_kind = "curiosity_image"
        else:
            narration = (
                f"每当提起{clean_topic}，小朋友们总有问不完的问题。 "
                f"其实只要仔细观察生活中的小细节，就能找到最棒的答案。 "
                f"让我们和主角一起去探索{clean_topic}的奇妙世界吧！"
            )
            hook_text = f"关于{clean_topic}，你也有同样的疑问吗？"
            hook_kind = "conflict"
        domain = "general"

    sentences = [s.strip() for s in re.split(r"[。！？；]", narration) if s.strip()]
    if not sentences:
        sentences = [narration]

    total_chars = sum(len(s) for s in sentences)
    duration_sec = max(8.0, round(total_chars / 2.8, 1))
    total_ms = int(duration_sec * 1000)

    # 2) 叙事层：beats + 开场钩子
    # 归一化蒙太奇阶段清单（ChangeStage 或等价 dict 均可）
    stages: list[ChangeStage] = [
        raw_stage if isinstance(raw_stage, ChangeStage) else ChangeStage(**raw_stage)
        for raw_stage in change_stages or []
    ]

    if stages:
        # 给定 change_stages 时按阶段生成 beats：一阶段至少一拍，
        # 时间轴按阶段数等分；phase 缺省按首=cause / 尾=result / 中间=process
        # 推断，阶段项自带合法 phase 时尊重其声明。
        beats = []
        n_stages = len(stages)
        for i, stage in enumerate(stages):
            declared = getattr(stage, "phase", None)
            if declared in {"cause", "process", "result", "reaction", "flashback", "flashforward"}:
                phase = declared  # type: ignore[assignment]
            elif n_stages == 1:
                phase = "process"
            elif i == 0:
                phase = "cause"
            elif i == n_stages - 1:
                phase = "result"
            else:
                phase = "process"
            detail = stage.description or stage.target_state
            beats.append(
                StoryBeat(
                    beat_id=f"beat_{domain}_stage_{i + 1}_{stage.name}",
                    phase=phase,
                    summary=f"{stage.name}：{detail}" if detail else stage.name,
                    expectation=stage.target_state or "推进到下一阶段目标状态",
                    start_ms=int(total_ms * i / n_stages),
                    end_ms=int(total_ms * (i + 1) / n_stages),
                    semantic_refs=[domain, "change_stage", stage.name],
                )
            )
    else:
        # 未给定 change_stages：保持原有百分比切分（cause 30% / process 45% /
        # result 15%），并在 result 后、收束前补 reaction 反应拍（末 10%），
        # 使自产计划叙事四环完整（见 check.py C8）。
        beats = [
            StoryBeat(
                beat_id=f"beat_{domain}_1_cause",
                phase="cause",
                summary=sentences[0] if len(sentences) > 0 else f"起因：引入主题 {clean_topic}",
                expectation=hook_text,
                start_ms=0,
                end_ms=int(total_ms * 0.3),
                semantic_refs=[domain, "topic_intro"],
            ),
            StoryBeat(
                beat_id=f"beat_{domain}_2_process",
                phase="process",
                summary=sentences[1] if len(sentences) > 1 else "经过：探索与互动体验",
                expectation="寻找核心解决方法",
                start_ms=int(total_ms * 0.3),
                end_ms=int(total_ms * 0.75),
                semantic_refs=[domain, "exploration"],
            ),
            StoryBeat(
                beat_id=f"beat_{domain}_3_result",
                phase="result",
                summary=sentences[2] if len(sentences) > 2 else "结果：得出结论与闭环总结",
                expectation="回应开头期待与互动问句",
                start_ms=int(total_ms * 0.75),
                end_ms=int(total_ms * 0.9),
                semantic_refs=[domain, "closure"],
            ),
            StoryBeat(
                beat_id=f"beat_{domain}_4_reaction",
                phase="reaction",
                summary=f"反应：主角看到结果后眼睛一亮，开心地拍手欢呼，把喜悦分享给小朋友（主题：{clean_topic}）",
                expectation="角色情绪反应与互动邀请",
                start_ms=int(total_ms * 0.9),
                end_ms=total_ms,
                semantic_refs=[domain, "reaction"],
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
        closing_response=sentences[-1] if sentences else f"小朋友，我们一起来记住关于{clean_topic}的小知识吧！",
        change_stages=stages or None,
    )

    # 3) 镜头层：Sequence → Scene → Shot（六项必填齐全，动作有明确结束状态）
    shots = [
        Shot(
            shot_id="shot_01",
            scene_id="scene_1",
            sequence_id=1,
            purpose=f"引入主题 {clean_topic} 与开场提问",
            start_state="画面明亮温馨，主角登场迎接观众",
            action=f"主角面向镜头挥手并提出关于 {clean_topic} 的生动疑问，表情期待",
            end_state="主角站定并微笑，疑问字幕清晰呈现",
            sound="旁白温柔发问，背景音乐轻快",
            acceptance="前3秒内画面与声音双重呈现问题，无快切，语速合规",
            roll_role="A_main",
            b_roll_function="交代环境",
            shot_type="establishing",
            material_source="generated",
            new_info=[clean_topic, "主角登场", "开场提问"],
            start_ms=0,
            end_ms=int(total_ms * 0.3),
        ),
        Shot(
            shot_id="shot_02",
            scene_id="scene_1",
            sequence_id=1,
            purpose=f"探索 {clean_topic} 的过程与互动演示",
            start_state="主角站定并微笑，疑问字幕清晰呈现",
            action=f"主角通过生动动作展示关于 {clean_topic} 的探索细节，动作平稳过渡",
            end_state="主角露出恍然大悟的欣喜表情，指向核心知识点",
            sound="旁白详细讲解，音效契合动作",
            acceptance="镜头时长充足，动作状态有清晰起止，无冗余空转",
            roll_role="A_main",
            b_roll_function="补充说明",
            shot_type="character",
            material_source="generated",
            new_info=["探索过程", "核心知识点", "转折互动"],
            start_ms=int(total_ms * 0.3),
            end_ms=int(total_ms * 0.75),
        ),
        Shot(
            shot_id="shot_03",
            scene_id="scene_1",
            sequence_id=1,
            purpose=f"总结升华关于 {clean_topic} 的完整闭环",
            start_state="主角露出恍然大悟的欣喜表情，指向核心知识点",
            action="主角做出点赞与挥手告别动作，伴随结尾闭环互动复述",
            end_state="画面平稳渐隐收尾，主角保持微笑定格",
            sound="旁白总结主题并留出互动空白，音乐柔和淡出",
            acceptance="开头问题在结尾得到明确回应，时间线闭环无黑场",
            roll_role="A_main",
            b_roll_function="衔接",
            shot_type="character",
            material_source="generated",
            new_info=["主题复述", "互动问句", "完美闭环"],
            start_ms=int(total_ms * 0.75),
            end_ms=total_ms,
        ),
    ]

    scene = Scene(scene_id="scene_1", location=f"{clean_topic}主题动画绘本舞台", time_of_day="day", shots=shots)
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
        metadata={"generator": "hevi.storyplan.autofill", "hook_type": hook_kind, "domain": domain},
    )
