"""新手 10 秒模板：一句话 + 一个图形变化 + 一首音乐。

默认入门模板，不替代完整逐拍脚本；它同样走脚本自检与零件库。
"""

from __future__ import annotations

from typing import Any

from hevi.explainer.warmgold import parts as parts_mod


def build_10s(
    sentence: str,
    *,
    part_id: str = "random_walk",
    anchor_object: str = "手机屏幕",
    params: dict[str, Any] | None = None,
    bpm: float = 120.0,
) -> dict[str, Any]:
    if part_id not in parts_mod.PARTS_BY_ID:
        raise KeyError(part_id)
    sentence = sentence.strip() or "越着急，越看不清"
    shots = [
        {
            "id": "s1",
            "role": "problem",
            "beats": 4,
            "visual": part_id,
            "params": params or {"seed": 3},
            "big": sentence[:10],
            "small": sentence,
            "narration": "你有没有过这种时候",
            "sfx": "ding",
            "focus": "一句话",
        },
        {
            "id": "s2",
            "role": "example",
            "beats": 8,
            "visual": part_id,
            "params": params or {"seed": 3},
            "big": "只看一眼",
            "small": "画面动起来，读数在变",
            "narration": "先别下结论，看它在动。",
            "sfx": "pop",
            "focus": "一个变化",
            "example": {
                "visible_reading": "读数在变",
                "invisible_change": "每一步都随机",
                "jump_moment": "走到某一步才看出来",
                "supports_theme": True,
            },
        },
        {
            "id": "s3",
            "role": "ending",
            "beats": 8,
            "visual": part_id,
            "params": params or {"seed": 3},
            "big": sentence[:10],
            "small": "回到你手里的那件事",
            "narration": "回到你手里的那件事。",
            "sfx": "chime",
            "focus": "回收开头",
        },
    ]
    return {
        "schema": "hevi.warmgold.script/1",
        "template": "10s",
        "topic": sentence,
        "bpm": bpm,
        "anchor": {"object": anchor_object, "daily": True},
        "opening": {"personal_detail": "你每天都会遇到的那一下", "has_you": True},
        "shots": shots,
        "ending": {
            "recall_object": anchor_object,
            "cta": "comment",
            "cta_text": "你最近一次有这种感觉，是在什么时候？",
            "recovers_opening": True,
        },
        "numbers": [{"value": "示意", "source": "示意"}],
        "low_point_shot": "s2",
        "payoff_shot": "s3",
        "target_seconds": 10,
    }
