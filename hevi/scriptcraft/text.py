"""Shared text helpers for the S28 script layer.

All thresholds come from the brief: dialogue is timed at 4–5 characters per
second, actions must be physically filmable, and a setup that needs more than
three sentences to understand is a different story.
"""

from __future__ import annotations

import re
from typing import Any

CN_PUNCT = set("，。！？；：、…—「」『』“”‘’（）()《》〈〉—-,.!?;: \t\n\r")
SENTENCE_END = re.compile(r"(?<=[。！？!?；;…])")
ACTION_PREFIX = "△"

PHYSICAL_VERBS = (
    "看", "望", "盯", "瞥", "扫", "低", "抬", "转", "回", "走", "跑", "冲", "退", "站",
    "坐", "蹲", "跪", "躺", "靠", "倚", "弯", "伸", "拿", "抓", "握", "捏", "递", "接",
    "放", "推", "拉", "扯", "拽", "拍", "打", "扔", "摔", "塞", "掏", "抽", "撕", "折",
    "打开", "关上", "锁", "按", "点", "划", "写", "签", "盖", "翻", "举", "挥", "指",
    "笑", "哭", "咬", "皱眉", "沉默", "停", "进", "出", "离开", "回来", "起身", "坐下",
    "拨", "挂", "听", "喊", "问", "念", "读", "踩", "踢", "躲", "挡", "扶", "抱",
)

EMOTION_WORDS = (
    "难过", "委屈", "愤怒", "开心", "伤心", "害怕", "紧张", "尴尬", "震惊", "崩溃",
    "绝望", "无奈", "欣慰", "愧疚", "心虚", "得意", "失落", "压抑", "痛苦", "心酸",
    "感动", "焦虑", "犹豫", "不舍", "生气", "高兴", "悲伤", "不安", "惊讶", "疑惑",
    "心疼", "后悔", "羞耻", "恐惧", "激动", "平静", "冷漠", "麻木",
)

NET_LITERARY = (
    "仿佛", "宛如", "犹如", "如同", "像是", "像被", "像是被", "不禁", "不由得",
    "竟然", "居然", "瞬间", "刹那间", "心底", "内心深处", "命运", "宿命", "灵魂",
    "仿佛整个世界", "空气凝固", "时间静止",
)

WATER_WORDS = (
    "其实", "总之", "说白了", "也就是说", "不得不说", "说实话", "你知道吗", "大家",
    "众所周知", "毫无疑问", "可以这么说", "简而言之", "换言之",
)

TOO_CONVENIENT = (
    "幸好", "多亏", "正好", "恰好", "碰巧", "突然出现", "及时赶到", "凭空", "不知从哪",
    "天上掉", "白给", "自动送上门",
)

RESULT_WORDS = (
    "拿到", "签下", "曝光", "被抓", "当场", "揭穿", "转账", "辞职", "跪下", "道歉",
    "被开除", "合同", "录音", "视频", "证据", "判决", "落网", "认输", "退婚", "净身出户",
    "夺回", "冻结", "封号", "下架", "赔", "入狱", "拘留", "停职", "查封", "接管",
    "拍下", "拍照", "截下", "截图", "锁进", "存证", "存进", "解冻", "恢复", "找到",
    "查出", "调出", "画出", "写进", "写下", "指出", "还原", "证明", "播出", "投屏",
    "念出", "带走", "删掉", "撕掉", "撕了", "换回", "交出", "放回", "留下", "改口",
    "出具", "承认", "现身", "反锁", "排开", "收到", "拿回", "停单", "离席", "沉默",
)

REACTION_ONLY = (
    "愣住了", "愣住", "傻眼", "呆住", "脸色一变", "说不出话", "你等着", "等着",
    "走着瞧", "不会放过", "一定会", "早晚", "后悔吧", "冷笑", "瞪大眼",
)


def readable_len(text: str) -> int:
    return sum(1 for ch in str(text or "") if ch not in CN_PUNCT)


def cn_len(text: str) -> int:
    return readable_len(text)


def sentences(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in SENTENCE_END.split(raw) if p.strip()]
    return parts or [raw]


def sentence_count(text: str) -> int:
    return len(sentences(text))


def estimate_seconds(text: str, *, cps: float = 5.0) -> float:
    """Dialogue duration at the brief's 4–5 characters per second."""
    speed = max(3.0, min(6.0, float(cps or 5.0)))
    return max(0.6, readable_len(text) / speed)


def suggested_duration(text: str, *, cps: float = 4.5) -> float:
    return round(max(1.0, readable_len(text) / max(3.0, cps)), 1)


def has_physical_action(text: str) -> bool:
    return any(verb in str(text or "") for verb in PHYSICAL_VERBS)


def emotion_without_action(text: str) -> str:
    raw = str(text or "")
    if not any(word in raw for word in EMOTION_WORDS):
        return ""
    if has_physical_action(raw):
        return ""
    return next(word for word in EMOTION_WORDS if word in raw)


def find_all(text: str, words: tuple[str, ...]) -> list[str]:
    raw = str(text or "")
    return [word for word in words if word in raw]


def flatten_strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            out.extend(flatten_strings(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            out.extend(flatten_strings(item))
    return out


def document_text(document: dict[str, Any]) -> str:
    return "\n".join(flatten_strings(document))


def unique(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


__all__ = [
    "ACTION_PREFIX",
    "EMOTION_WORDS",
    "NET_LITERARY",
    "PHYSICAL_VERBS",
    "REACTION_ONLY",
    "RESULT_WORDS",
    "TOO_CONVENIENT",
    "WATER_WORDS",
    "cn_len",
    "document_text",
    "emotion_without_action",
    "estimate_seconds",
    "find_all",
    "flatten_strings",
    "has_physical_action",
    "readable_len",
    "sentence_count",
    "sentences",
    "suggested_duration",
    "unique",
]
