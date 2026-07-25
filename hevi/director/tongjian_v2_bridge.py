"""通鉴演绎段 → V2 渲染栈桥接器(SPEC-005-V2 §1)。

架构决策(soffy 拍板,方案 B):不把 tongjian 特化注入 V2 的 ①立意/②剧本(V2 screenplay 硬性
自由编造对白=史实反面),而是复用 tongjian 现成 L0-L2 前端产出的**已过 G2/CG2.5 史实门**的
`Script`/`ShotList`/`CharacterBible`,在这里**确定性映射**成 V2 的 `SceneScriptSet`/`DesignList`,
喂给 `run_v2_produce` 渲染——拿全 V2 战果(写实统一/运镜多样/L5 三级/审核预案/持久化)。

**史实红线不在这层**:quote_id/dramatized 溯源、G2 事实幻觉门、CG2.5、T1 版权 lint 全在 tongjian
L2(桥接之前)跑过。这里只做无损映射 + 把 quote_id/dramatized 审计透传进 V2(反查史料出处用,
不进生成端)。反向参照 `director/tongjian_render.py::build_tongjian_inputs`(V2→tongjian),照它反着写。

WorldBible 不来自 tongjian(前端无对应物),由调用方用 `generate_world_bible_draft(
visual_style="historical")` 新生成(见 `build_v2_inputs_from_tongjian`)。
"""

from __future__ import annotations

from typing import Any

from hevi.director.pipeline_schemas import (
    DesignCharacter,
    DesignList,
    SceneScript,
    SceneScriptDialogueLine,
    SceneScriptSegment,
    SceneScriptSet,
)

# tongjian ShotCamera.movement → V2 camera_movement(SPEC-005-V2 §1.2)。映射后仍过 V2 的
# enforce_camera_budget(全片配比)+ 强运动×身份互斥;演绎段镜少配比几乎不触发,主要靠此映射。
_CAMERA_MOVEMENT_MAP: dict[str, str] = {
    "static": "静态对话",
    "slow_push_in": "定场推",  # 首镜/情绪点由 _map_camera 细分峰值轻推
    "slow_pull_out": "横移",  # V2 无拉远类,近似
    "pan_left": "横移",
    "pan_right": "横移",
    "tilt_up": "摇向声源",
    "tilt_down": "摇向声源",
}


def _map_camera(movement: str, *, is_first_shot_in_scene: bool) -> str:
    """运镜词表映射。slow_push_in 首镜→定场推,非首镜(情绪点)→峰值轻推。未知→静态对话。"""
    mv = (movement or "static").strip()
    if mv == "slow_push_in":
        return "定场推" if is_first_shot_in_scene else "峰值轻推"
    return _CAMERA_MOVEMENT_MAP.get(mv, "静态对话")


def _is_drama_shot(shot: Any, lines_by_id: dict[str, Any]) -> bool:
    """判一镜是不是演绎(drama):有对白行(type==dialogue)或有在场角色 → drama;否则 narration。
    SPEC-005 架构:一集=讲解主干+演绎插段,只有 drama 镜进 produce_v2 演绎段,narration 镜走讲解段
    (sdxl_local 图解)。"""
    if shot.characters:
        return True
    return any(
        (ln := lines_by_id.get(lid)) is not None and ln.type == "dialogue" for lid in shot.line_ids
    )


def partition_drama_narration(script: Any, shot_list: Any) -> tuple[list[Any], list[Any]]:
    """把 shotlist 分成(drama 镜, narration 镜)——drama→produce_v2 演绎段,narration→讲解段。
    过场镜(is_transition)两边都不要。"""
    lines_by_id = {ln.line_id: ln for ln in script.lines}
    drama, narration = [], []
    for shot in shot_list.shots:
        if shot.is_transition:
            continue
        (drama if _is_drama_shot(shot, lines_by_id) else narration).append(shot)
    return drama, narration


def build_v2_scene_script_set(
    *, script: Any, shot_list: Any, id_to_name: dict[str, str], drama_only: bool = False
) -> SceneScriptSet:
    """tongjian `Script` + `ShotList` → V2 `SceneScriptSet`(SPEC-005-V2 §1.1)。确定性纯函数。

    一镜(`Shot`)→一段(`SceneScriptSegment`);按 `Shot.scene_id` 分组成 `SceneScript`
    (scene_ref = 按 scene_id 首现顺序赋的整数)。`id_to_name`:character_id→name(从 CharacterBible
    构建),tongjian 用 id、V2 用 name。跳过 `is_transition` 过场镜。**`drama_only=True`(通鉴演绎段
    默认走这个):只保留 drama 镜(有对白/角色),narration 镜留给讲解段——否则会把讲解的旁白镜也
    塞进 produce_v2 付费渲染(2026-07-24 商鞅立木实证:不过滤 16 镜→14 段,过滤后只 drama)。**"""
    lines_by_id: dict[str, Any] = {ln.line_id: ln for ln in script.lines}

    # 按 scene_id 首现顺序分配 scene_ref
    def _skip(shot: Any) -> bool:
        return shot.is_transition or (drama_only and not _is_drama_shot(shot, lines_by_id))

    scene_ref_by_id: dict[str, int] = {}
    for shot in shot_list.shots:
        if _skip(shot):
            continue
        sid = shot.scene_id or ""
        if sid not in scene_ref_by_id:
            scene_ref_by_id[sid] = len(scene_ref_by_id) + 1

    segments_by_scene: dict[int, list[SceneScriptSegment]] = {}
    chars_by_scene: dict[int, list[str]] = {}

    for shot in shot_list.shots:
        if _skip(shot):
            continue
        scene_ref = scene_ref_by_id[shot.scene_id or ""]
        shot_lines = [lines_by_id[lid] for lid in shot.line_ids if lid in lines_by_id]

        # 对白行 → dialogue;旁白/史论行 → 并进 narrative_text
        dialogue: list[SceneScriptDialogueLine] = []
        narration_bits: list[str] = []
        for ln in shot_lines:
            if ln.type == "dialogue":
                dialogue.append(
                    SceneScriptDialogueLine(
                        character_name=id_to_name.get(ln.speaker, ln.speaker),
                        text=ln.text,
                        target_name=id_to_name.get(ln.target, ln.target) if ln.target else "",
                        quote_id=ln.quote_id,  # 史实溯源审计透传(§1.3)
                        dramatized=ln.dramatized,
                    )
                )
            elif ln.text:
                narration_bits.append(ln.text)

        # narrative_text = 视觉描述 + 走位 + 旁白(动作+摄像机一体)
        parts: list[str] = []
        if shot.visual_prompt:
            parts.append(shot.visual_prompt)
        if shot.blocking:
            parts.append("走位:" + ";".join(shot.blocking))
        parts.extend(narration_bits)
        narrative_text = "。".join(p.strip("。") for p in parts if p.strip())

        segs = segments_by_scene.setdefault(scene_ref, [])
        segs.append(
            SceneScriptSegment(
                segment_id=f"sg{len(segs) + 1:03d}",
                order=len(segs) + 1,
                t_start_s=shot.t_start_ms / 1000.0,
                t_end_s=shot.t_end_ms / 1000.0,
                narrative_text=narrative_text,
                dialogue=dialogue,
                camera_movement=_map_camera(
                    shot.camera.movement, is_first_shot_in_scene=(len(segs) == 0)
                ),
                beat_description="；".join(shot.action_beats) if shot.action_beats else "",
            )
        )
        # 场次在场人物(character_id → name,去重保序)
        present = chars_by_scene.setdefault(scene_ref, [])
        for cid in shot.characters:
            nm = id_to_name.get(cid, cid)
            if nm not in present:
                present.append(nm)

    scripts = [
        SceneScript(
            scene_ref=ref,
            characters_present=chars_by_scene.get(ref, []),
            segments=segs,
            total_duration_s=(segs[-1].t_end_s if segs else 0.0),
        )
        for ref, segs in sorted(segments_by_scene.items())
    ]
    return SceneScriptSet(scripts=scripts)


def build_v2_design_list(*, character_bible: Any) -> DesignList:
    """tongjian `CharacterBible` → V2 `DesignList.characters`(SPEC-005-V2 §1.4)。确定性纯函数。

    `era_check`(tongjian L5 时代校验)并进 `appearance`——供 canon 定妆照走考据式生成(§3:
    描述必须含时代形制词)。`ref_image` 不直接用,走 V2 design-list/lock 的 qwen-image 重生成。"""
    characters: list[DesignCharacter] = []
    for c in character_bible.characters:
        appearance = c.appearance or ""
        if c.era_check:
            appearance = f"{appearance}（时代考据:{c.era_check}）" if appearance else c.era_check
        characters.append(
            DesignCharacter(
                name=c.name,
                appearance=appearance,
                voice_id=c.voice_id,
            )
        )
    return DesignList(characters=characters)


def character_id_to_name(character_bible: Any) -> dict[str, str]:
    """从 CharacterBible 建 character_id → name 映射(tongjian 用 id,V2 用 name)。"""
    return {c.character_id: c.name for c in character_bible.characters}


async def build_v2_inputs_from_tongjian(
    *,
    script: Any,
    shot_list: Any,
    character_bible: Any,
    material_text: str,
    concept: Any,
    llm: Any = None,
) -> tuple[DesignList, SceneScriptSet, Any]:
    """编排:tongjian 前端产物 → V2 三件(DesignList / SceneScriptSet / WorldBible)。

    确定性映射(design_list/scene_script)+ WorldBible 用 `generate_world_bible_draft(
    visual_style="historical")` 新生成(通鉴无 WorldBible 对应物,§1.5)——历史 directive 走
    §2.2 已接的角色卷/世界卷/visual 卷考据约束。

    **不含**:canon 定妆照生成(qwen-image)+ scene_ref_paths(空景板)+ Screenplay shim
    (produce_v2 的 `_scene_name_for` 用)——这些是真跑 harness(step 2b)的职责,不在桥接层
    (桥接只做无损映射 + world_bible;资产/文件路径是运行时关注点)。"""
    from hevi.director.world_bible import generate_world_bible_draft

    id_to_name = character_id_to_name(character_bible)
    design_list = build_v2_design_list(character_bible=character_bible)
    # drama_only=True:演绎段只渲染 drama 镜,narration 镜归讲解段(sdxl_local),不进 produce_v2 付费渲染。
    scene_script_set = build_v2_scene_script_set(
        script=script, shot_list=shot_list, id_to_name=id_to_name, drama_only=True
    )
    world_bible = await generate_world_bible_draft(
        concept=concept,
        material_text=material_text,
        design_list=design_list,
        llm=llm,
        visual_style="historical",
    )
    return design_list, scene_script_set, world_bible
