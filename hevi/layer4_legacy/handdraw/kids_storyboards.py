"""Preschool-safe, topic-grounded handdraw storyboards and rule-based gates."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

KIDS_TOPIC_STORYBOARDS: dict[str, dict[str, Any]] = {
    "fox_turn_taking": {
        "title": "小狐狸学会轮流",
        "theme": "轮流与分享",
        "stages": ["greeting", "problem", "try", "solve", "recap", "action", "goodbye", "interaction"],
        "pages": [
            {"title": "一起玩球吧", "scene_key": "fox_share", "beats": [
                {"stage": "greeting", "text": "嗨，小朋友！今天和小狐狸一起玩球吧！"},
                {"stage": "problem", "text": "小兔子也想玩，可是球只有一颗，怎么办呢？"},
            ]},
            {"title": "轮流来试试", "scene_key": "turn_taking", "beats": [
                {"stage": "try", "text": "小狐狸先抱着球，朋友们在等，它想到了一个办法。"},
                {"stage": "solve", "text": "我们轮流玩吧！你一下，我一下，大家都能玩。"},
            ]},
            {"title": "记住小办法", "scene_key": "fox_share", "beats": [
                {"stage": "recap", "text": "记住啦，轮流就是排好队，一个接一个来。"},
                {"stage": "action", "text": "现在把玩具轻轻传给朋友，也请朋友传给你。"},
            ]},
            {"title": "下次再一起玩", "scene_key": "turn_taking", "beats": [
                {"stage": "goodbye", "text": "今天玩得真开心，再见啦，小朋友！"},
                {"stage": "interaction", "text": "下次你想和谁一起玩球呢？告诉身边的大人吧！"},
            ]},
        ],
    },
    "brush_teeth": {
        "title": "为什么要刷牙",
        "theme": "温和的日常刷牙习惯",
        "stages": ["greeting", "problem", "try", "solve", "recap", "action", "goodbye", "interaction"],
        "pages": [
            {"title": "早上好，刷牙啦", "scene_key": "brush_teeth", "beats": [
                {"stage": "greeting", "text": "早上好，小朋友！今天和小熊一起刷刷牙吧！"},
                {"stage": "problem", "text": "小熊吃过点心，牙齿上有小小的碎屑，要怎么办呢？"},
            ]},
            {"title": "轻轻刷一刷", "scene_key": "brush_teeth", "beats": [
                {"stage": "try", "text": "小熊拿起小牙刷，挤一点点牙膏，轻轻开始刷。"},
                {"stage": "solve", "text": "上面刷一刷，下面刷一刷，里面外面都慢慢刷到。"},
            ]},
            {"title": "每天的小习惯", "scene_key": "brush_teeth", "beats": [
                {"stage": "recap", "text": "记住啦，刷牙要认真，上下里外都照顾到。"},
                {"stage": "action", "text": "刷完后漱漱口，请大人陪你把小牙齿刷干净。"},
            ]},
            {"title": "明天也见", "scene_key": "stars_nature", "beats": [
                {"stage": "goodbye", "text": "谢谢小熊陪我们刷牙，再见啦，明天见！"},
                {"stage": "interaction", "text": "你今天刷过牙了吗？可以跟身边的大人说一说。"},
            ]},
        ],
    },
    "tidy_toys": {
        "title": "玩具回家啦",
        "theme": "温和的收纳习惯",
        "stages": ["greeting", "problem", "try", "solve", "recap", "action", "goodbye", "interaction"],
        "pages": [
            {"title": "你好，小朋友", "scene_key": "tidy_up", "beats": [
                {"stage": "greeting", "text": "你好，小朋友！我们和小狐狸一起收玩具吧！"},
                {"stage": "problem", "text": "地上的积木和小球散开了，玩具该回哪里呢？"},
            ]},
            {"title": "试着分一分", "scene_key": "tidy_up", "beats": [
                {"stage": "try", "text": "小狐狸拿起一个积木，再看看旁边的玩具盒。"},
                {"stage": "solve", "text": "积木住进积木盒，小球住进小篮子，各回各的家。"},
            ]},
            {"title": "记住办法", "scene_key": "fox_share", "beats": [
                {"stage": "recap", "text": "记住啦，玩完玩具，我们一起把它们送回家。"},
                {"stage": "action", "text": "请你挑一件玩具，和大人一起放回原来的地方。"},
            ]},
            {"title": "再见啦", "scene_key": "stars_nature", "beats": [
                {"stage": "goodbye", "text": "地板变整齐啦，谢谢你帮忙，再见，小朋友！"},
                {"stage": "interaction", "text": "你最喜欢收好哪一件玩具呢？说给大人听吧！"},
            ]},
        ],
    },
}

BLOCKED_KIDS_TERMS = (
    "巴菲特", "暴利", "毁灭", "生死威胁", "武器", "鲜血", "恐怖", "鬼怪",
    "杀人", "惩罚", "羞辱", "坏孩子", "笨蛋", "投资回报", "复利效应",
    "复利", "资产", "投资", "财富", "股票", "暴力", "危险模仿",
    "自残", "毒品", "酗酒", "可口可乐", "迪士尼", "抖音", "广告",
)
REQUIRED_TEXT_MARKERS = {
    "greeting": ("小朋友",),
    "problem": ("怎么办", "要怎么办", "呢？"),
    "try": ("拿起", "先", "想到了"),
    "solve": ("轮流", "刷", "住进"),
    "recap": ("记住",),
    "action": ("你", "请", "一起"),
    "goodbye": ("再见",),
    "interaction": ("？", "吗？", "呢？"),
}


def select_kids_storyboard(topic: str) -> dict[str, Any]:
    """Select a deterministic preschool template grounded in the requested topic."""
    raw = str(topic or "").strip()
    normalized = raw.lower()
    if not raw:
        key = "fox_turn_taking"
    elif any(word in normalized for word in ("刷牙", "牙齿", "牙膏", "口腔", "dent")):
        key = "brush_teeth"
    elif any(word in normalized for word in ("收拾", "整理", "玩具", "tidy", "clean up")):
        key = "tidy_toys"
    else:
        key = "fox_turn_taking"
    spec = deepcopy(KIDS_TOPIC_STORYBOARDS[key])
    if raw and len(raw) <= 36:
        spec["title"] = raw
    spec["topic_key"] = key
    return spec


def validate_kids_script(
    topic: str,
    pages: list[dict[str, Any]],
    *,
    aspect: str,
    caption_font_size: int,
    characters_per_second: float | None = None,
    audio_lufs: float | None = None,
    true_peak_dbtp: float | None = None,
    preview: bool = False,
) -> dict[str, Any]:
    """Report local automated checks without claiming human review."""
    beats = [beat for page in pages for beat in page.get("beats", [])]
    script = "\n".join(str(beat.get("text") or "") for beat in beats)
    blocked = sorted({term for term in BLOCKED_KIDS_TERMS if term in script or term in topic})
    stages = [str(beat.get("stage") or "") for beat in beats]
    expected = KIDS_TOPIC_STORYBOARDS["fox_turn_taking"]["stages"]
    stage_sequence_ok = preview or stages == expected
    missing_markers = []
    for beat in beats:
        stage = str(beat.get("stage") or "")
        markers = REQUIRED_TEXT_MARKERS.get(stage, ())
        if markers and not any(marker in str(beat.get("text") or "") for marker in markers):
            missing_markers.append(stage)
    familiar_words = any(word in script for word in ("小朋友", "小狐狸", "小熊", "小兔子"))
    caption_minimum = 56 if aspect == "9:16" else 48
    checks = {
        "blocked_terms_absent": not blocked,
        "stage_sequence": stage_sequence_ok,
        "stage_language_markers": not missing_markers,
        "child_facing_language": familiar_words,
        "caption_font_minimum": int(caption_font_size) >= caption_minimum,
        "pace_within_3_5_chars_per_second": characters_per_second is None or characters_per_second <= 3.5,
        "integrated_loudness_minus_16_plus_minus_1_lufs": audio_lufs is None or -17.0 <= audio_lufs <= -15.0,
        "true_peak_at_or_below_minus_1_5_dbtp": true_peak_dbtp is None or true_peak_dbtp <= -1.5,
    }
    return {
        "schema_version": 1,
        "gate": "kids_anime_rule_based",
        "review_type": "automated_only",
        "human_review": "pending",
        "topic": topic,
        "theme": "preschool_daily_life_or_social_emotional_learning",
        "aspect": aspect,
        "preview": preview,
        "beat_count": len(beats),
        "stage_sequence": stages,
        "expected_stage_sequence": expected,
        "blocked_terms_found": blocked,
        "missing_stage_markers": missing_markers,
        "characters_per_second": characters_per_second,
        "audio_lufs": audio_lufs,
        "true_peak_dbtp": true_peak_dbtp,
        "caption_font_size": int(caption_font_size),
        "caption_minimum": caption_minimum,
        "checks": checks,
        "passed": all(checks.values()),
        "notes": ["规则筛查不等同人工审片；发布前仍需成人审核。"],
    }
