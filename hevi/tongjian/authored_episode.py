"""人工撰稿通鉴集:声明式剧本 → 编译成 Script/ShotList/CharacterBible → 走固化 back-half。

★ 为什么存在(2026-07-27 定,soffy 认可):前端 LLM 自动抽取(`produce_tongjian_v2_episode` 全程
入口)出来的解说词碎片化、重复、不连贯——立意/讲解词/对话必须**人工审核**。这个模块把「人手写
立意 + 白话解说 + 白话对话 + 逐镜配图」固化成一份声明式 `AuthoredEpisode`,编译器 `compile_*`
负责机械活(分配 line_id/shot_id/时序、narration 镜 `characters=[]` 路由讲解段、dialogue 镜带
target 自动触发廷辩反打),作者只管内容。

用法(见 `hevi.tongjian.episodes.shangyang_bianfa` 这份填好的模板/首集):
    ep = AuthoredEpisode(title=..., thesis=..., raw_text=..., intro=..., characters=[...],
                         locations={scene_id: 描述}, beats=[AuthoredBeat(...), ...])
    print(summarize_episode_structure(ep))          # 免费:审核撰稿 + 查演绎镜序
    await produce_authored_episode(ep, output_path=..., llm=...)  # 花钱:出片($80 熔断)

★ narration/commentary 镜的 `visual_prompt` 直接驱动讲解静帧配图(经 v2_jiangjie 加写实取景框 +
world_bible 画风锚),手写它就能治"南门木杆→枯树小院"这类配图错配。演绎段与讲解段共用同一份
world_bible(back-half 从 raw_text 现生成考据 gold)——跨栈接缝能接上的根本。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from hevi.tongjian.schemas import (
    CharacterBible,
    CharacterBibleEntry,
    Script,
    ScriptLine,
    Shot,
    ShotCamera,
    ShotList,
)

# 讲解镜按字数估的名义时长(ms):TTS 实测会重新归一,这里只求分镜时序单调、大致合理。
_MS_PER_CHAR = 180
_MS_BASE = 1200


class AuthoredCharacter(BaseModel):
    """一个出场角色:id 供剧本内引用,appearance 进 canon,voice 是 edge-tts 音色。"""

    id: str
    name: str
    appearance: str
    voice: str = "zh-CN-YunjianNeural"


class AuthoredBeat(BaseModel):
    """一个叙事拍:讲解镜(narration/commentary+visual_prompt)或演绎镜(dialogue+speaker/target)。"""

    kind: Literal["narration", "dialogue", "commentary"]
    scene: str  # 对应 locations 的 key;dialogue 同 scene 连续 → 合并成一场(自动反打)
    text: str
    # ── dialogue 用 ──
    speaker: str = ""  # 说话角色 id
    target: str = ""  # 受话角色 id(廷辩靠 speaker↔target 互驳识别反打轴)
    characters: list[str] = Field(default_factory=list)  # 在场角色 id;空则默认 [speaker]
    # ── narration/commentary 用 ──
    visual_prompt: str = ""  # ★ 手写配图(讲解静帧的视觉描述)
    # ── 三档置信标注(空=走 _clip_tier 默认:讲解→推演,演绎→演绎)──
    tier: str = ""  # 实录/推演/演绎
    cite: str = ""  # 出处(实录必填,如 资治通鉴·周纪二)


class AuthoredEpisode(BaseModel):
    """一份人工撰稿的通鉴集。thesis(立意)不进片,供审核/文档;raw_text 是 world_bible 考据底本。"""

    title: str
    thesis: str
    raw_text: str
    intro: str  # 片头点题口播(如"今天,我们回到…的现场")
    characters: list[AuthoredCharacter]
    locations: dict[str, str]  # scene_id -> 场景描述
    beats: list[AuthoredBeat]


class CompiledEpisode(BaseModel):
    """编译产物:直接喂 render_tongjian_v2_backhalf 的四件套 + 音色 + 片头。"""

    script: Script
    shotlist: ShotList
    character_bible: CharacterBible
    locations: dict[str, str]
    voices: dict[str, str]
    intro: str

    model_config = {"arbitrary_types_allowed": True}


def compile_authored_episode(ep: AuthoredEpisode) -> CompiledEpisode:
    """声明式撰稿 → 管线 schema。机械活集中在此:分配 id/时序、narration 镜清空 characters(路由讲解),
    dialogue 镜落 speaker/target/在场角色(路由演绎+反打)、tier/cite 落到 Shot。会校验引用完整性。"""
    char_ids = {c.id for c in ep.characters}
    bible = CharacterBible(
        characters=[
            CharacterBibleEntry(character_id=c.id, name=c.name, appearance=c.appearance)
            for c in ep.characters
        ]
    )
    voices = {c.name: c.voice for c in ep.characters}
    id_to_name = {c.id: c.name for c in ep.characters}

    lines: list[ScriptLine] = []
    shots: list[Shot] = []
    t_cursor = 0
    for i, b in enumerate(ep.beats):
        if b.scene not in ep.locations:
            raise ValueError(
                f"beat[{i}] scene={b.scene!r} 不在 locations 里(配图/空景板取不到场景)"
            )
        lid = f"L{i:02d}"
        dur = _MS_BASE + len(b.text) * _MS_PER_CHAR
        if b.kind == "dialogue":
            if b.speaker not in char_ids:
                raise ValueError(f"beat[{i}] dialogue speaker={b.speaker!r} 不在 characters 里")
            if b.target and b.target not in char_ids:
                raise ValueError(f"beat[{i}] dialogue target={b.target!r} 不在 characters 里")
            chars = list(b.characters) if b.characters else [b.speaker]
            line = ScriptLine(
                line_id=lid, type="dialogue", speaker=b.speaker, text=b.text, target=b.target
            )
        else:  # narration / commentary → 讲解段(characters 必须空,否则被判成 drama)
            if not b.visual_prompt.strip():
                raise ValueError(f"beat[{i}] {b.kind} 缺 visual_prompt(讲解镜配图会退回泛化空景)")
            chars = []
            line = ScriptLine(line_id=lid, type=b.kind, speaker="NARRATOR", text=b.text)
        if b.tier == "实录" and not b.cite.strip():
            raise ValueError(f"beat[{i}] tier=实录 必须带 cite(出处)")
        lines.append(line)
        shots.append(
            Shot(
                shot_id=f"SH_{i:02d}",
                line_ids=[lid],
                scene_id=b.scene,
                characters=chars,
                t_start_ms=t_cursor,
                t_end_ms=t_cursor + dur,
                camera=ShotCamera(),
                visual_prompt=b.visual_prompt,
                provenance_tier=b.tier,
                source_cite=b.cite,
            )
        )
        t_cursor += dur

    # 校验 dialogue 的 target 有真在同场出现(廷辩反打轴需要),仅告警不阻断(单人宣令 target 可空)
    _ = id_to_name  # 供将来 lint 用;当前 build_v2_scene_script_set 自行映射
    return CompiledEpisode(
        script=Script(lines=lines),
        shotlist=ShotList(shots=shots),
        character_bible=bible,
        locations=ep.locations,
        voices=voices,
        intro=ep.intro,
    )


def summarize_episode_structure(ep: AuthoredEpisode) -> str:
    """免费审核:叙事分组(讲解主干/演绎插段)+ 演绎镜序(反打)。跟 run_story.py --dry 同源,不花钱。"""
    from hevi.director.reverse_shots import summarize_shot_sequence
    from hevi.director.tongjian_v2_bridge import build_v2_scene_script_set
    from hevi.tongjian.v2_episode import group_shots_by_kind

    c = compile_authored_episode(ep)
    out = [f"《{ep.title}》  立意:{ep.thesis}", "== 叙事分组(讲解主干 + 演绎插段)=="]
    for k, ss in group_shots_by_kind(c.shotlist, c.script):
        out.append(f"  {k:<9} {[s.shot_id for s in ss]}")
    sss = build_v2_scene_script_set(
        script=c.script,
        shot_list=c.shotlist,
        id_to_name={ch.character_id: ch.name for ch in c.character_bible.characters},
        drama_only=True,
    )
    out.append("== 演绎镜序(反打)==")
    out.extend(
        f"  场{r['scene']} {r['seg']:<6}{r['shot_type']:<8}"
        f"{r['speaker'] or '—':<6}{r['side'] or '—':<6}前景={r['fg'] or '—'}"
        for r in summarize_shot_sequence(sss.scripts)
    )
    return "\n".join(out)


async def produce_authored_episode(
    ep: AuthoredEpisode,
    *,
    output_path: Path,
    llm: Any,
    budget_usd: float | None = 80.0,
    landscape: bool = True,
    gen_fn: Any = None,
    image_gen_fn: Any = None,
    tts_fn: Any = None,
) -> dict[str, Any]:
    """编译 + 出片(走固化 back-half)。world_bible 由 back-half 从 raw_text 现生成考据 gold。"""
    from hevi.tongjian.v2_episode import render_tongjian_v2_backhalf

    c = compile_authored_episode(ep)
    return await render_tongjian_v2_backhalf(
        script=c.script,
        shotlist=c.shotlist,
        character_bible=c.character_bible,
        raw_text=ep.raw_text,
        output_path=output_path,
        location=c.locations,
        llm=llm,
        voice_by_speaker=c.voices,
        budget_usd=budget_usd,
        landscape=landscape,
        intro_theme=ep.intro,
        gen_fn=gen_fn,
        image_gen_fn=image_gen_fn,
        tts_fn=tts_fn,
    )
