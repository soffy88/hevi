"""连续性提示词编译器 —— 跨平台防穿帮多模态提示词生成。

覆盖 BRIEF_CONT1017 规范：
- 风格定性：输出成“不是X，而是Y”
- 语言锁：“全部对白与背景人声只说普通话，禁止日语或其他语言；画面不出现文字”
- 逐字复用每个角色的完整外貌固定描述(修掉老代码共享 anchor 穿帮 bug)
- 音色卡与空间混响
- 【镜头】：景别/角度/焦段/机位/唯一运镜
- 【光线调色】：布光+调色基准
- 道具与手部占用状态
- 动作弧与动作对齐(match on action)
- 对白与口型锁定(画内画外)
- 环境声与配乐(无配乐时明确输出“无音乐”)
- 一致性条款(同脸同服装同光线同机位)
- 结束状态衔接

平台适配层：
- h3: 三段式结构与 <d>[Chinese] 对白标记
- seedance / muse: 内部秒数改写为“先…再…最后…”顺序节拍，提供约束词
- veo: 台词“说话人：台词”严禁引号；负面词放独立 negative_prompt
- runway: 严禁否定句，全部转换为肯定句表达
- generic: 标准影视镜头提示词
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from hevi.prompt.continuity.schemas import (
    CharacterCard,
    FilmBible,
    PropItem,
    PropLedger,
    SceneCard,
    ShotContract,
    ShotDialogue,
)
from hevi.prompt.continuity.vocab import get_vocab_item

logger = logging.getLogger(__name__)


@dataclass
class ContinuityRender:
    """跨平台渲染输出契约，兼容 H3Render 协议。"""

    platform: str
    prompt: str  # 画面主体 prompt (h3 平台即 integrated_multimodal_description)
    negative_prompt: str = ""
    soundscape: str = ""
    music: str = ""
    constraints: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def integrated_multimodal_description(self) -> str:
        return self.prompt

    @property
    def overall_soundscape(self) -> str:
        return self.soundscape

    @property
    def non_diegetic_music(self) -> str:
        return self.music

    def to_dict(self) -> dict[str, str]:
        if self.platform == "h3":
            return {
                "integrated_multimodal_description": self.prompt,
                "overall_soundscape": self.soundscape,
                "non_diegetic_music": self.music,
            }
        elif self.platform == "veo":
            return {
                "prompt": self.prompt,
                "negative_prompt": self.negative_prompt,
                "soundscape": self.soundscape,
                "music": self.music,
            }
        elif self.platform in ("seedance", "muse"):
            return {
                "prompt": self.prompt,
                "constraints": self.constraints,
                "soundscape": self.soundscape,
                "music": self.music,
            }
        elif self.platform == "runway":
            return {
                "prompt": self.prompt,
                "soundscape": self.soundscape,
                "music": self.music,
            }
        else:
            return {
                "prompt": self.prompt,
                "negative_prompt": self.negative_prompt,
                "soundscape": self.soundscape,
                "music": self.music,
            }


def _sanitize_for_runway(text: str) -> str:
    """将文本中的否定句表达改写为肯定句，满足 Runway 平台纯肯定句要求。

    消灭所有包含'无'、'不要'、'禁止'、'严禁'、'避免'、'没有'、'不得'的表达。
    """
    replacements = [
        ("无耳环戒指", "耳部与手指保持自然素雅"),
        ("无首饰", "周身保持素雅"),
        ("无配饰", "造型保持简约"),
        ("无方言口音", "普通话纯正发音"),
        ("无口音", "普通话纯正发音"),
        ("无字幕、无文字、无水印", "纯净画面，只呈现人物与场景"),
        ("无字幕", "纯净画面"),
        ("无文字", "纯净画面"),
        ("无水印", "纯净画面"),
        ("无杂音", "声音纯净"),
        ("无噪音", "背景平稳"),
        ("无混响", "开阔自然干声"),
        ("无手持道具冲突", "手部自然放松"),
        ("无动作", "保持静止姿态"),
        ("无对白", "画面静默"),
        ("无表情", "神态沉静"),
        ("无妆容", "素颜自然面貌"),
        ("无瑕疵", "质感细腻"),
        ("无偏色", "色彩纯正"),
        ("无突然静音或音量跳变", "声音平稳连贯"),
        ("无突然静音", "声音平稳连贯"),
        ("无音乐", "仅环境声"),
        ("不得开口", "保持双唇自然闭合"),
        ("禁止开口", "保持双唇自然闭合"),
        ("禁止日语或其他语言", "只使用清晰普通话"),
        ("禁止日语", "只使用清晰普通话"),
        ("禁止其他语言", "只使用清晰普通话"),
        ("禁止外语", "只使用清晰普通话"),
        ("禁止", "务必"),
        ("严禁", "务必"),
        ("不要", "请"),
        ("避免", "保持"),
        ("不得", "请保持"),
        ("没有", "缺少"),
    ]
    res = text
    for old, new in replacements:
        res = res.replace(old, new)
    # 替换以'无'开头的词
    res = re.sub(r"无([\u4e00-\u9fa5]{1,4})", r"素雅\1", res)
    for bad in ["无", "不要", "禁止", "严禁", "避免", "没有", "不得"]:
        if bad in res:
            res = res.replace(bad, "自然" if bad == "无" else "")
    return res


def _convert_beats_to_sequential_order(beats: list[str]) -> str:
    """将秒级时间码动作(如 0-2s/2-4s)改写为 Seedance/Muse 推荐的‘先…再…最后…’顺序节拍。"""
    cleaned: list[str] = []
    for b in beats:
        s = b.strip().rstrip("。；;.")
        if ":" in s:
            s = s.split(":", 1)[1].strip().rstrip("。；;.")
        elif "：" in s:
            s = s.split("：", 1)[1].strip().rstrip("。；;.")
        if s:
            cleaned.append(s)

    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return f"动作按序发生：{cleaned[0]}"
    if len(cleaned) == 2:
        return f"先{cleaned[0]}；再{cleaned[1]}"
    # 3项及以上
    middle = "；再".join(cleaned[1:-1])
    return f"先{cleaned[0]}；再{middle}；最后{cleaned[-1]}"


def compile_continuity_prompt(
    bible: FilmBible,
    scene: SceneCard,
    characters: list[CharacterCard] | dict[str, CharacterCard],
    props: list[PropItem] | dict[str, PropItem] | PropLedger | None,
    shot: ShotContract,
    platform: str = "generic",
) -> ContinuityRender:
    """按平台输出包含全部防穿帮要素的导演提示词。

    Args:
        bible: 整片圣经
        scene: 场景母卡
        characters: 角色母卡列表或映射表
        props: 道具状态或道具账本
        shot: 镜头契约
        platform: 目标平台 ("h3", "seedance", "muse", "veo", "runway", "generic")
    """
    platform_clean = platform.lower().strip()

    # 1. 角色映射表规范化
    char_map: dict[str, CharacterCard] = {}
    if isinstance(characters, (list, tuple)):
        for c in characters:
            char_map[c.name] = c
    elif isinstance(characters, dict):
        char_map = characters

    # 2. 道具信息规范化
    prop_map: dict[str, PropItem] = {}
    if isinstance(props, PropLedger):
        for it in props.items:
            prop_map[it.prop_name] = it
    elif isinstance(props, (list, tuple)):
        for it in props:
            prop_map[it.prop_name] = it
    elif isinstance(props, dict):
        prop_map = props

    # ── 模块 A: 风格定性 ───────────────────────────────────────────────────
    if platform_clean == "runway":
        # Runway 严禁用否定句
        is_items = bible.style_is or ["电影质感现实主义叙事短片"]
        style_block = f"【风格定性】{'、'.join(is_items)}，保持院线级专业摄影质感与真实写实质地。"
    else:
        # 其他平台支持“不是X，而是Y”
        style_block = f"【{bible.format_style_qualification()}】"

    # ── 模块 B: 语言锁 ─────────────────────────────────────────────────────
    if platform_clean == "runway":
        language_lock_block = (
            "【语言与画面要求】全部对话与背景人声严格保持普通话清晰发声；"
            "画面构图纯净，只呈现人物与场景，保持纯净电影质感画面。"
        )
    else:
        language_lock_block = (
            f"【语言锁】{bible.language_lock or '全部对白与背景人声只说普通话，禁止日语或其他语言；画面不出现文字'}。"
        )

    # ── 模块 C: 场景固定描述与空间站位 ───────────────────────────────────
    scene_parts: list[str] = [f"【场景】{scene.scene_name}"]
    if scene.description:
        scene_parts.append(f"描述:{scene.description}")
    if scene.top_down_blocking:
        scene_parts.append(f"站位空间坐标:{scene.top_down_blocking}")
    if scene.axis:
        scene_parts.append(f"轴线约定:{scene.axis}")
    if scene.reverse_angle_background:
        scene_parts.append(f"反打背景事实:{scene.reverse_angle_background}")
    scene_block = "；".join(scene_parts) + "。"

    # ── 模块 D: 角色逐字固定描述与音色卡 ─────────────────────────────────
    char_blocks: list[str] = []
    voice_blocks: list[str] = []
    for cname in shot.character_names:
        char = char_map.get(cname)
        if char:
            desc = char.get_full_description(story_day=shot.story_day)
            if platform_clean == "runway":
                desc = _sanitize_for_runway(desc)
            char_blocks.append(f"【人物】S{char.s_no} {char.name}（完整外貌固定描述）：{desc}")
            if char.voice_card:
                sc_rev = getattr(scene, "reverb", "") or ""
                if platform_clean == "runway" and sc_rev:
                    sc_rev = _sanitize_for_runway(sc_rev)
                v_text = char.voice_card.to_prompt_text(scene_reverb=sc_rev)
                if platform_clean == "runway":
                    v_text = _sanitize_for_runway(v_text)
                voice_blocks.append(f"【音色卡】{char.name}：{v_text}")
        else:
            char_blocks.append(f"【人物】{cname}（未绑定母卡，保持既往外观一致）")

    # ── 模块 E: 镜头语言 (景别/角度/焦段/机位/唯一运镜) ────────────────────
    camera_parts: list[str] = []
    if shot.shot_type:
        st_item = get_vocab_item(shot.shot_type)
        st_desc = st_item.prompt_hint_zh if st_item else shot.shot_type
        camera_parts.append(f"景别:{shot.shot_type}({st_desc})")
    if shot.camera_move:
        cm_item = get_vocab_item(shot.camera_move)
        cm_desc = cm_item.prompt_hint_zh if cm_item else shot.camera_move
        camera_parts.append(f"唯一运镜:{shot.camera_move}({cm_desc})")
    if shot.composition:
        comp_item = get_vocab_item(shot.composition)
        comp_desc = comp_item.prompt_hint_zh if comp_item else shot.composition
        camera_parts.append(f"构图法则:{shot.composition}({comp_desc})")
    if scene.lens:
        camera_parts.append(f"机位与镜头:{scene.lens}")
    if shot.eyeline_angle:
        camera_parts.append(f"视线角度:{shot.eyeline_angle}")
    if shot.in_out_direction:
        camera_parts.append(f"出入画:{shot.in_out_direction}")
    camera_block = "【镜头】" + ("；".join(camera_parts) if camera_parts else "标准视平固定镜头") + "。"

    # ── 模块 F: 光线与调色 ─────────────────────────────────────────────────
    lighting_parts: list[str] = []
    if scene.lighting:
        lighting_parts.append(f"布光方案:{scene.lighting}")
    if bible.color_grading_baseline:
        lighting_parts.append(f"调色基准:{bible.color_grading_baseline}")
    lighting_block = (
        "【光线调色】" + ("；".join(lighting_parts) if lighting_parts else "自然光影平稳") + "。"
    )

    # ── 模块 G: 道具与手部状态 ─────────────────────────────────────────────
    prop_parts: list[str] = []
    for pname in shot.prop_names:
        p_item = prop_map.get(pname)
        if p_item:
            inner_parts = []
            if p_item.holder and p_item.holder != "无":
                inner_parts.append(f"持有人:{p_item.holder}")
            if p_item.placement:
                inner_parts.append(f"位置:{p_item.placement}")
            if p_item.start_state:
                inner_parts.append(f"状态:{p_item.start_state}")
            if p_item.liquid_level:
                inner_parts.append(f"液位:{p_item.liquid_level}")
            detail = f"{p_item.prop_name}({'，'.join(inner_parts)})" if inner_parts else p_item.prop_name
            prop_parts.append(detail)
        else:
            prop_parts.append(pname)
    if shot.hands_occupation:
        hands_desc = "，".join(f"{k}:{v}" for k, v in shot.hands_occupation.items())
        prop_parts.append(f"手部占用状态:[{hands_desc}]")
    if prop_parts:
        prop_block = "【道具与手部】" + "；".join(prop_parts) + "。"
    else:
        if platform_clean == "runway":
            prop_block = "【道具与手部】双手自然垂放，肢体姿态放松舒展。"
        else:
            prop_block = "【道具与手部】双手自然下垂无手持道具冲突。"

    # ── 模块 H: 动作与节拍 ─────────────────────────────────────────────────
    action_content: list[str] = []
    if shot.second_beats:
        if platform_clean in ("seedance", "muse"):
            # Seedance/Muse 改写为顺序节拍
            seq_action = _convert_beats_to_sequential_order(shot.second_beats)
            if seq_action:
                action_content.append(seq_action)
        else:
            cleaned_beats = [b.strip().rstrip("。；;.") for b in shot.second_beats if b.strip()]
            action_content.append("节拍计划：" + "；".join(cleaned_beats))
    if shot.action:
        action_content.append(shot.action.strip().rstrip("。；;."))
    elif shot.visual_prompt:
        action_content.append(shot.visual_prompt.strip().rstrip("。；;."))
    if shot.match_on_action:
        action_content.append(f"动作剪辑衔接点:{shot.match_on_action.strip().rstrip('。；;.')}")

    if action_content:
        action_block = "【动作】" + "；".join(action_content) + "。"
    else:
        action_block = "【动作】人物自然动态。"

    # ── 模块 I: 对白与口型 ─────────────────────────────────────────────────
    dialogue_block = ""
    target_dialogue: ShotDialogue | None = shot.dialogue
    if not target_dialogue and shot.dialogue_lines:
        target_dialogue = shot.dialogue_lines[0]

    if target_dialogue and target_dialogue.text:
        speaker = target_dialogue.speaker or "角色"
        char_obj = char_map.get(speaker)
        s_no = char_obj.s_no if char_obj else 1
        text = target_dialogue.text.strip()
        quote_mark = f"[q:{target_dialogue.quote_id}]" if target_dialogue.quote_id else ""
        in_out_tag = "画内口型对齐" if target_dialogue.is_in_frame else (
            "画外音(画面人物保持静默闭合双唇)" if platform_clean == "runway" else "画外音(画面人物不得开口)"
        )
        sync_tag = "口型锁定" if target_dialogue.lip_sync_locked else "非强锁定"

        if platform_clean == "h3":
            dialogue_block = (
                f"【对白】\n（S{s_no}）{speaker}说道：\n"
                f"<d>[Chinese] {text}</d>{quote_mark}\n"
                f"（标记:{in_out_tag}，{sync_tag}）"
            )
        elif platform_clean == "veo":
            # Veo 规则：冒号后严禁引号
            dialogue_block = f"【对白】{speaker}：{text}（{in_out_tag}，{sync_tag}）"
        elif platform_clean == "runway":
            dialogue_block = f"【对白】{speaker}发声说道：“{text}”（{in_out_tag}）"
        else:
            dialogue_block = f"【对白】（S{s_no}）{speaker}说道：“{text}”{quote_mark}（{in_out_tag}，{sync_tag}）"

    # ── 模块 J: 情绪刻度 ─────────────────────────────────────────────────
    emotion_block = f"【表演情绪刻度】{shot.emotion_scale}。" if shot.emotion_scale else ""

    # ── 模块 K: 一致性条款 ─────────────────────────────────────────────────
    if platform_clean == "runway":
        consistency_block = (
            "【一致性保障】画面角色严格保持同一面孔、同一发型、同一套服装配饰；"
            "光线色温、机位轴线保持稳定一致，肢体结构解剖学严密自然。"
        )
    else:
        consistency_block = (
            "【一致性条款】同脸同服装同光线同机位；"
            "严禁面部五官漂移、发型突变、服装配饰跳变或肢体畸变穿模。"
        )

    # ── 模块 L: 结束状态与转场衔接 ─────────────────────────────────────────
    trans_parts: list[str] = []
    if shot.end_state:
        end_desc = (
            str(shot.end_state)
            if isinstance(shot.end_state, str)
            else "，".join(f"{k}:{v}" for k, v in shot.end_state.items())
        )
        trans_parts.append(f"本镜尾帧状态:[{end_desc}]")
    if shot.transition_out:
        trans_parts.append(f"出镜转场衔接:{shot.transition_out}")
    trans_block = "【衔接状态】" + ("；".join(trans_parts) if trans_parts else "平缓接续下一镜") + "。"

    # ── 组合主 Prompt ──────────────────────────────────────────────────────
    main_sections = [
        style_block,
        language_lock_block,
        scene_block,
        *char_blocks,
        *voice_blocks,
        camera_block,
        lighting_block,
        prop_block,
        action_block,
    ]
    if dialogue_block:
        main_sections.append(dialogue_block)
    if emotion_block:
        main_sections.append(emotion_block)
    main_sections.extend([consistency_block, trans_block])

    prompt_integrated = "\n".join(s for s in main_sections if s)

    # ── 声音与配乐 (关键要求：无音乐明确输出“无音乐”) ─────────────────────
    soundscape = scene.ambient_noise or "环境底噪连续稳定，无突然静音"
    music = (
        scene.music_policy
        if (scene.music_policy and scene.music_policy.strip() != "")
        else "无音乐"
    )

    if platform_clean == "runway":
        prompt_integrated = _sanitize_for_runway(prompt_integrated)
        soundscape = _sanitize_for_runway(soundscape)
        if music == "无音乐":
            music = "仅环境声"
        else:
            music = _sanitize_for_runway(music)

    # ── 负面与约束处理 ─────────────────────────────────────────────────────
    negative_prompt = ""
    constraints = ""

    if platform_clean == "veo":
        # Veo 负面词放独立字段
        neg_items = [
            "subtitles",
            "japanese subtitles",
            "foreign text",
            "text",
            "watermark",
            "blurry",
            "distorted faces",
            "extra fingers",
            "mutated hands",
            "missing limbs",
            "clothing shift",
            "lighting shift",
        ]
        if shot.negatives:
            neg_items.extend(shot.negatives)
        negative_prompt = ", ".join(neg_items)
    elif platform_clean in ("seedance", "muse"):
        # Seedance / Muse 约束词
        constraints = (
            "keep it subtitle-free, keep characters physically consistent, "
            "keep background stable, no japanese text, locked facial identity"
        )
    elif platform_clean == "generic":
        negative_prompt = (
            "字幕, 乱码, 水印, 日语, 穿模, 崩手, 面部变形, 服装跳变, 光线跳变"
        )

    return ContinuityRender(
        platform=platform_clean,
        prompt=prompt_integrated,
        negative_prompt=negative_prompt,
        soundscape=soundscape,
        music=music,
        constraints=constraints,
        metadata={
            "shot_id": shot.shot_id,
            "scene_name": shot.scene_name,
            "duration_s": shot.duration_s,
        },
    )
