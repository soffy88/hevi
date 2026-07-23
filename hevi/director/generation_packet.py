"""SPEC-006 ③Generation Packet 组装器 —— World Bible 切片 + Scene Script 一段时间轴 +
canon 参考图 → 段落级 prompt。

与现有 `hevi/tongjian/scene_render_avatar.py` 的 L4 分支(`quality_tier == "key"`)关系:
新增独立函数,**不改造**现有分支。现有 L4 分支以单镜 `ShotListItem` 为组装粒度,V2
Generation Packet 是段落级(10-15s,跨多镜量级),且这次垂直切片不产出 `ShotList`——没有
`ShotListItem` 可挂钩,改造现有分支收益小风险大。本模块只读 `WorldBible`+`SceneScript`,
不碰 `SceneStage`(呼应"生成读文档、SceneStage 只是校验影子"),只产出 prompt 文本落盘
供人工审阅,不接入渲染调用。

这是 G-V2 垂直切片(spec §5)③,纯确定性字符串/数值工程,不经 LLM。
"""

from __future__ import annotations

from hevi.director.pipeline_schemas import (
    GenerationPacket,
    SceneScript,
    SceneScriptSegment,
    WorldBible,
)


def group_segments_into_packets(
    scene_script: SceneScript, *, target_s: float = 12.0, max_s: float = 15.0
) -> list[list[SceneScriptSegment]]:
    """贪心把连续 segment 归组到 10-15s 窗口,不跨场景(单个 SceneScript 本就是一场)、不切断
    单个 segment(一个 segment 的时长哪怕超过 max_s 也整段归进当前组,不拆)。镜像
    `scene_stage.py::project_shot_space` 的"纯确定性投影,不经 LLM"哲学。"""
    groups: list[list[SceneScriptSegment]] = []
    current: list[SceneScriptSegment] = []
    current_start = 0.0
    for seg in scene_script.segments:
        if current and (seg.t_end_s - current_start) > max_s:
            groups.append(current)
            current = []
        if not current:
            current_start = seg.t_start_s
        current.append(seg)
        if (seg.t_end_s - current_start) >= target_s:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def assemble_generation_packet_prompt(
    *,
    world_bible: WorldBible,
    scene_script: SceneScript,
    scene_name: str,
    segments: list[SceneScriptSegment],
    canon_image_paths: dict[str, str],
) -> GenerationPacket:
    """World Bible 切片(该场出场角色的角色卷 + 该场世界卷 + 影像卷风格/persona + 声音卷)
    + Scene Script 该组 segment 完整 narrative_text + 台词 → 拼装 prompt 文本。格式参考
    现有 L4 分支拼接风格(见 scene_render_avatar.py 的 l4_prompt 构造),内容来源从"单镜
    字段拼接"换成"文档切片拼接"。"""
    present = set(scene_script.characters_present or [])
    char_entries = [c for c in world_bible.characters if c.name in present]
    world_entry = next((w for w in world_bible.world if w.name == scene_name), None)
    persona = world_bible.visual.camera_persona

    parts: list[str] = []
    parts.append(f"【影像风格】{world_bible.visual.style_manifesto}")
    parts.append(f"【摄像机人格:{persona.persona_id}】{persona.behavior_derivation_text}")
    parts.append(f"【场景:{scene_name}】{world_entry.profile_text if world_entry else ''}")

    char_lines = ["【出场人物】"]
    for c in char_entries:
        char_lines.append(f"  {c.name}:{c.profile_text}")
        if c.identity_lock_sentence:
            char_lines.append(f"  {c.identity_lock_sentence}")
        ref = canon_image_paths.get(c.name)
        if ref:
            char_lines.append(f"  （canon 参考图:{ref}）")
    parts.append("\n".join(char_lines))

    t_start = segments[0].t_start_s if segments else 0.0
    t_end = segments[-1].t_end_s if segments else 0.0
    timeline_lines = [f"【这一段发生的事(逐段时间轴,{t_start:.1f}s-{t_end:.1f}s)】"]
    dialogue_lines = ["【台词】"]
    for seg in segments:
        timeline_lines.append(f"  [{seg.t_start_s:.1f}-{seg.t_end_s:.1f}s] {seg.narrative_text}")
        for d in seg.dialogue:
            target = f"对{d.target_name}" if d.target_name else ""
            dialogue_lines.append(f"  {d.character_name}{target}:「{d.text}」")
    parts.append("\n".join(timeline_lines))
    if len(dialogue_lines) > 1:
        parts.append("\n".join(dialogue_lines))

    negatives = list(
        dict.fromkeys(
            world_bible.visual.negative_list + (world_entry.negative_list if world_entry else [])
        )
    )
    if negatives:
        parts.append("【负面清单】" + "；".join(negatives))

    prompt_text = "\n\n".join(parts)
    reference_image_names = [c.name for c in char_entries if c.name in canon_image_paths]

    return GenerationPacket(
        scene_ref=scene_script.scene_ref,
        segment_ids=[s.segment_id for s in segments],
        duration_s=t_end - t_start,
        prompt_text=prompt_text,
        reference_image_names=reference_image_names,
        source_trace={
            "characters": [c.name for c in char_entries],
            "world_entry": scene_name if world_entry else None,
            "camera_persona": persona.persona_id,
        },
    )
