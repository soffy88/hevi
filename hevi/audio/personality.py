"""语音人格系统（对标 VoiceBox Voice Personalities）。

用 LLM 改写文本以匹配角色的说话风格/人格:
- 每个角色绑定一段人格描述（说话习惯、用词偏好、性格特征）
- Compose: LLM 以角色身份即兴生成一句话
- Rewrite: LLM 将输入文本改写为角色风格
- Respond: LLM 以角色身份回复对话

集成到 Hevi 的 TTS 管线:
    text → personality.rewrite(text, persona) → tts.synthesize(rewritten)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class VoicePersona:
    """角色语音人格。"""
    name: str
    description: str  # 角色描述
    speaking_style: str = ""  # 说话风格（如"粗犷直爽"、"温文尔雅"、"毒舌"）
    vocabulary: list[str] = field(default_factory=list)  # 常用词汇/口头禅
    background: str = ""  # 背景信息（影响知识水平和用语）
    emotional_tendency: str = "neutral"  # 情感倾向: optimistic/pessimistic/neutral/volatile


@dataclass
class PersonaResult:
    """人格改写结果。"""
    original_text: str
    rewritten_text: str
    persona_name: str
    confidence: float = 1.0
    model_used: str = ""


_REWRITE_PROMPT_TEMPLATE = """你是一个语音合成管线的文本改写器。你需要将用户输入的文本改写为符合以下角色人格的说话风格。

角色名称: {name}
角色描述: {description}
说话风格: {speaking_style}
常用词汇/口头禅: {vocabulary}
背景信息: {background}
情感倾向: {emotional_tendency}

改写要求:
1. 保持原始文本的核心含义不变
2. 调整用词和句式使其符合角色的说话风格
3. 适当融入角色的常用词汇和口头禅（但不要每句都加）
4. 控制改写幅度：轻微调整即可，不要大幅改变
5. 直接输出改写后的文本，不要加任何解释或前缀

原始文本: {text}

改写后的文本:"""

_COMPOSE_PROMPT_TEMPLATE = """你是一个角色扮演 AI。请以以下角色的身份，即兴说一句话。

角色名称: {name}
角色描述: {description}
说话风格: {speaking_style}
常用词汇/口头禅: {vocabulary}
背景信息: {background}
情感倾向: {emotional_tendency}

上下文: {context}

请生成一句符合角色的台词（15-40字），直接输出文本:"""

_RESPOND_PROMPT_TEMPLATE = """你是一个角色扮演 AI。请以以下角色的身份回复对话。

角色名称: {name}
角色描述: {description}
说话风格: {speaking_style}
常用词汇/口头禅: {vocabulary}
背景信息: {background}
情感倾向: {emotional_tendency}

对方说的话: {input_text}

请以角色的口吻回复（15-50字），直接输出文本:"""


class PersonalityEngine:
    """语音人格引擎：用 LLM 改写文本以匹配角色人格。"""

    def __init__(self, llm_fn: Callable[..., Awaitable[str]] | None = None):
        """
        Args:
            llm_fn: 异步 LLM 调用函数 async def fn(prompt: str) -> str
                    None 时使用基于规则的简单改写
        """
        self._llm_fn = llm_fn

    async def rewrite(
        self,
        text: str,
        persona: VoicePersona,
    ) -> PersonaResult:
        """将文本改写为角色风格。"""
        if not text.strip():
            return PersonaResult(
                original_text=text,
                rewritten_text=text,
                persona_name=persona.name,
            )

        if self._llm_fn is not None:
            prompt = _REWRITE_PROMPT_TEMPLATE.format(
                name=persona.name,
                description=persona.description,
                speaking_style=persona.speaking_style,
                vocabulary=", ".join(persona.vocabulary) if persona.vocabulary else "无",
                background=persona.background or "无",
                emotional_tendency=persona.emotional_tendency,
                text=text,
            )
            try:
                rewritten = await self._llm_fn(prompt)
                rewritten = rewritten.strip().strip('"').strip("'")
                return PersonaResult(
                    original_text=text,
                    rewritten_text=rewritten,
                    persona_name=persona.name,
                    model_used="llm",
                )
            except Exception as e:
                logger.warning("LLM rewrite failed, using original: %s", e)
                return PersonaResult(
                    original_text=text,
                    rewritten_text=text,
                    persona_name=persona.name,
                    confidence=0.5,
                )

        # Fallback: 规则改写
        return self._rule_based_rewrite(text, persona)

    async def compose(
        self,
        persona: VoicePersona,
        context: str = "",
    ) -> PersonaResult:
        """以角色身份即兴生成一句话。"""
        if self._llm_fn is not None:
            prompt = _COMPOSE_PROMPT_TEMPLATE.format(
                name=persona.name,
                description=persona.description,
                speaking_style=persona.speaking_style,
                vocabulary=", ".join(persona.vocabulary) if persona.vocabulary else "无",
                background=persona.background or "无",
                emotional_tendency=persona.emotional_tendency,
                context=context or "日常场景",
            )
            try:
                generated = await self._llm_fn(prompt)
                return PersonaResult(
                    original_text="",
                    rewritten_text=generated.strip().strip('"').strip("'"),
                    persona_name=persona.name,
                    model_used="llm",
                )
            except Exception as e:
                logger.warning("LLM compose failed: %s", e)

        # Fallback
        phrases = persona.vocabulary or ["嗯", "好的"]
        return PersonaResult(
            original_text="",
            rewritten_text=f"{'，'.join(phrases[:2])}。",
            persona_name=persona.name,
            confidence=0.3,
        )

    async def respond(
        self,
        input_text: str,
        persona: VoicePersona,
    ) -> PersonaResult:
        """以角色身份回复对话。"""
        if self._llm_fn is not None:
            prompt = _RESPOND_PROMPT_TEMPLATE.format(
                name=persona.name,
                description=persona.description,
                speaking_style=persona.speaking_style,
                vocabulary=", ".join(persona.vocabulary) if persona.vocabulary else "无",
                background=persona.background or "无",
                emotional_tendency=persona.emotional_tendency,
                input_text=input_text,
            )
            try:
                response = await self._llm_fn(prompt)
                return PersonaResult(
                    original_text=input_text,
                    rewritten_text=response.strip().strip('"').strip("'"),
                    persona_name=persona.name,
                    model_used="llm",
                )
            except Exception as e:
                logger.warning("LLM respond failed: %s", e)

        return PersonaResult(
            original_text=input_text,
            rewritten_text=f"（{persona.name}沉默不语）",
            persona_name=persona.name,
            confidence=0.3,
        )

    def _rule_based_rewrite(
        self, text: str, persona: VoicePersona
    ) -> PersonaResult:
        """基于规则的简单改写（无 LLM 时的 fallback）。"""
        rewritten = text

        # 添加口头禅（20% 概率在句首加）
        if persona.vocabulary:
            import random
            catchphrase = random.choice(persona.vocabulary)
            if not rewritten.startswith(catchphrase):
                rewritten = f"{catchphrase}，{rewritten}"

        # 风格微调
        if "粗犷" in persona.speaking_style or "直爽" in persona.speaking_style:
            rewritten = rewritten.replace("请", "").replace("麻烦", "")
        elif "温文尔雅" in persona.speaking_style:
            if not rewritten.endswith("。") and not rewritten.endswith("！"):
                rewritten += "。"

        return PersonaResult(
            original_text=text,
            rewritten_text=rewritten,
            persona_name=persona.name,
            confidence=0.7,
            model_used="rule_based",
        )


# ── 便捷预设人格 ──────────────────────────────────────────────────────────

PRESET_PERSONAS: dict[str, VoicePersona] = {
    "warrior": VoicePersona(
        name="战士",
        description="身经百战的武将，说话直来直去",
        speaking_style="粗犷直爽，简短有力",
        vocabulary=["哈！", "俺", "来战！"],
        background="军旅出身，不识字但精通兵法",
        emotional_tendency="volatile",
    ),
    "scholar": VoicePersona(
        name="书生",
        description="饱读诗书的文人，谈吐文雅",
        speaking_style="温文尔雅，引经据典",
        vocabulary=["依在下之见", "此言差矣", "妙哉"],
        background="寒窗苦读十年，对诗词歌赋颇有造诣",
        emotional_tendency="optimistic",
    ),
    "villain": VoicePersona(
        name="反派",
        description="阴险狡诈的幕后黑手",
        speaking_style="阴冷低沉，话中有话",
        vocabulary=["呵呵", "有趣", "你以为…"],
        background="权倾朝野，城府极深",
        emotional_tendency="pessimistic",
    ),
    "child": VoicePersona(
        name="孩童",
        description="天真烂漫的小孩子",
        speaking_style="活泼天真，用词简单",
        vocabulary=["哇！", "为什么呀？", "好厉害！"],
        background="五岁的小孩子，对世界充满好奇",
        emotional_tendency="optimistic",
    ),
}


def get_preset_persona(name: str) -> VoicePersona | None:
    """获取预设人格。"""
    return PRESET_PERSONAS.get(name)


def list_preset_personas() -> list[str]:
    """列出可用预设人格。"""
    return sorted(PRESET_PERSONAS.keys())
