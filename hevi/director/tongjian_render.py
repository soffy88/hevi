"""SPEC-003 ⑤生成(通鉴对白+口型后端)—— 把导演流水线锁定的分镜/设计清单/立意,
接到通鉴已验证的 cloud_avatar 对白管线上,治"对白与画面各走各的 / 看不到说话人 /
没感情"三连。

为什么不走 orchestrate_longvideo(通用长视频管线):它把全片对白拼成一条音轨,再把
独立生成的镜头拉伸去填满——对白跟镜头没有任何对齐,也没有口型/数字人,看不到谁在说话
(2026-07-14 用户实测抱怨,与 2026-07-12 短剧弃用它的原因一致)。

为什么不直接调 season_planner.tongjian_bridge.render_episode:它内部会用 LLM 重新
build_script/build_shotlist —— 会把导演流水线人工审核锁定的剧本/分镜整个丢掉重写。
这里在更低一层桥接:把锁定内容确定性地转成通鉴的 Script/ShotList/CharacterBible/
Constitution,只跑 L3 配音 → L6 数字人 → L7 音乐 → L8 装配,不再经过 L2/L4 生成。

通鉴管线的关键能力(逐 shot talking clip,自带同步配音+口型):
  build_voiceover      逐行 TTS,每行一个音频段 + 精确时间边界(voiceover.py)
  build_frame_manifest_avatar  逐 shot 用 happyhorse-1.1 出"角色开口说话"的 clip
                                (scene_render_avatar.py,口型/可见说话人)
  build_final_video    识别 clip_path 直接拼接,音已在 clip 里 → 天然音画同步
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hevi.director.pipeline_schemas import Concept, DesignList, ShotList
from hevi.tongjian.schemas import (
    Act,
    CharacterBible,
    CharacterBibleEntry,
    Constitution,
    LayerConfig,
    Script,
    ScriptLine,
    Shot,
    ShotCamera,
    VisualStyle,
)
from hevi.tongjian.schemas import (
    ShotList as TjShotList,
)

logger = logging.getLogger(__name__)

# 导演分镜的景别字符串(中文自由文本)→ 通鉴 ShotCamera.shot_size 枚举。命不中默认 medium。
_SHOT_SIZE_MAP: tuple[tuple[tuple[str, ...], str], ...] = (
    (("特写", "extreme", "极特"), "close_up"),
    (("近", "close"), "medium_close"),
    (("中", "medium"), "medium"),
    (("全", "远", "wide", "大全"), "wide"),
)


def _map_shot_size(camera_or_size: str) -> str:
    s = camera_or_size or ""
    for keys, val in _SHOT_SIZE_MAP:
        if any(k in s for k in keys):
            return val
    return "medium"


def build_tongjian_inputs(
    *,
    shot_list: ShotList,
    design_list: DesignList,
    concept: Concept,
    voice_by_speaker: dict[str, str],
    aspect_ratio: str = "9:16",
    target_duration_sec: int = 180,
) -> tuple[Script, TjShotList, CharacterBible]:
    """锁定的导演内容 → 通鉴 Script + ShotList + CharacterBible(确定性转换,无 LLM)。

    - 只保留有说话人的对白行(旁白行 character_name 为空,按用户要求整段不要)。
    - 每句对白一条 ScriptLine(type=dialogue,dramatized=True——原文无逐字引语约束);
      line_id 全片顺序编号,记录每个 shot 覆盖哪些 line_id。
    - 没有任何对白的镜头(原本是纯旁白镜头)在这一版直接丢弃:没台词、不要旁白,数字人
      管线没有可讲的内容;导演可在④分镜级保证镜头都有台词。
    """
    lines: list[ScriptLine] = []
    tj_shots: list[Shot] = []
    bible_names = {c.name for c in design_list.characters if c.name}
    scene_names = {s.name for s in design_list.scenes if s.name}
    n = 0
    for shot in shot_list.shots:
        shot_line_ids: list[str] = []
        for dl in shot.dialogue_lines:
            speaker = (dl.character_name or "").strip()
            text = (dl.text or "").strip()
            if not speaker or not text:
                continue  # 旁白 / 空行:丢弃
            n += 1
            line_id = f"ln{n:03d}"
            # INC-001 §H:受话对象须是已锁定角色且不是说话人本人,才作 eyeline 数据源;否则丢弃。
            target = (dl.target_name or "").strip()
            if target not in bible_names or target == speaker:
                target = ""
            lines.append(
                ScriptLine(
                    line_id=line_id,
                    act=1,
                    type="dialogue",
                    speaker=speaker,
                    text=text,
                    dramatized=True,
                    target=target,
                )
            )
            shot_line_ids.append(line_id)
        shot_chars = [c for c in (shot.character_names or []) if c in bible_names]
        visual = (shot.visual_prompt or "").strip()
        if not shot_line_ids:
            # 无对白镜头:保留为静默动作/建场空镜(电影语言:开场空镜、人物动作、
            # 刺杀/擒拿等动作镜头,渲染为无配音的画面动作,见 render 侧 silent_action)。
            # 什么视觉描述都没有才真丢——那种镜头没内容可生成。
            if not visual:
                continue
        elif not shot_chars:  # 对白镜头兜底:至少放该镜第一句台词的说话人
            shot_chars = [lines[-len(shot_line_ids)].speaker]
        scene_id = (
            shot.scene_name if shot.scene_name in scene_names else (shot.scene_name or "scene")
        )
        tj_shots.append(
            Shot(
                shot_id=shot.shot_id or f"SH{len(tj_shots) + 1:03d}",
                line_ids=shot_line_ids,
                scene_id=scene_id,
                characters=shot_chars,
                camera=ShotCamera(shot_size=_map_shot_size(shot.shot_size or shot.camera)),
                visual_prompt=visual,
                motion_mode="img2video",
                action_beats=list(shot.action_beats or []),  # INC-001 §B 动作弧透传到 L6 kf2v
            )
        )

    character_bible = CharacterBible(
        characters=[
            CharacterBibleEntry(
                character_id=c.name,
                name=c.name,
                appearance=" ".join(
                    x for x in (c.appearance, c.wardrobe, c.hairstyle) if x
                ).strip(),
                voice_id=voice_by_speaker.get(c.name),
            )
            for c in design_list.characters
            if c.name
        ]
    )
    return Script(lines=lines), TjShotList(shots=tj_shots), character_bible


def _build_constitution(
    concept: Concept, *, aspect_ratio: str, target_duration_sec: int
) -> Constitution:
    return Constitution(
        thesis=concept.theme or "",
        logline=concept.theme or "",
        tone=[t for t in (concept.tone,) if t],
        visual_style=VisualStyle(
            art_direction=concept.style or "",
            aspect_ratio=aspect_ratio,
        ),
        act_structure=[Act(act=1, title="", emotion_curve=concept.tone or "")],
        target_duration_sec=target_duration_sec,
    )


_ACTION_SHOT_MS = 4000  # 静默动作/建场镜头的名义时长(无对白音频驱动,给个视觉节拍)


def _fill_shot_timings(shotlist: TjShotList, timeline: Any) -> TjShotList:
    """L3 timeline(逐行音频段)→ 回填每个 shot 的 t_start_ms/t_end_ms。对白镜头取其覆盖
    的所有 line 音频段的最小起点/最大终点;静默动作镜头(无 line_ids/无音频段)按名义时长
    顺序接在时间轴上。装配(_assemble_avatar_clips)是按 shotlist 顺序拼 clip,时间边界只
    要连续不崩即可,精确对齐由每个 clip 自带时长保证。"""
    seg_by_line = {seg.line_id: seg for seg in timeline.audio_segments}
    new_shots: list[Shot] = []
    cursor_ms = 0
    for shot in shotlist.shots:
        segs = [seg_by_line[lid] for lid in shot.line_ids if lid in seg_by_line]
        if segs:
            start = min(s.t_start_ms for s in segs)
            end = max(s.t_end_ms for s in segs)
        elif shot.visual_prompt:
            # 静默动作/建场镜头:接在游标后,名义 4s。
            start = cursor_ms
            end = cursor_ms + _ACTION_SHOT_MS
        else:
            continue  # 既无对白又无画面 → 丢
        cursor_ms = max(cursor_ms, end)
        new_shots.append(shot.model_copy(update={"t_start_ms": start, "t_end_ms": end}))
    return TjShotList(shots=new_shots)


async def render_director_episode(
    *,
    shot_list: ShotList,
    design_list: DesignList,
    concept: Concept,
    run_dir: Path,
    subject_ref_paths: dict[str, str],
    voice_by_speaker: dict[str, str],
    aspect_ratio: str = "9:16",
    target_duration_sec: int = 180,
    style: str | None = None,
    llm: Any = None,
    tts_fn: Any = None,
) -> dict[str, Any]:
    """导演流水线锁定内容 → 通鉴 L3-L8 → 真实成片(对白+口型+按角色配音+情绪)。

    返回 {"final_video": FinalVideo, "shots": [_persist_shots 认的形状], "gate_reports": {...}}
    —— 与 season_planner.tongjian_bridge.render_episode 同形状,produce 端可同样落库。
    """
    from obase.provider_registry import ProviderRegistry

    from hevi.season_planner.tongjian_bridge import (
        DEFAULT_SHORTDRAMA_NARRATOR_DESC,
        DEFAULT_SHORTDRAMA_STYLE,
        _frame_manifest_to_shot_states,
    )
    from hevi.tongjian.assemble import build_final_video
    from hevi.tongjian.music_plan import build_music_plan
    from hevi.tongjian.scene_render_avatar import build_frame_manifest_avatar, gate_avatar_manifest
    from hevi.tongjian.schemas import MusicPlan
    from hevi.tongjian.voiceover import build_voiceover

    run_dir.mkdir(parents=True, exist_ok=True)
    style = style or concept.style or DEFAULT_SHORTDRAMA_STYLE
    if llm is None:
        llm = ProviderRegistry.get().llm("qwen_cloud")
    if tts_fn is None:
        # 同 tongjian_bridge:L3 显式 edge_tts(云端零 GPU 依赖),不用会吃本地掉线 3080
        # 的 vibevoice 默认值。
        tts_fn = ProviderRegistry.get().generic("audio", "edge_tts")

    script, shotlist, character_bible = build_tongjian_inputs(
        shot_list=shot_list,
        design_list=design_list,
        concept=concept,
        voice_by_speaker=voice_by_speaker,
        aspect_ratio=aspect_ratio,
        target_duration_sec=target_duration_sec,
    )
    if not script.lines:
        raise RuntimeError("导演分镜里没有任何对白行(旁白已按要求剔除)——无可生成内容")

    # 把设计清单锁定的角色参考图贴进 bible(数字人 keyframe 的脸从这来)。
    ref_by_name = subject_ref_paths or {}
    character_bible = CharacterBible(
        characters=[
            e.model_copy(update={"ref_image": ref_by_name.get(e.character_id)})
            for e in character_bible.characters
        ]
    )
    constitution = _build_constitution(
        concept, aspect_ratio=aspect_ratio, target_duration_sec=target_duration_sec
    )

    # 逐行情绪推断(治"没感情"):失败则每行中性,不阻断。
    try:
        from hevi.prompt.emotion_inference import infer_line_emotions

        emotions = await infer_line_emotions([ln.text for ln in script.lines])
        script = Script(
            lines=[
                ln.model_copy(update={"emotion": emotions[i] if i < len(emotions) else ""})
                for i, ln in enumerate(script.lines)
            ]
        )
    except Exception as e:
        logger.warning("director 通鉴渲染:逐行情绪推断失败,按中性继续: %s", e)

    gate_reports: dict[str, Any] = {}
    timeline, g3 = await build_voiceover(
        script=script,
        constitution=constitution,
        output_dir=run_dir,
        tts_fn=tts_fn,
        voice_by_speaker=voice_by_speaker,
    )
    gate_reports["voiceover"] = g3
    if not timeline.audio_segments:
        raise RuntimeError(f"配音时间轴为空(L3 门:{g3.errors})")

    shotlist = _fill_shot_timings(shotlist, timeline)
    if not shotlist.shots:
        raise RuntimeError("回填时间轴后没有任何镜头")

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
                "resolution": "720P",
                "narrator_desc": DEFAULT_SHORTDRAMA_NARRATOR_DESC,
                # 导演流水线要电影语言:非对白镜头渲成纯静默动作/建场空镜,不加史官旁白配音
                # (用户要求"不要旁白、要有场景/动作")。
                "non_dialogue_mode": "silent_action",
            },
        ),
    )
    gate_reports["avatar_manifest"] = gate_avatar_manifest(frame_manifest)

    try:
        music_plan, g7 = await build_music_plan(
            shotlist=shotlist, timeline=timeline, constitution=constitution
        )
        gate_reports["music_plan"] = g7
    except Exception as e:
        logger.warning("director 通鉴渲染:L7 音乐规划失败,降级无音乐: %s", e)
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

    return {
        "final_video": final_video,
        "shots": _frame_manifest_to_shot_states(frame_manifest),
        "gate_reports": gate_reports,
    }
