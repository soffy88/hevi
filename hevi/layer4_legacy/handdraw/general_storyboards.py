"""General-audience handdraw storyboard.

The legacy handdraw line only knew preschool story templates and forced an
arbitrary topic into one of them.  This builder turns an arbitrary topic into a
neutral 8-beat explainer storyboard (no "小朋友", no child-safety markers) and
picks an existing illustration scene key by keyword.  Child topics still route
through ``kids_storyboards`` when the caller asks for the kids audience.
"""

from __future__ import annotations

from typing import Any

GENERAL_STAGES = (
    "hook", "context", "problem", "try", "solve", "example", "recap", "close",
)

# The same routing keywords the kids line uses.  A topic that matches one of
# these is still a child topic; anything else is general.
KIDS_KEYWORDS = (
    "刷牙", "牙齿", "牙膏", "口腔",
    "洗手", "肥皂",
    "过马路", "红绿灯", "人行横道", "斑马线", "交通安全",
    "收拾", "整理", "玩具",
    "分享", "轮流", "一起玩", "玩球",
    "不怕黑", "怕黑", "害怕", "夜晚", "夜里", "黑暗",
    "睡前", "睡觉", "睡不着", "晚安",
    "谢谢", "感谢", "感恩",
    "难过", "伤心",
    "对不起", "道歉",
    "生气", "发脾气", "情绪",
    "种子", "植物", "自然", "发芽", "昆虫", "星星", "月亮",
    "勇敢", "尝试", "新本领", "不放弃",
    "朋友", "友谊", "合作", "家人",
    "小朋友", "孩子", "儿童", "幼儿",
)

SCENE_ROUTES = (
    ("钱", "coin_pyramid"), ("投资", "coin_pyramid"), ("价格", "coin_pyramid"),
    ("增长", "growth_curves"), ("数据", "growth_curves"), ("趋势", "growth_curves"),
    ("选择", "balance_scale"), ("公平", "balance_scale"), ("权衡", "balance_scale"),
    ("情绪", "feelings"), ("决定", "calm_decision"), ("判断", "calm_decision"),
    ("勇气", "cat_courage"), ("怕", "cat_courage"),
    ("自然", "stars_nature"), ("宇宙", "stars_nature"), ("科学", "stars_nature"),
)


def is_kids_topic(topic: str) -> bool:
    text = str(topic or "")
    return any(word in text for word in KIDS_KEYWORDS)


def scene_key_for(topic: str) -> str:
    text = str(topic or "")
    for word, key in SCENE_ROUTES:
        if word in text:
            return key
    return "stars_nature"


def build_general_storyboard(topic: str) -> dict[str, Any]:
    raw = str(topic or "").strip()
    if not raw:
        raise ValueError("手绘讲解需要具体主题；未生成默认故事。")
    subject = raw if len(raw) <= 36 else raw[:36]
    texts = [
        ("hook", f"先用一句话说清：{subject}。"),
        ("context", "这件事天天出现，但多数人只看到表面。"),
        ("problem", f"真正的问题是：{subject}为什么会这样？"),
        ("try", "先从最直观的一步看，再往下拆。"),
        ("solve", "关键在机制，不在名词；把因果摆出来就清楚了。"),
        ("example", f"放回现实里，{subject}就在我们身边。"),
        ("recap", f"记住这一点：{subject}不是玄学。"),
        ("close", "下一集，我们接着拆下一层。"),
    ]
    pages = []
    for index in range(4):
        beats = [
            {"stage": texts[index * 2][0], "text": texts[index * 2][1]},
            {"stage": texts[index * 2 + 1][0], "text": texts[index * 2 + 1][1]},
        ]
        pages.append({
            "title": f"{index + 1}. {subject}",
            "scene_key": scene_key_for(raw),
            "beats": beats,
        })
    return {
        "title": subject,
        "theme": subject,
        "hero": "",
        "friend": "",
        "pages": pages,
        "topic_key": "general",
        "stages": list(GENERAL_STAGES),
        "audience": "general",
    }
