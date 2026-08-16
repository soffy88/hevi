"""hevi.dub.emotion — 情感感知配音(对标 DramaClaw 情感感知配音)。

台词级情感(emotion) → TTS 参数映射:高兴/悲伤/愤怒/平静/紧张等
驱动 edge-tts 的 rate/pitch/volume/voice 调整,让配音带情绪。
纯机制:确定性映射 + 台词情感标注辅助;装配层(_synth)注入合成参数。

情感标注来源:1) screenplay/dub 已有台词标注;2) 未标注时按关键词启发式
(确定性,不调 LLM);3) 可选 LLM 深度标注(装配层决定)。
"""

from __future__ import annotations

from dataclasses import dataclass

# 情感 → TTS 参数(edge-tts 风格: rate/pitch/volume)
# rate/pitch/volume 为相对百分比(正=提升,负=降低),edge-tts 接受 "+10%" 形式。
EMOTION_PROFILES: dict[str, dict[str, str]] = {
    "happy": {"rate": "+10%", "pitch": "+15%", "volume": "+0%", "voice_hint": ""},
    "sad": {"rate": "-15%", "pitch": "-10%", "volume": "-10%", "voice_hint": ""},
    "angry": {"rate": "+5%", "pitch": "-10%", "volume": "+15%", "voice_hint": ""},
    "calm": {"rate": "-5%", "pitch": "-5%", "volume": "-5%", "voice_hint": ""},
    "nervous": {"rate": "+15%", "pitch": "+5%", "volume": "-5%", "voice_hint": ""},
    "excited": {"rate": "+20%", "pitch": "+20%", "volume": "+5%", "voice_hint": ""},
    "neutral": {"rate": "+0%", "pitch": "+0%", "volume": "+0%", "voice_hint": ""},
}

VALID_EMOTIONS = frozenset(EMOTION_PROFILES)

# 关键词启发式情感分类(确定性,台词未标注时用)
_EMOTION_KEYWORDS: dict[str, list[str]] = {
    "happy": ["笑", "高兴", "开心", "太好了", "哈哈", "喜欢"],
    "sad": ["哭", "难过", "伤心", "遗憾", "对不起", "别了", "眼泪"],
    "angry": ["怒", "混蛋", "岂有此理", "气", "恨", "闭嘴"],
    "nervous": ["紧张", "发抖", "害怕", "怎么办"],
    "excited": ["激动", "万岁", "太棒了", "兴奋"],
    "calm": ["平静", "淡然", "放心", "别急"],
}


@dataclass
class EmotionCue:
    """带情感的台词: 文本 + 情感 + 可选说话人。"""

    text: str
    emotion: str = "neutral"
    speaker: str = ""


def detect_emotion(text: str) -> str:
    """确定性情感分类: 关键词命中(优先级 happy > angry > sad > ...) → neutral。"""
    score: dict[str, int] = {}
    for emotion, kws in _EMOTION_KEYWORDS.items():
        score[emotion] = sum(1 for kw in kws if kw in text)
    if not any(score.values()):
        return "neutral"
    return max(score, key=lambda k: score[k])


def emotion_tts_params(emotion: str) -> dict[str, str]:
    """情感 → TTS 参数(未知情感回退 neutral)。"""
    return EMOTION_PROFILES.get(emotion, EMOTION_PROFILES["neutral"])


def apply_emotion_to_edge_tts(
    base_params: dict[str, str], emotion: str
) -> dict[str, str]:
    """把情感参数合入 edge-tts 调用参数(显式情感覆盖 base)。"""
    merged = dict(base_params)
    prof = emotion_tts_params(emotion)
    for k in ("rate", "pitch", "volume"):
        if prof.get(k) and prof[k] != "+0%":
            merged[k] = prof[k]
    return merged
