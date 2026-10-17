"""连续性契约数据结构 —— 导演一部片前后不穿帮的核心状态母本。

覆盖 BRIEF_CONT1017 规范：
- FilmBible: 整片总则、画幅、风格定性(不是X，而是Y)、语言锁、文字白名单、资产上限等
- VoiceCard: 音色母卡(性别年龄/音高/语速/质感/口音/混响)
- CharacterCard: 角色母卡(S号/姓名/逐字固定外貌/音色/故事日状态)
- SceneCard: 场景母卡(站位图/轴线/反打背景/灯光/镜头/底噪/配乐策略)
- PropItem / PropLedger: 道具账本(持有人/手部占用/液位/起止状态)
- ShotDialogue / ShotContract: 镜头契约(景别/单运镜/视线/动作对齐/台词预算/情绪/状态衔接)
- GenerationLog: 场记生成日志(模型版本/seed/参考文件/条次/选用标记)
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class VoiceCard(BaseModel):
    """角色的固定声音母卡。"""

    gender_age: str = ""  # 如 "32岁成年男性"
    pitch: str = ""  # 音高，如 "中低音沉稳"
    speed: str = ""  # 语速，如 "中速沉稳，约每秒3-4字"
    timbre: str = ""  # 音色质感，如 "温和醇厚、略带磁性沙哑"
    accent: str = "标准普通话，无方言口音"  # 口音
    reverb: str = "室内轻度混响匹配"  # 空间混响

    def to_prompt_text(self) -> str:
        parts: list[str] = []
        if self.gender_age:
            parts.append(self.gender_age)
        if self.pitch:
            parts.append(f"音高:{self.pitch}")
        if self.speed:
            parts.append(f"语速:{self.speed}")
        if self.timbre:
            parts.append(f"质感:{self.timbre}")
        if self.accent:
            parts.append(f"口音:{self.accent}")
        if self.reverb:
            parts.append(f"混响:{self.reverb}")
        return "，".join(parts)


class ReferenceAsset(BaseModel):
    """参考资产。"""

    asset_id: str
    asset_type: str = "image"  # face / body / scene / voice / prop
    target_name: str = ""  # 对应角色或场景名
    file_path: str = ""
    description: str = ""


class FilmBible(BaseModel):
    """整片圣经：全片级连续性契约。"""

    title: str = ""  # 片名
    aspect_ratio: str = "16:9"  # 画幅
    style_is: list[str] = Field(default_factory=list)  # 肯定风格
    style_is_not: list[str] = Field(default_factory=list)  # 否定风格
    language: str = "zh-普通话"  # 对白语言默认普通话
    language_lock: str = "全部对白与背景人声只说普通话，禁止日语或其他语言；画面不出现文字"
    text_whitelist: list[str] = Field(default_factory=list)  # 画内文字白名单
    genre_preset: str = ""  # 类型预设(来自 15 genres)
    color_grading_baseline: str = ""  # 调色基准(如 "胶片暖金低饱和高宽容度")
    story_days: dict[str, Any] = Field(default_factory=dict)  # 故事日/时间线表
    target_duration_s: float = 0.0  # 片长目标(秒)
    reference_assets: list[ReferenceAsset] = Field(default_factory=list)
    # 平台参考资产数量上限(research.md 实证)
    reference_limits: dict[str, int] = Field(
        default_factory=lambda: {
            "seedance": 5,
            "sora_characters": 2,
            "veo": 3,
            "grok_images": 14,
            "grok_voices": 3,
            "kling": 4,
        }
    )
    native_audio_strategy: str = (
        "原生音频仅作口型参考，全部替换；每场景铺一条连续底噪，配音加该房间混响"
    )

    def format_style_qualification(self) -> str:
        """输出成'不是X，而是Y'的风格定性。"""
        not_str = "、".join(self.style_is_not) if self.style_is_not else "快餐网剧或廉价短视频质感"
        is_str = "、".join(self.style_is) if self.style_is else "电影质感现实主义叙事短片"
        return f"风格定性：不是{not_str}，而是{is_str}。"


class CharacterCard(BaseModel):
    """角色卡：完整外貌固定描述(逐字复用，禁止只给短锚点)。"""

    s_no: int  # S号，全片稳定 1-based
    name: str  # 角色名
    appearance_fixed: str  # 完整外貌描述(脸/肤/眼/眉/鼻唇/发/服装/配饰)，禁止只给短锚点
    voice_card: VoiceCard | None = None  # 音色母卡
    daily_states: dict[str, str] = Field(default_factory=dict)  # 故事日状态(伤/脏/湿/换装)

    def get_full_description(self, story_day: str = "") -> str:
        base = self.appearance_fixed.strip()
        day_note = self.daily_states.get(story_day, "").strip() if story_day else ""
        if day_note:
            return f"{base}【当日状态:{day_note}】"
        return base


class SceneCard(BaseModel):
    """场景卡：空间与声画物理基准。"""

    scene_name: str
    description: str = ""  # 场景固定描述
    top_down_blocking: str = ""  # 俯视站位图(文字坐标)
    axis: str = ""  # 主轴线约定与正反打视线基准
    reverse_angle_background: str = ""  # 反打方向背景固定描述
    lighting: str = ""  # 来自词表+主光方向+色温+调色
    lens: str = ""  # 焦段/光圈/机位高度
    ambient_noise: str = "环境底噪连续稳定，无突然静音或音量跳变"  # 固定底噪一句
    music_policy: str = "无音乐"  # 配乐策略，明确“无音乐”或指定乐段


class PropItem(BaseModel):
    """单项道具状态。"""

    prop_name: str
    holder: str = ""  # 持有人(角色名)
    placement: str = ""  # 左手/右手/双手/背/斜挎/桌面/地面
    start_state: str = ""  # 起始状态
    end_state: str = ""  # 结束状态
    liquid_level: str = ""  # 液位等细节(如 "八分满咖啡", "半支烟")
    notes: str = ""


class PropLedger(BaseModel):
    """道具账本。"""

    items: list[PropItem] = Field(default_factory=list)

    def get_item(self, prop_name: str) -> PropItem | None:
        for it in self.items:
            if it.prop_name == prop_name:
                return it
        return None

    def items_held_by(self, holder: str) -> list[PropItem]:
        return [it for it in self.items if it.holder == holder]


class ShotDialogue(BaseModel):
    """镜头台词。"""

    speaker: str = ""  # 说话人
    text: str = ""  # 台词正文
    is_in_frame: bool = True  # 是否画内
    lip_sync_locked: bool = True  # 口型锁定等级
    quote_id: str = ""  # 溯源标记
    max_duration_budget_s: float = 0.0  # 时长预算(秒)，0 表示按字数自动算


class ShotContract(BaseModel):
    """镜头连续性契约(扩展 ShotListItem)。"""

    shot_id: str
    scene_name: str = ""
    shot_type: str = ""  # 景别类型(来自 25 Shot Types 词表)
    camera_move: str = ""  # 唯一运镜(来自 20 Camera Movements 词表，每镜限一种)
    composition: str = ""  # 构图(来自 12 Composition 词表)
    transition_in: str = ""  # 入场转场
    transition_out: str = ""  # 出场转场
    eyeline_angle: str = ""  # 视线角度(如 "视线画右偏15°、微仰")
    in_out_direction: str = ""  # 出入画方向(如 "画左入画，静止停留")
    second_beats: list[str] = Field(default_factory=list)  # 按秒 beats 内部计划
    match_on_action: str = ""  # 动作对齐到台词某个词
    hands_occupation: dict[str, str] = Field(default_factory=dict)  # 手部占用
    dialogue: ShotDialogue | None = None
    dialogue_lines: list[ShotDialogue] = Field(default_factory=list)
    emotion_scale: str = ""  # 情绪刻度(如 "3/10 压抑 → 5/10 绷不住")
    start_state: dict[str, str] | str = Field(default_factory=dict)  # 起始状态
    end_state: dict[str, str] | str = Field(default_factory=dict)  # 结束状态
    negatives: list[str] = Field(default_factory=list)  # 负面与约束
    character_names: list[str] = Field(default_factory=list)
    character_anchor: str = ""  # 历史/兼容锚点字段(若给出且非完整母卡描述，将被连续性校验器拦截)
    character_descriptions: dict[str, str] = Field(default_factory=dict)  # 自定义角色描述覆盖
    prop_names: list[str] = Field(default_factory=list)
    duration_s: float = 5.0
    visual_prompt: str = ""
    action: str = ""
    on_screen_text: list[str] = Field(default_factory=list)  # 画面可能出现的文字
    story_day: str = "D1"  # 故事日对应


class GenerationLog(BaseModel):
    """生成日志与场记圈选。"""

    shot_id: str = ""
    model_version: str = ""
    seed: int | None = None
    reference_files: list[str] = Field(default_factory=list)
    take_no: int = 1
    selected: bool = False
    reject_reason: str = ""
