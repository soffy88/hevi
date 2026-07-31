"""讲解数字人 prompt 工程 — 半身像讲解场景的专用提示词模板。

LongCat-Avatar 文档明确建议:prompt 要长且描述性强,包含角色外貌、动作、场景上下文。
短 prompt 效果差。本模块提供讲解场景的 prompt 构造工具:

  1. 讲解者人设描述(古装史官 / 现代讲述者 / 自定义)
  2. 半身像约束(构图、动作幅度、表情)
  3. 讲解动作推断(根据文本内容推断手势/表情)
  4. 负面约束(防止夸张动作/穿帮)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from hevi.video.longcat.avatar_driver import AvatarFraming

__all__ = [
    "NarratorPersona",
    "NarratorPromptConfig",
    "build_narrator_prompt",
    "build_narrator_negative",
    "infer_gesture_from_text",
    "NARRATOR_PERSONAS",
]


@dataclass(frozen=True)
class NarratorPersona:
    """讲解者人设。"""

    name: str
    description: str          # 外貌描述
    clothing: str             # 服饰描述
    era: str                  # 时代背景
    default_framing: AvatarFraming = AvatarFraming.HALF_BODY

    def full_description(self) -> str:
        """完整人物描述(外貌+服饰+时代)。"""
        return f"{self.description},{self.clothing},{self.era}背景"


# 预置讲解者人设(对应 Hevi 已有的 _NARRATOR_DESC / DEFAULT_SHORTDRAMA_NARRATOR_DESC)
NARRATOR_PERSONAS: dict[str, NarratorPersona] = {
    "ancient_historian": NarratorPersona(
        name="ancient_historian",
        description="一位年长儒雅的古代史官,须发斑白,面容睿智平和",
        clothing="身着素色长袍,腰系玉带",
        era="中国古代",
    ),
    "modern_narrator": NarratorPersona(
        name="modern_narrator",
        description="一位沉稳知性的现代讲述者,中年男性,短发整齐",
        clothing="身着深色西装,白色衬衫",
        era="现代",
    ),
    "female_narrator": NarratorPersona(
        name="female_narrator",
        description="一位温和优雅的女性讲述者,黑色长发,面容知性",
        clothing="身着简约白色衬衫,搭配浅色外套",
        era="现代",
    ),
    "young_storyteller": NarratorPersona(
        name="young_storyteller",
        description="一位年轻活泼的讲述者,表情丰富,眼神明亮",
        clothing="身着休闲衬衫",
        era="现代",
    ),
}


@dataclass(frozen=True)
class NarratorPromptConfig:
    """讲解 prompt 配置。"""

    persona: NarratorPersona | None = None
    framing: AvatarFraming = AvatarFraming.HALF_BODY
    style: str = ""
    gesture_inference: bool = True   # 根据文本推断手势
    expression_guard: bool = True    # 表情克制约束
    custom_suffix: str = ""          # 自定义后缀


# 半身像讲解的通用正面约束
_HALF_BODY_CONSTRAINTS = (
    "半身像,腰部以上可见,正在说话并伴有自然的手势和表情,"
    "身体有轻微自然的说话动作,不要大幅度运动"
)

# 表情克制约束(参考 scene_render_avatar.py _EXPRESSION_GUARD)
_EXPRESSION_GUARD = (
    "表情自然克制,像真人演员的微表演:眼睛正常睁开不要瞪大,"
    "五官比例正常不变形,情绪含蓄不夸张,口型与语音自然同步"
)

# 半身像讲解的通用负面约束
_NARRATOR_NEGATIVE = (
    "Close-up, 全身像, 大远景, "
    "Bright tones, overexposed, static, blurred details, subtitles, "
    "worst quality, low quality, JPEG compression residue, ugly, "
    "extra fingers, poorly drawn hands, deformed, disfigured, "
    "messy background, walking backwards, "
    "exaggerated gestures, jumping, running, "  # 防止夸张动作
    "mouth wide open, teeth showing excessively"  # 防止嘴张太大
)


def infer_gesture_from_text(text: str) -> str:
    """根据讲解文本内容推断适当的手势/动作描述。

    通过分析文本中的关键词推断讲解者的自然动作:
      - 数字/时间词 → 伸手比划
      - 对比词(但是/然而) → 双手摊开
      - 强调词(重要/关键) → 微微点头
      - 疑问/思考 → 微微侧头

    Args:
        text: 讲解文本

    Returns:
        动作描述字符串(空串=无特殊动作)
    """
    gestures: list[str] = []

    # 数字/列举
    if re.search(r"[一二三四五六七八九十百千]|\d+", text):
        gestures.append("微微抬手比划")

    # 对比/转折
    if re.search(r"但是|然而|不过|却|虽然|尽管", text):
        gestures.append("双手微微摊开表示对比")

    # 强调
    if re.search(r"重要|关键|核心|必须|正是|恰恰", text):
        gestures.append("微微点头强调")

    # 疑问/思考
    if re.search(r"为什么|如何|怎样|难道|难道", text):
        gestures.append("微微侧头思考状")

    # 叙述/描述
    if re.search(r"然后|接着|之后|随后", text):
        gestures.append("手势自然过渡")

    if not gestures:
        return ""

    # 最多叠加 2 个动作
    return ", ".join(gestures[:2])


def build_narrator_prompt(
    narration_text: str,
    config: NarratorPromptConfig | None = None,
) -> str:
    """构造讲解数字人的完整 prompt。

    Args:
        narration_text: 讲解文本
        config: prompt 配置

    Returns:
        完整的视频生成 prompt
    """
    if config is None:
        config = NarratorPromptConfig()

    parts: list[str] = []

    # 1. 人物描述
    if config.persona is not None:
        parts.append(config.persona.full_description())

    # 2. 半身像约束
    framing_desc = {
        AvatarFraming.HALF_BODY: "半身像,腰部以上可见",
        AvatarFraming.MEDIUM_SHOT: "中景,腰部以上",
        AvatarFraming.CLOSE_UP: "近景,肩部以上",
    }.get(config.framing, "半身像")
    parts.append(framing_desc)
    parts.append("正在说话并伴有自然的手势和表情")

    # 3. 画风
    if config.style:
        parts.append(config.style)

    # 4. 动作推断
    if config.gesture_inference:
        gesture = infer_gesture_from_text(narration_text)
        if gesture:
            parts.append(gesture)

    # 5. 表情约束
    if config.expression_guard:
        parts.append(_EXPRESSION_GUARD)

    # 6. 自定义后缀
    if config.custom_suffix:
        parts.append(config.custom_suffix)

    return ", ".join(parts)


def build_narrator_negative() -> str:
    """返回讲解数字人的标准负面 prompt。"""
    return _NARRATOR_NEGATIVE
