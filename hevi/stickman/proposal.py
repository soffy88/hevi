"""stickman.proposal —— 导演提案与状态机。

提案包含：黄金钩子、色调、分镜表（分段/时长/声画动作）、旁白声线、BGM 风格。
状态机约束：
- 状态：draft -> approved / rejected
- 画幅（aspect_ratio）与画风（art_style）只能在 draft 阶段修改；approved 状态下锁定。
- 只有 approved 状态允许生成提示词（Flow pack）或渲染成片；未批准调用直接报错拦截。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


class ProposalError(Exception):
    """提案基础异常。"""


class ProposalNotApprovedError(ProposalError):
    """未批准不得出提示词或出片。"""


class ProposalModificationError(ProposalError):
    """已批准状态禁止修改受保护字段（画幅、画风）。"""


@dataclass
class StoryboardScene:
    scene_index: int
    stage: str
    duration_s: float
    visual_beats: list[str]
    narration_zh: str
    narration_en: str = ""
    visual_action: str = ""
    first_frame_state: str = ""
    last_frame_state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_index": self.scene_index,
            "stage": self.stage,
            "duration_s": self.duration_s,
            "visual_beats": self.visual_beats,
            "narration_zh": self.narration_zh,
            "narration_en": self.narration_en,
            "visual_action": self.visual_action,
            "first_frame_state": self.first_frame_state,
            "last_frame_state": self.last_frame_state,
        }


@dataclass
class DirectorProposal:
    proposal_id: str
    title: str
    topic: str
    hook: str
    color_palette: dict[str, str]
    storyboard: list[StoryboardScene]
    voiceover: dict[str, Any]
    bgm_style: str
    aspect_ratio: str = "16:9"  # "16:9" 或 "9:16"
    art_style: str = "classic_minimalist"  # "classic_minimalist" 或 "color_story"
    status: str = "draft"  # draft -> approved / rejected
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_duration(self) -> float:
        return sum(s.duration_s for s in self.storyboard)

    def approve(self) -> None:
        """批准提案，锁定画幅画风并激活出片权限。"""
        if not self.storyboard:
            raise ProposalError("分镜表为空，不可批准提案")
        self.status = "approved"

    def reject(self, reason: str = "") -> None:
        """驳回提案回 draft 或 rejected。"""
        self.status = "rejected"
        if reason:
            self.metadata["rejection_reason"] = reason

    def reopen(self) -> None:
        """重新打开为 draft 以便编辑画幅画风。"""
        self.status = "draft"

    def update_settings(
        self,
        *,
        aspect_ratio: str | None = None,
        art_style: str | None = None,
        hook: str | None = None,
        bgm_style: str | None = None,
        color_palette: dict[str, str] | None = None,
    ) -> None:
        """更新提案设置。画幅和画风只能在 draft 状态下修改。"""
        if self.status != "draft":
            if (aspect_ratio is not None and aspect_ratio != self.aspect_ratio) or (
                art_style is not None and art_style != self.art_style
            ):
                raise ProposalModificationError(
                    f"画幅与画风只能在提案草稿阶段(draft)修改，当前提案状态为 '{self.status}'。"
                    "如需修改，请先调用 reopen() 打回草稿。"
                )

        if aspect_ratio is not None:
            if aspect_ratio not in ("16:9", "9:16", "1:1"):
                raise ProposalError(f"不支持的画幅: {aspect_ratio}")
            self.aspect_ratio = aspect_ratio

        if art_style is not None:
            if art_style not in ("classic_minimalist", "color_story"):
                raise ProposalError(f"不支持的画风: {art_style}")
            self.art_style = art_style

        if hook is not None:
            self.hook = hook
        if bgm_style is not None:
            self.bgm_style = bgm_style
        if color_palette is not None:
            self.color_palette = color_palette

    def assert_can_render(self) -> None:
        """检查出片权限：未批准不得出片。"""
        if self.status != "approved":
            raise ProposalNotApprovedError(
                f"提案尚未批准(当前状态: '{self.status}')，未批准不得出片。"
                "请先由导演/评审调用 approve()。"
            )

    def assert_can_generate_prompts(self) -> None:
        """检查出提示词权限：未批准不得出提示词。"""
        if self.status != "approved":
            raise ProposalNotApprovedError(
                f"提案尚未批准(当前状态: '{self.status}')，未批准不得出 Flow 提示词包。"
                "请先由导演/评审调用 approve()。"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "title": self.title,
            "topic": self.topic,
            "hook": self.hook,
            "color_palette": self.color_palette,
            "storyboard": [s.to_dict() for s in self.storyboard],
            "voiceover": self.voiceover,
            "bgm_style": self.bgm_style,
            "aspect_ratio": self.aspect_ratio,
            "art_style": self.art_style,
            "status": self.status,
            "total_duration": self.total_duration,
            "metadata": self.metadata,
        }


def create_proposal_from_script(
    script_data: dict[str, Any],
    *,
    aspect_ratio: str = "16:9",
    art_style: str = "classic_minimalist",
    bgm_style: str = "Kinetic Piano & Upbeat Lo-Fi Synth",
    voiceover_profile: str = "Natural Analytical Male",
) -> DirectorProposal:
    """从五段骨架台本生成导演提案草稿。

    将五段结构映射为 6 镜（针对 60 秒标配，每镜 ≤ 10 秒），
    保证每镜时长适合 Flow 与本地精准渲染。
    """
    topic = script_data.get("topic", "未命名选题")
    stages = script_data.get("stages", [])

    # 提取钩子与台词
    hook_text = ""
    for s in stages:
        if s.get("stage_name") == "悬念追问":
            hook_text = s.get("narration", "")
            break
    if not hook_text and stages:
        hook_text = stages[0].get("narration", "")

    # 默认色彩契约
    if art_style == "classic_minimalist":
        color_palette = {
            "background": "pure_white",
            "ink": "pure_black",
            "accent1": "vivid red",
            "accent2": "electric blue",
            "accent3": "warm gold",
        }
    else:
        color_palette = {
            "background": "soft_studio_cream",
            "character_hat": "bright red beanie",
            "character_shirt": "vibrant yellow t-shirt",
            "accent": "cyan glow",
        }

    # 规划分镜（6段各10秒，每镜 <= 10s，匹配 Flow 与心跳节拍）
    # 镜1: 黄金钩子 (0-10s)
    # 镜2: 常识铺垫 (10-20s)
    # 镜3: 反转机制 (20-30s)
    # 镜4: 核心揭秘第1段 (30-40s)
    # 镜5: 核心揭秘第2段 (40-50s)
    # 镜6: 互动收尾与升华 (50-60s)
    stage_map = {s.get("stage_name"): s.get("narration", "") for s in stages}

    s1_zh = stage_map.get("悬念追问", hook_text)
    s2_zh = stage_map.get("常识铺垫", "常识认为事物总是符合表面直觉。")
    s3_zh = stage_map.get("反转", "然而真实物理规则在此发生完全逆转！")
    s4_full = stage_map.get("揭秘", "核心揭秘：密度与浮力平衡决定了沉浮状态。")
    # 如果揭秘较长，切两句
    parts = s4_full.split("！") if "！" in s4_full else [s4_full[: len(s4_full) // 2], s4_full[len(s4_full) // 2 :]]
    s4_zh = parts[0] + "！" if len(parts) > 1 else parts[0]
    s5_zh = parts[1] if len(parts) > 1 else "密度比油大，自然直坠沉底！"
    s6_zh = stage_map.get("互动收尾", "在下方打出你的独到推演，看看谁能猜中正解！")

    storyboard_scenes = [
        StoryboardScene(
            scene_index=1,
            stage="悬念追问",
            duration_s=10.0,
            visual_beats=[
                "[0-3s] 火柴人好奇地手持冰块站在水杯与油杯前",
                "[3-7s] 冰块丢入水杯，水花溅起后轻盈漂浮在水面",
                "[7-10s] 火柴人转头看向旁边黄色的食用油杯，眼神闪过巨大问号",
            ],
            narration_zh=s1_zh,
            narration_en="Why does an identical ice cube float in water, but sink like a stone in oil?",
            visual_action="火柴人手持冰块对比水与油两杯液体",
            first_frame_state="火柴人居中站立，纯净白底黑线，双手捧着发蓝光的纯净冰块",
            last_frame_state="水杯中冰块稳定漂浮，火柴人正对镜头挥手指向旁边的食用油杯",
        ),
        StoryboardScene(
            scene_index=2,
            stage="常识铺垫",
            duration_s=10.0,
            visual_beats=[
                "[0-3s] 背景出现直觉图表：水结冰体积膨胀示意图",
                "[3-7s] 脑海弹泡：冰肯定比所有液体都要轻",
                "[7-10s] 火柴人自信满满地竖起大拇指",
            ],
            narration_zh=s2_zh,
            narration_en="Common sense tells us water expands into ice, so we assume ice is lighter than liquids.",
            visual_action="火柴人展示常识思维气泡与体积膨胀图",
            first_frame_state="火柴人站在黑白对比坐标轴旁，身后展示水分子排列表",
            last_frame_state="火柴人单手托腮做胸有成竹状",
        ),
        StoryboardScene(
            scene_index=3,
            stage="反转",
            duration_s=10.0,
            visual_beats=[
                "[0-3s] 冰块被投入食用油杯中",
                "[3-7s] 冰块不仅没有浮起，反而呼啸直沉杯底摔个底朝天",
                "[7-10s] 火柴人抱头惊呼，红色感叹号爆开",
            ],
            narration_zh=s3_zh,
            narration_en="But common sense fails: vegetable oils are actually much lighter than water!",
            visual_action="冰块在油中直坠沉底，火柴人震惊大叫",
            first_frame_state="火柴人悬空松开冰块进入油杯上方",
            last_frame_state="冰块重重砸在油杯底部，火柴人双手捂住圆脸做惊恐状",
        ),
        StoryboardScene(
            scene_index=4,
            stage="揭秘",
            duration_s=10.0,
            visual_beats=[
                "[0-3s] 虚空中浮现天平与数字标尺：水 1.0，冰 0.917",
                "[3-7s] 火柴人拉出食用油的标尺：0.91",
                "[7-10s] 红色高亮闪烁：冰比油更重！",
            ],
            narration_zh=s4_zh,
            narration_en="Physics reveal: water density is 1.0, ice is 0.917, while cooking oil is only 0.91!",
            visual_action="火柴人拉出三者密度标尺精准比对",
            first_frame_state="火柴人指向上方浮现的三根不同高度的密度量筒",
            last_frame_state="冰块的 0.917 数值红光高亮压过食用油的 0.91",
        ),
        StoryboardScene(
            scene_index=5,
            stage="揭秘升华",
            duration_s=10.0,
            visual_beats=[
                "[0-3s] 阿基米德浮力定律动画示意，排开液体重量不足以支撑重力",
                "[3-7s] 冰块在油中被重力死死拉向底部",
                "[7-10s] 火柴人豁然开朗，头顶灯泡亮起金色光芒",
            ],
            narration_zh=s5_zh,
            narration_en="Ice is denser than oil, so buoyant force cannot sustain it and it must sink!",
            visual_action="火柴人展示浮力受力分析箭头，灯泡点亮",
            first_frame_state="油杯剖面力学箭头向下，浮力小于重力",
            last_frame_state="火柴人头顶金黄灯泡亮起，自信指向上方",
        ),
        StoryboardScene(
            scene_index=6,
            stage="互动收尾",
            duration_s=10.0,
            visual_beats=[
                "[0-3s] 地球极地冰川全景浮现",
                "[3-7s] 冰川下方的海水换成了金色食用油，冰山沉没大猜想",
                "[7-10s] 火柴人向观众递出话筒，下方弹出互动评论符号",
            ],
            narration_zh=s6_zh,
            narration_en="If Antarctica's oceans turned into oil, would icebergs still float? Share below!",
            visual_action="火柴人递出话筒向全网观众发起神级挑战",
            first_frame_state="火柴人站在极地冰山与油海推演全景图旁",
            last_frame_state="火柴人微笑指向屏幕下方评论互动区域",
        ),
    ]

    return DirectorProposal(
        proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
        title=topic,
        topic=topic,
        hook=hook_text,
        color_palette=color_palette,
        storyboard=storyboard_scenes,
        voiceover={
            "profile": voiceover_profile,
            "pace_wpm": 135,
            "language": "zh-CN",
            "ref_language": "en-US",
        },
        bgm_style=bgm_style,
        aspect_ratio=aspect_ratio,
        art_style=art_style,
        status="draft",
    )
