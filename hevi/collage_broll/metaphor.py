"""隐喻卡生成（LLM + 确定性回退）。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

COLORS = {
    "time": ("焦橙", "#E86A33"),
    "tool": ("芥末黄", "#D9A441"),
    "cognition": ("墨绿", "#2F5D50"),
    "norm": ("深紫", "#4A3B6B"),
    "collab": ("青绿", "#3FA7A0"),
}

KEYWORDS = {
    "time": ["时间", "重复", "消耗", "劳动", "紧迫", "流程", "效率"],
    "tool": ["工具", "警示", "漏", "经验", "技巧"],
    "cognition": ["认知", "审美", "理解", "思考", "概念"],
    "norm": ["规范", "沉淀", "长期", "记忆", "规则", "标准"],
    "collab": ["协作", "判断", "自动", "分工", "团队"],
}


def _color_for(text: str) -> tuple[str, str, str]:
    low = text.lower()
    for key, words in KEYWORDS.items():
        if any(w in text for w in words):
            name, hexv = COLORS[key]
            return key, name, hexv
    # deterministic hash fallback
    h = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)
    key = list(COLORS.keys())[h % len(COLORS)]
    name, hexv = COLORS[key]
    return key, name, hexv


def _objects_for(text: str) -> list[str]:
    # simple noun-ish extraction: split by common punctuation and take chunks
    import re

    chunks = re.split(r"[，。、,;；:：\s]+", text)
    objs = [c for c in chunks if 1 < len(c) <= 6]
    if len(objs) < 3:
        # pad with generic
        base = ["主体", "结构", "连接件", "结果"]
        objs = (objs + base)[:6]
    return objs[:6] if len(objs) >= 3 else (objs + ["物件A", "物件B", "物件C"])[:6]


def generate_metaphor(sentence: str, index: int = 0, total: int = 1) -> dict[str, Any]:
    """Generate a metaphor card for one sentence."""
    key, color_name, hexv = _color_for(sentence)
    objs = _objects_for(sentence)
    core = sentence.strip()[:40] if sentence.strip() else "核心意思"
    visual = f"以{color_name}色场为底，用黑白半调剪片与彩色卡纸拼贴表达：{core}"
    order = "结构 → 主体/卡片 → 连接件 → 动作 → 结果"
    if total > 1:
        # narrative progression hint
        if index == 0:
            order = "消耗/经验流失 → 主体 → 结果（前段）"
        elif index == total - 1:
            order = "规范/沉淀 → 协作 → 自动执行（后段）"
    return {
        "index": index,
        "sentence": sentence,
        "core_meaning": core,
        "emotion": "冷静",
        "visual_proposition": visual,
        "key_objects": objs,
        "color_key": key,
        "color_name": color_name,
        "background_hex": hexv,
        "accent_colors": ["#F5EFE0", "#2B2B2B"],
        "assembly_order": order,
    }


def generate_metaphors(sentences: list[str], confirm: bool = False) -> list[dict[str, Any]]:
    out = [generate_metaphor(s, i, len(sentences)) for i, s in enumerate(sentences)]
    if confirm:
        # gate: would prompt; here auto-pass
        pass
    return out


def try_llm_metaphor(sentence: str) -> dict[str, Any] | None:
    """Optional LLM enhancement; returns None if unavailable."""
    try:
        from hevi.llm.monid_chat import monid_key_available, chat_sync

        if not monid_key_available():
            return None
        prompt = (
            "把这句话压成一个视觉隐喻，输出 JSON：core_meaning, visual_proposition, "
            "key_objects(3-6), color_key(time/tool/cognition/norm/collab), assembly_order. "
            f"句子：{sentence}"
        )
        raw = chat_sync(prompt)
        data = json.loads(raw)
        km = data.get("color_key", "time")
        name, hexv = COLORS.get(km, COLORS["time"])
        data.setdefault("color_name", name)
        data.setdefault("background_hex", hexv)
        data.setdefault("accent_colors", ["#F5EFE0", "#2B2B2B"])
        data.setdefault("emotion", "冷静")
        data.setdefault("sentence", sentence)
        return data
    except Exception:
        return None
