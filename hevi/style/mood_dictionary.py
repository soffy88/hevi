"""抽象词→具象现象词典(HEVI 路线图 Phase3 #38)。

跨所有 StylePack/预设共享一份——"温馨"这类情绪词直接喂给视频生成模型往往落地
成空洞的滤镜式氛围;换成具体可拍摄的现象("树影移动/晾衣绳织物摇曳/陶瓷杯冒
热气")模型才有实际画面可参照。之前每个 style_preset 各写一遍类似的具象化描述
(参见 style_presets.py 里 20 个预设各自的 style/lighting 短语),这里抽成公共
词典,新增预设/StylePack 直接复用,不必每次重新想具象化措辞。

只覆盖已知情绪词;没有对应词条 → 原样返回,不瞎编具象化描述(宁可退化成"这个
情绪词 mood"这种朴素后缀,也不该编造跟这个词实际不搭的具象现象)。
"""

from __future__ import annotations

ABSTRACT_TO_CONCRETE: dict[str, str] = {
    "温馨": "tree shadows drifting on the wall, fabric swaying on a clothesline, "
    "steam rising from a ceramic cup",
    "紧张": "a slight tremor in the hands in close-up, audible breathing, long stretched shadows",
    "孤独": "a single figure dwarfed by empty space, footsteps echoing, dim scattered light",
    "怀旧": "dust motes floating in a sunbeam, faded photographs, a slow ticking clock",
    "浪漫": "soft golden backlight through hair, gentle wind lifting fabric, warm bokeh lights",
    "压抑": "low ceiling framing, muted desaturated tones, characters shot through doorways",
    "希望": "light breaking through clouds, a slow sunrise, an open window with fresh air",
    "神秘": "fog rolling low across the ground, a single flickering light source, long silence",
    "欢快": "quick handheld movement, bright saturated colors, characters laughing mid-motion",
    "疲惫": "slumped posture, half-closed eyes, muted flat lighting, slow drifting camera",
}


def expand_mood_to_concrete(mood: str) -> str:
    """情绪词 → 具象现象描述。没有词条 → 原样返回(不编造)。"""
    return ABSTRACT_TO_CONCRETE.get(mood, mood)


def list_known_moods() -> list[str]:
    return list(ABSTRACT_TO_CONCRETE)
