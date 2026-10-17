"""首帧图提示词编译器、资产参考图与编辑扩图模板 (FF-1017)。

实现 BRIEF_FF1017 规范：
1. compile_first_frame(shot, bible, scene, characters, props, platform):
   - 英文提示词，顺序：主体 → 外观/动作起始姿态 → 环境 → 光线 → 画面形式与构图(景别/机位/焦段/留白)
   - 角色外貌/服装从母卡逐字复用(appearance_fixed_en / appearance_fixed)
   - 画面状态 = 该镜 0 秒状态(站位、朝向、道具在谁手里哪只手，取自道具账本与上镜交接)
   - 拒绝"高级感、绝美、masterpiece"等空词，采用写实摄影与明确画幅
   - midjourney: 末尾参数 `--ar W:H --v 8.2 --raw --s 75 --c 0 --sd`，可选 `--seed`, `--p`, `--sref`, `--sw`, `--iw`
   - generic / chatgpt_image: 自然语言版，不带 `--` 参数，画幅写成文字
   - 输出首帧规划要求并支持严格校验
2. compile_end_frame: 尾帧提示词(该镜结束状态)
3. compile_asset_refs: 为角色/关键场景/关键道具输出定妆参考图提示词及 Midjourney 入口说明
   (Attach to prompt 保人物/物体; Style Reference 借画风; Image Prompts 借构图)
4. build_local_edit_prompt & build_outpaint_prompt: 局部修改与扩图提示词模板及操作指南
5. validate_first_frame: 10 项严格首帧防穿帮校验器
"""

from __future__ import annotations

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
)


@dataclass
class FirstFrameResult:
    """首帧编译结果对象。"""

    shot_id: str
    platform: str
    prompt: str
    aspect_ratio: str
    requirements: list[str]
    end_frame_prompt: str = ""
    edit_templates: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.prompt


@dataclass
class AssetRefSpec:
    """资产定妆参考图契约。"""

    asset_id: str
    name: str
    category: str  # character / scene / prop
    prompt: str
    entry_slot: str  # Attach to prompt / Style Reference / Image Prompts
    instructions: str

    def to_dict(self) -> dict[str, str]:
        return {
            "asset_id": self.asset_id,
            "name": self.name,
            "category": self.category,
            "prompt": self.prompt,
            "entry_slot": self.entry_slot,
            "instructions": self.instructions,
        }


# ── 首帧规划标准规则 ─────────────────────────────────────────────────────────

FIRST_FRAME_REQUIREMENTS = [
    "身体与空间：动作所需身体部位与活动空间必须全部在画内；位移动作（如起身、走动、推轮椅等）必须全身或中景留出移动方向空间；仅微笑/眨眼等微表情允许肩部以上。",
    "细节与防粘连：面部五官与双手结构清晰可辨，物体与人体边界明确，严禁肢体形变或物体粘连穿模。",
    "构图与留白：主体头顶（Headroom）与画面边缘保留安全缓冲留白，防止图生视频推拉运镜时关键特征被裁切。",
    "文字白名单：画内文字严格仅限白名单，默认纯净无文字（'no text'）。",
]

# 全身/位移动作关键词（需留出全身或活动空间）
WHOLE_BODY_ACTION_KEYWORDS = [
    "起身", "站起", "起立", "走动", "走", "跑步", "跑", "推轮椅", "推车",
    "踱步", "跨步", "下蹲", "跪下", "跳", "奔跑", "漫步", "穿行",
    "stand up", "get up", "walk", "walking", "run", "running",
    "push wheelchair", "pushing wheelchair", "push cart", "pace",
    "kneel", "jump", "stride",
]

# 特写/肩部以上景别关键词
CLOSEUP_FRAMING_KEYWORDS = [
    "特写", "大特写", "微距", "肩部以上", "胸部以上", "特写镜头", "头部特写",
    "close-up", "extreme close-up", "medium close-up",
    "head-and-shoulders", "head and shoulders", "bust shot", "ecu", "cu", "mcu",
]


def _normalize_mapping(
    items: list[Any] | dict[str, Any] | None, key_fn
) -> dict[str, Any]:
    if not items:
        return {}
    if isinstance(items, dict):
        return items
    return {key_fn(it): it for it in items}


# ── 1. 首帧图提示词编译 ───────────────────────────────────────────────────────


def compile_first_frame(
    shot: ShotContract,
    bible: FilmBible,
    scene: SceneCard | None = None,
    characters: list[CharacterCard] | dict[str, CharacterCard] | None = None,
    props: PropLedger | list[PropItem] | dict[str, PropItem] | None = None,
    platform: str = "midjourney",
) -> FirstFrameResult:
    """编译镜头首帧图提示词（支持 midjourney, generic, chatgpt_image）。

    提示词结构顺序：
      主体 → 外观/动作起始姿态 → 环境 → 光线 → 画面形式与构图（景别、机位、焦段、留白）
    """
    char_map = _normalize_mapping(characters, lambda c: c.name)
    prop_map: dict[str, PropItem] = {}
    if isinstance(props, PropLedger):
        prop_map = {p.prop_name: p for p in props.items}
    elif isinstance(props, (list, tuple)):
        prop_map = {p.prop_name: p for p in props}
    elif isinstance(props, dict):
        prop_map = props

    target_ar = bible.aspect_ratio or "16:9"
    platform_clean = (platform or "midjourney").lower().strip()

    # 1. 主体与外观（卡片逐字复用）
    subject_parts: list[str] = []
    for cname in shot.character_names:
        char_card = char_map.get(cname)
        if char_card:
            # 优先使用英文外貌固定描述，保持与卡片逐字一致
            desc = char_card.appearance_fixed_en.strip() or char_card.appearance_fixed.strip()
            subject_parts.append(desc)
        else:
            subject_parts.append(cname)

    # 2. 0 秒起始姿态、站位与手部道具（取自 start_state 与道具账本）
    pose_parts: list[str] = []
    # 站位与起始动作
    start_state_text = (
        shot.start_state_en.strip()
        or (str(shot.start_state) if isinstance(shot.start_state, str) else "")
    )
    if start_state_text:
        pose_parts.append(start_state_text)

    # 道具 0 秒状态
    for pname in shot.prop_names:
        p_item = prop_map.get(pname)
        if p_item:
            holder = p_item.holder or ""
            placement = p_item.placement_en or p_item.placement or ""
            state = p_item.start_state_en or p_item.start_state or ""
            p_desc = f"{p_item.prop_name_en or p_item.prop_name}"
            if placement:
                p_desc += f" {placement}"
            if state:
                p_desc += f", {state}"
            if p_desc not in pose_parts:
                pose_parts.append(p_desc)

    # 手部占用
    if shot.hands_occupation and not pose_parts:
        hands_desc = ", ".join(f"{k} {v}" for k, v in shot.hands_occupation.items())
        pose_parts.append(f"hands: {hands_desc}")

    # 3. 环境描述（来自 SceneCard）
    env_desc = ""
    if scene:
        env_desc = scene.description_en.strip() or scene.description.strip()

    # 4. 光线与影调（来自 SceneCard）
    light_desc = ""
    if scene:
        light_desc = scene.lighting_en.strip() or scene.lighting.strip()

    # 5. 画面形式与构图（景别、机位、焦段、留白）
    comp_parts: list[str] = []
    shot_type = shot.shot_type_en.strip() or shot.shot_type.strip()
    if shot_type:
        comp_parts.append(f"{shot_type} framing")
    else:
        comp_parts.append("cinematic framing")

    if shot.composition_en:
        comp_parts.append(shot.composition_en.strip())
    elif shot.composition:
        comp_parts.append(shot.composition.strip())

    comp_parts.append("eye-level camera angle, 50mm lens, shallow depth of field")
    comp_parts.append("centered composition, ample headroom above the head, balanced negative space around the edges")
    comp_parts.append("realistic cinematic still photography, natural skin texture, movie color grading")

    # 画内文字控制
    if shot.on_screen_text:
        allowed = [t for t in shot.on_screen_text if t in (bible.text_whitelist or [])]
        if allowed:
            comp_parts.append(f"on-screen text: '{', '.join(allowed)}'")
        else:
            comp_parts.append("clean background, no on-screen text, no watermark")
    else:
        comp_parts.append("clean background, no on-screen text, no watermark")

    # 组合自然语言主体内容
    content_blocks: list[str] = []
    if subject_parts:
        content_blocks.append(", ".join(subject_parts))
    if pose_parts:
        content_blocks.append(", ".join(pose_parts))
    if env_desc:
        content_blocks.append(f"set in {env_desc}")
    if light_desc:
        content_blocks.append(f"lit by {light_desc}")
    if comp_parts:
        content_blocks.append(", ".join(comp_parts))

    body_content = ", ".join(s.strip() for s in content_blocks if s.strip())

    # 6. 平台专属适配与参数组装
    if platform_clean == "midjourney":
        # Midjourney V8.x 网页端参数
        params: list[str] = [
            f"--ar {target_ar}",
            f"--v {bible.mj_version or '8.2'}",
            "--raw",
            f"--s {bible.mj_stylize if bible.mj_stylize is not None else 75}",
            f"--c {bible.mj_chaos if bible.mj_chaos is not None else 0}",
            "--sd",
        ]
        if bible.seed is not None:
            params.append(f"--seed {bible.seed}")

        # --p 与 --sref 互斥
        if bible.personalization:
            params.append(f"--p {bible.personalization}")
            # 情绪板不得出 --sw/--sv
            if not bible.is_moodboard and not bible.personalization.startswith("m"):
                if bible.style_weight is not None:
                    params.append(f"--sw {bible.style_weight}")
        elif bible.style_ref:
            params.append(f"--sref {bible.style_ref}")
            if bible.style_weight is not None:
                params.append(f"--sw {bible.style_weight}")

        if bible.image_weight is not None:
            params.append(f"--iw {bible.image_weight}")

        final_prompt = f"{body_content} {' '.join(params)}"

    elif platform_clean == "chatgpt_image":
        # ChatGPT Image / DALL-E 自然语言版
        final_prompt = (
            f"Create a realistic cinematic still photograph in {target_ar} aspect ratio. "
            f"{body_content}. Authentic skin textures, high dynamic range, no text, no watermarks."
        )

    else:
        # 通用自然语言版 (generic)
        final_prompt = (
            f"Cinematic film still, {target_ar} aspect ratio: {body_content}. "
            "Natural photographic lighting, film grain, realistic physical details."
        )

    # 7. 尾帧提示词（可选）
    end_frame_prompt = compile_end_frame(
        shot=shot,
        bible=bible,
        scene=scene,
        characters=characters,
        props=props,
        platform=platform_clean,
    )

    # 8. 编辑与扩图模板
    first_char_name = shot.character_names[0] if shot.character_names else "subject"
    edit_templates = {
        "local_edit": build_local_edit_prompt(
            change_from=f"{first_char_name}'s clothing",
            change_to="target costume",
        ),
        "outpaint": build_outpaint_prompt(
            scene_background=env_desc or "environment background",
            subject=first_char_name,
            target_ar=target_ar,
        ),
    }

    return FirstFrameResult(
        shot_id=shot.shot_id,
        platform=platform_clean,
        prompt=final_prompt,
        aspect_ratio=target_ar,
        requirements=FIRST_FRAME_REQUIREMENTS,
        end_frame_prompt=end_frame_prompt,
        edit_templates=edit_templates,
        metadata={
            "character_count": len(shot.character_names),
            "prop_count": len(shot.prop_names),
            "duration_s": shot.duration_s,
        },
    )


def compile_end_frame(
    shot: ShotContract,
    bible: FilmBible,
    scene: SceneCard | None = None,
    characters: list[CharacterCard] | dict[str, CharacterCard] | None = None,
    props: PropLedger | list[PropItem] | dict[str, PropItem] | None = None,
    platform: str = "midjourney",
) -> str:
    """编译镜头尾帧图提示词（该镜结束时刻状态，用于首尾帧模型或下镜衔接）。"""
    char_map = _normalize_mapping(characters, lambda c: c.name)
    prop_map: dict[str, PropItem] = {}
    if isinstance(props, PropLedger):
        prop_map = {p.prop_name: p for p in props.items}
    elif isinstance(props, (list, tuple)):
        prop_map = {p.prop_name: p for p in props}
    elif isinstance(props, dict):
        prop_map = props

    target_ar = bible.aspect_ratio or "16:9"
    platform_clean = (platform or "midjourney").lower().strip()

    subject_parts: list[str] = []
    for cname in shot.character_names:
        char_card = char_map.get(cname)
        if char_card:
            desc = char_card.appearance_fixed_en.strip() or char_card.appearance_fixed.strip()
            subject_parts.append(desc)
        else:
            subject_parts.append(cname)

    # 结束状态姿势
    pose_parts: list[str] = []
    end_state_text = (
        shot.end_state_en.strip()
        or (str(shot.end_state) if isinstance(shot.end_state, str) else "")
    )
    if end_state_text:
        pose_parts.append(f"ending pose: {end_state_text}")

    # 结束时道具状态
    for pname in shot.prop_names:
        p_item = prop_map.get(pname)
        if p_item and (p_item.end_state_en or p_item.end_state):
            pose_parts.append(
                f"{p_item.prop_name_en or p_item.prop_name}: {p_item.end_state_en or p_item.end_state}"
            )

    env_desc = scene.description_en.strip() or scene.description.strip() if scene else ""
    light_desc = scene.lighting_en.strip() or scene.lighting.strip() if scene else ""

    content_blocks = [
        ", ".join(subject_parts),
        ", ".join(pose_parts) if pose_parts else "final settled pose at cut point",
        f"set in {env_desc}" if env_desc else "",
        f"lit by {light_desc}" if light_desc else "",
        "settled cinematic composition, space around the subject, clean background, no text",
    ]
    body = ", ".join(s for s in content_blocks if s)

    if platform_clean == "midjourney":
        return f"{body} --ar {target_ar} --v {bible.mj_version or '8.2'} --raw --s 75 --c 0 --sd"
    elif platform_clean == "chatgpt_image":
        return f"Create a realistic cinematic end-frame still in {target_ar} aspect ratio. {body}. No text, no watermarks."
    else:
        return f"Cinematic film end-frame still, {target_ar} aspect ratio: {body}."


# ── 2. 资产定妆参考图编译 ─────────────────────────────────────────────────────


def compile_asset_refs(
    bible: FilmBible,
    characters: list[CharacterCard] | dict[str, CharacterCard] | None = None,
    scenes: list[SceneCard] | dict[str, SceneCard] | None = None,
    props: PropLedger | list[PropItem] | dict[str, PropItem] | None = None,
) -> list[AssetRefSpec]:
    """为每个角色、关键场景和关键道具生成定妆参考图提示词，并标明 Midjourney 入口。"""
    specs: list[AssetRefSpec] = []
    char_list = list(characters.values()) if isinstance(characters, dict) else (characters or [])
    scene_list = list(scenes.values()) if isinstance(scenes, dict) else (scenes or [])

    prop_list: list[PropItem] = []
    if isinstance(props, PropLedger):
        prop_list = props.items
    elif isinstance(props, dict):
        prop_list = list(props.values())
    elif isinstance(props, list):
        prop_list = props

    # 1. 角色定妆图 (Attach to prompt，保人物)
    for c in char_list:
        c_name = c.name_en or c.name
        c_app = c.appearance_fixed_en.strip() or c.appearance_fixed.strip()
        prompt = (
            f"Studio character reference portrait of {c_name}, {c_app}. "
            "Frontal full-body and medium shot, neutral light-gray studio background, "
            "even clean commercial lighting, realistic skin texture, centered eye-level composition, "
            "space around head and body --ar 1:1 --v 8.2 --raw --s 75 --c 0 --sd"
        )
        instructions = (
            "Midjourney V8.x 入口：【Attach to prompt】（人物/物体参考并入 Edit Model，保人物面容与服装；"
            "写改什么留什么）。注：只借画风才用【Style Reference】（--sref，会换人）；借构图用【Image Prompts】。"
        )
        specs.append(
            AssetRefSpec(
                asset_id=f"REF-CHAR-{c.s_no}-{c.name}",
                name=c.name,
                category="character",
                prompt=prompt,
                entry_slot="Attach to prompt",
                instructions=instructions,
            )
        )

    # 2. 关键场景空镜参考 (Image Prompts / Attach to prompt)
    for idx, s in enumerate(scene_list):
        s_desc = s.description_en.strip() or s.description.strip()
        prompt = (
            f"Cinematic architectural establishing shot of {s.scene_name}, {s_desc}. "
            f"Wide establishing shot, empty scene without people, authentic environment lighting, "
            f"realistic textures --ar {bible.aspect_ratio or '16:9'} --v 8.2 --raw --s 75 --c 0 --sd"
        )
        instructions = (
            "Midjourney 入口：【Image Prompts】（借空间透视、环境构图与景深层次）"
            "或【Attach to prompt】作为场景底图。"
        )
        specs.append(
            AssetRefSpec(
                asset_id=f"REF-SCENE-{idx+1}-{s.scene_name}",
                name=s.scene_name,
                category="scene",
                prompt=prompt,
                entry_slot="Image Prompts",
                instructions=instructions,
            )
        )

    # 3. 关键道具特写参考 (Attach to prompt，保物体)
    for idx, p in enumerate(prop_list):
        p_name = p.prop_name_en or p.prop_name
        p_state = p.start_state_en or p.start_state or "standard condition"
        prompt = (
            f"Product commercial photography of {p_name}, {p_state}. "
            "Neutral light-gray studio background, crisp focus, clean soft studio lighting, "
            "realistic material texture --ar 1:1 --v 8.2 --raw --s 75 --c 0 --sd"
        )
        instructions = (
            "Midjourney 入口：【Attach to prompt】（物体参考，保持后续各镜头道具外形与材质物理一致）。"
        )
        specs.append(
            AssetRefSpec(
                asset_id=f"REF-PROP-{idx+1}-{p.prop_name}",
                name=p.prop_name,
                category="prop",
                prompt=prompt,
                entry_slot="Attach to prompt",
                instructions=instructions,
            )
        )

    return specs


# ── 3. 编辑与扩图提示词模板 ───────────────────────────────────────────────────


def build_local_edit_prompt(
    change_from: str,
    change_to: str,
    keep_elements: str = "face, hair, pose, light and background",
) -> dict[str, str]:
    """局部修改提示词模板与操作指导（每轮只改一件事）。"""
    prompt = f"Change only {change_from} to {change_to}. Keep the same {keep_elements}."
    instructions = (
        "Midjourney 操作指南：点击图下方 Edit → Quick Edit 或 Open Editor → "
        "使用 Paint 涂抹需要修改的局部区域（棋盘格为重绘区）→ "
        "输入上述提示词提交。规则：每轮只改一个主要要求，偏了就回原图重来，切勿在偏离结果上叠加修改。"
    )
    return {"prompt": prompt, "instructions": instructions}


def build_outpaint_prompt(
    scene_background: str,
    subject: str = "subject",
    lighting: str = "lighting",
    directions: str = "above and below",
    target_ar: str = "16:9",
) -> dict[str, str]:
    """扩图/改画幅提示词模板与操作指导（用于首帧画幅与视频画幅不一致时）。"""
    prompt = (
        f"Extend the existing {scene_background} {directions}. "
        f"Keep the existing {subject} unchanged, coherent {lighting}."
    )
    instructions = (
        f"Midjourney 扩图/改画幅操作指南：首帧画幅与视频画幅不一致时，"
        f"进入 Open Editor → Move/resize → 选择目标比例 ({target_ar}) → "
        f"Scale 缩小原图留出外扩透明区域（棋盘格区域为生成区）→ 粘贴上述提示词提交生成。"
    )
    return {"prompt": prompt, "instructions": instructions}


# ── 4. 首帧防穿帮校验器 (10 项检查) ──────────────────────────────────────────


def validate_first_frame(
    shot: ShotContract,
    bible: FilmBible,
    prompt_text: str,
    props: PropLedger | list[PropItem] | dict[str, PropItem] | None = None,
    characters: list[CharacterCard] | dict[str, CharacterCard] | None = None,
) -> list[str]:
    """校验单个镜头的首帧图提示词是否符合视频生成规范，返回错误列表。

    严格覆盖 BRIEF_FF1017 的 10 大校验项：
    1. 首帧 --ar 与视频画幅不符
    2. --ar 重复出现
    3. 中文破折号/全角横线当参数
    4. 出现 /imagine (网页端禁止)
    5. --p 与 --sref 混写
    6. 情绪板 (moodboard) 配 --sw/--sv
    7. 动作需要全身但首帧是特写/肩部以上
    8. 首帧道具状态与道具账本 0 秒状态不符
    9. 角色描述未逐字复用母卡完整描述
    10. 包含未在白名单中的文字
    """
    errors: list[str] = []
    sid = shot.shot_id or "Shot"
    pt = prompt_text.strip()

    # 规范化映射
    char_map = _normalize_mapping(characters, lambda c: c.name)
    prop_map: dict[str, PropItem] = {}
    if isinstance(props, PropLedger):
        prop_map = {p.prop_name: p for p in props.items}
    elif isinstance(props, (list, tuple)):
        prop_map = {p.prop_name: p for p in props}
    elif isinstance(props, dict):
        prop_map = props

    # ── 检查 4: 出现 /imagine ────────────────────────────────────────────
    if re.search(r"/imagine\b", pt, re.I):
        errors.append(
            f"[{sid}] 首帧提示词中出现 '/imagine'。Midjourney 网页端禁止写 '/imagine'（仅 Discord 命令格式需要）。"
        )

    # ── 检查 3: 中文破折号/全角横线当参数 ─────────────────────────────────
    bad_dash_match = re.search(
        r"[—–―—\uff0d]{1,2}(ar|v|raw|s|c|sd|seed|p|sref|sw|iw|sv)\b", pt
    )
    if bad_dash_match or re.search(r"\s+[—–―—\uff0d]{1,2}[a-zA-Z]", pt):
        matched_str = bad_dash_match.group(0) if bad_dash_match else "全角破折号"
        errors.append(
            f"[{sid}] 参数使用了中文破折号或全角符号 ('{matched_str}')。必须使用半角英文破折号 '--'。"
        )

    # ── 检查 2: --ar 重复出现 ─────────────────────────────────────────────
    ar_occurrences = re.findall(r"--ar\b", pt)
    if len(ar_occurrences) > 1:
        errors.append(
            f"[{sid}] 首帧参数中 --ar 重复出现 ({len(ar_occurrences)} 次)，必须只出现一次。"
        )

    # ── 检查 1: 首帧 --ar 与视频画幅不符 ───────────────────────────────────
    # 提取 prompt 中的 --ar 值
    ar_match = re.search(r"--ar\s+([0-9]+:[0-9]+|\d+(?:\.\d+)?:\d+(?:\.\d+)?)", pt)
    expected_ar = (bible.aspect_ratio or "16:9").strip()
    if ar_match:
        found_ar = ar_match.group(1).strip()
        if found_ar != expected_ar:
            errors.append(
                f"[{sid}] 首帧 --ar '{found_ar}' 与视频画幅 '{expected_ar}' 不符。首帧画幅必须与视频画幅完全一致。"
            )
    else:
        # 如果是 midjourney platform 却没写 --ar
        if "--v" in pt or "--raw" in pt or "--s " in pt:
            errors.append(
                f"[{sid}] Midjourney 首帧参数中缺少 --ar 参数，必须指定 --ar {expected_ar}。"
            )

    # ── 检查 5: --p 与 --sref 混写 ────────────────────────────────────────
    has_p = bool(re.search(r"--p\s+\S+", pt))
    has_sref = bool(re.search(r"--sref\s+\S+", pt))
    if has_p and has_sref:
        errors.append(
            f"[{sid}] --p (个性化配置) 与 --sref (风格参考) 混写。二者不可同时出现（做基准对比关 P，借画风用 sref）。"
        )

    # ── 检查 6: 情绪板配 --sw / --sv ──────────────────────────────────────
    # 情绪板判断：--p 后面以 m 开头，或显式标记为 moodboard
    p_match = re.search(r"--p\s+([a-zA-Z0-9_\-]+)", pt)
    is_moodboard = bible.is_moodboard
    if p_match:
        p_val = p_match.group(1)
        if p_val.startswith("m") or "moodboard" in p_val.lower():
            is_moodboard = True

    if is_moodboard and (re.search(r"--sw\s+\d+", pt) or re.search(r"--sv\s+\d+", pt)):
        errors.append(
            f"[{sid}] 情绪板 (moodboard '--p') 不得搭配 --sw 或 --sv 参数（情绪板无法调控风格强度/版本）。"
        )

    # ── 检查 7: 动作需要全身但首帧是特写/肩部以上 ─────────────────────────
    action_text = f"{shot.action} {' '.join(shot.second_beats)} {shot.action_en}".lower()
    needs_whole_body = any(kw.lower() in action_text for kw in WHOLE_BODY_ACTION_KEYWORDS)

    framing_text = f"{shot.shot_type} {shot.shot_type_en} {pt}".lower()
    is_closeup = any(kw.lower() in framing_text for kw in CLOSEUP_FRAMING_KEYWORDS)
    # 若首帧明确为特写但又需要全身大动作
    if needs_whole_body and is_closeup:
        errors.append(
            f"[{sid}] 首帧构图冲突: 动作需要全身或大范围位移空间 ('{shot.action or shot.action_en}')，"
            f"但首帧景别为特写/肩部以上 ('{shot.shot_type or shot.shot_type_en}')。"
            f"动作所需的身体部位与活动空间不在画内，将导致图生视频动作断裂或穿模。"
        )

    # ── 检查 8: 首帧道具状态与道具账本 0 秒状态不符 ───────────────────────
    for pname in shot.prop_names:
        p_item = prop_map.get(pname)
        if not p_item:
            continue
        p_holder = p_item.holder or ""
        p_place = p_item.placement or p_item.placement_en or ""
        p_name_en = p_item.prop_name_en or p_item.prop_name

        # 典型冲突 A: 账本中道具挂在挂钩/放在桌上/地面，但首帧描述角色手持
        if any(h in p_place for h in ["挂钩", "挂在", "桌", "地面", "现场", "hook", "hanging", "table"]):
            # 若首帧 prompt 中将该道具描述为手持或在角色手中
            wrong_holding = (
                f"holding {p_name_en.lower()}" in pt.lower()
                or f"holds {p_name_en.lower()}" in pt.lower()
                or f"in {p_holder}'s hand" in pt.lower()
                or f"手持{pname}" in pt
                or f"手提{pname}" in pt
                or f"拿{pname}" in pt
            )
            if wrong_holding:
                errors.append(
                    f"[{sid}] 首帧道具状态与道具账本 0 秒状态不符: 道具 '{pname}' 在账本中位置为 '{p_place}'，"
                    f"但首帧提示词描述为角色手持/手中。"
                )

        # 典型冲突 B: 账本中角色持有道具，但首帧描述在其他人手里或遗漏关键位置
        elif any(h in p_place for h in ["左手", "右手", "双手", "手持", "left hand", "right hand"]):
            # 如果账本指定了右手，但首帧提示词写了左手
            if "左手" in p_place or "left hand" in p_place.lower():
                if f"right hand" in pt.lower() and p_name_en.lower() in pt.lower():
                    errors.append(
                        f"[{sid}] 首帧道具状态与道具账本 0 秒状态不符: 道具 '{pname}' 在账本中为左手持有，"
                        f"但首帧提示词描述为右手持有。"
                    )
            elif "右手" in p_place or "right hand" in p_place.lower():
                if f"left hand" in pt.lower() and p_name_en.lower() in pt.lower():
                    errors.append(
                        f"[{sid}] 首帧道具状态与道具账本 0 秒状态不符: 道具 '{pname}' 在账本中为右手持有，"
                        f"但首帧提示词描述为左手持有。"
                    )

    # ── 检查 9: 角色描述未逐字复用 ────────────────────────────────────────
    for cname in shot.character_names:
        char_card = char_map.get(cname)
        if not char_card:
            continue
        # 英文提示词检查 appearance_fixed_en，若未提供英文则检查 appearance_fixed
        expected_desc = char_card.appearance_fixed_en.strip() or char_card.appearance_fixed.strip()
        if expected_desc and expected_desc not in pt:
            errors.append(
                f"[{sid}] 角色描述未逐字复用: 角色 '{cname}' 未在首帧提示词中逐字复用母卡完整描述 "
                f"(必须包含 '{expected_desc[:30]}...')。"
            )

    # ── 检查 10: 含未白名单文字 ──────────────────────────────────────────
    whitelist = bible.text_whitelist or []
    # 匹配提示词中可能声明的画内文字，如 text: '...', on-screen text: '...', letters '...'
    quoted_texts = re.findall(r"(?:text|words|displaying|reads)\s*[:：]?\s*['\"]([^'\"]+)['\"]", pt, re.I)
    for q in quoted_texts:
        q_clean = q.strip()
        if q_clean and q_clean.lower() != "no text" and q_clean not in whitelist:
            errors.append(
                f"[{sid}] 首帧提示词包含未在白名单中的文字: '{q_clean}'。FilmBible 白名单为 {whitelist}。"
            )

    return errors
