"""Topic-grounded preschool storyboards and fail-closed child-safety rules."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

STAGES = ["greeting", "problem", "try", "solve", "recap", "action", "goodbye", "interaction"]

KIDS_TOPIC_STORYBOARDS: dict[str, dict[str, Any]] = {
    "fox_turn_taking": {
        "title": "小狐狸学会轮流", "theme": "轮流与分享", "hero": "小狐狸", "friend": "小兔子",
        "pages": [
            {"title": "一起玩球吧", "scene_key": "fox_share", "beats": [
                {"stage": "greeting", "text": "嗨，小朋友！今天和小狐狸、小兔子一起玩球吧！"},
                {"stage": "problem", "text": "小兔子也想玩，可是球只有一颗，怎么办呢？"}]},
            {"title": "轮流来试试", "scene_key": "turn_taking", "beats": [
                {"stage": "try", "text": "小狐狸先抱着球，朋友们在等，它想到了一个办法。"},
                {"stage": "solve", "text": "我们分享着轮流玩吧！你一下，我一下，大家都能玩。"}]},
            {"title": "记住小办法", "scene_key": "fox_share", "beats": [
                {"stage": "recap", "text": "记住啦，分享和轮流就是排好队，一个接一个来。"},
                {"stage": "action", "text": "现在把玩具轻轻传给朋友，也请朋友传给你。"}]},
            {"title": "下次再一起玩", "scene_key": "turn_taking", "beats": [
                {"stage": "goodbye", "text": "今天玩得真开心，再见啦，小朋友！"},
                {"stage": "interaction", "text": "下次你想和谁一起玩球呢？告诉身边的大人吧！"}]},
        ],
    },
    "brush_teeth": {
        "title": "为什么要刷牙", "theme": "温和的日常刷牙习惯", "hero": "小熊", "friend": "小狐狸",
        "pages": [
            {"title": "早上好，刷牙啦", "scene_key": "brush_teeth", "beats": [
                {"stage": "greeting", "text": "早上好，小朋友！和小熊一起刷牙吧！"},
                {"stage": "problem", "text": "小熊吃完点心，牙齿上有小小的碎屑，怎么办呢？"}]},
            {"title": "轻轻刷一刷", "scene_key": "brush_teeth", "beats": [
                {"stage": "try", "text": "小熊拿起牙刷，挤一点牙膏，轻轻开始刷。"},
                {"stage": "solve", "text": "上面刷一刷，下面刷一刷，里外慢慢刷到。"}]},
            {"title": "每天的小习惯", "scene_key": "brush_teeth", "beats": [
                {"stage": "recap", "text": "记住啦，刷牙要认真，上下里外都刷到。"},
                {"stage": "action", "text": "刷完漱漱口，请大人陪你把牙齿刷干净。"}]},
            {"title": "明天也见", "scene_key": "stars_nature", "beats": [
                {"stage": "goodbye", "text": "谢谢小熊陪我们刷牙，再见啦，明天见！"},
                {"stage": "interaction", "text": "今天刷过牙了吗？告诉身边的大人吧！"}]},
        ],
    },
    "tidy_toys": {
        "title": "玩具回家啦", "theme": "温和的收纳习惯", "hero": "小狐狸", "friend": "小兔子",
        "pages": [
            {"title": "你好，小朋友", "scene_key": "tidy_up", "beats": [
                {"stage": "greeting", "text": "你好，小朋友！我们和小狐狸一起收玩具吧！"},
                {"stage": "problem", "text": "地上的积木和小球散开了，玩具该回哪里呢？"}]},
            {"title": "试着分一分", "scene_key": "tidy_up", "beats": [
                {"stage": "try", "text": "小狐狸拿起一个积木，再看看旁边的玩具盒。"},
                {"stage": "solve", "text": "积木住进积木盒，小球住进小篮子，各回各的家。"}]},
            {"title": "记住办法", "scene_key": "fox_share", "beats": [
                {"stage": "recap", "text": "记住啦，玩完玩具，我们一起把它们送回家。"},
                {"stage": "action", "text": "请你挑一件玩具，和大人一起放回原来的地方。"}]},
            {"title": "再见啦", "scene_key": "stars_nature", "beats": [
                {"stage": "goodbye", "text": "地板变整齐啦，谢谢你帮忙，再见，小朋友！"},
                {"stage": "interaction", "text": "你最喜欢收好哪一件玩具呢？说给大人听吧！"}]},
        ],
    },
    "crosswalk": {
        "title": "学会安全过马路", "theme": "在大人陪伴下安全过马路", "hero": "小猫", "friend": "小兔子",
        "pages": [
            {"title": "和大人一起出发", "scene_key": "crosswalk", "beats": [
                {"stage": "greeting", "text": "嗨，小朋友！今天和小猫跟着大人学过马路。"},
                {"stage": "problem", "text": "小猫走到路口，看到车子经过，怎么办呢？"}]},
            {"title": "先停一停", "scene_key": "crosswalk", "beats": [
                {"stage": "try", "text": "小猫先停在路边，牵好大人的手，一起看看信号灯。"},
                {"stage": "solve", "text": "等绿灯亮了，再牵着大人的手走人行横道。"}]},
            {"title": "安全小口诀", "scene_key": "crosswalk", "beats": [
                {"stage": "recap", "text": "记住啦，过马路要停一停、看信号、牵好手。"},
                {"stage": "action", "text": "请你和大人一起找找人行横道，跟着信号走。"}]},
            {"title": "再见啦", "scene_key": "crosswalk", "beats": [
                {"stage": "goodbye", "text": "跟着大人安全过马路，真棒！再见，小朋友！"},
                {"stage": "interaction", "text": "过马路时你会牵谁的手呢？告诉身边的大人吧！"}]},
        ],
    },
    "wash_hands": {
        "title": "为什么要洗手", "theme": "吃东西前和玩耍后洗手", "hero": "小熊", "friend": "小狐狸",
        "pages": [
            {"title": "你好，小朋友", "scene_key": "hand_washing", "beats": [
                {"stage": "greeting", "text": "你好，小朋友！今天和小熊一起学洗手吧！"},
                {"stage": "problem", "text": "小熊玩完积木，准备吃点心，手该怎么办呢？"}]},
            {"title": "小泡泡来帮忙", "scene_key": "hand_washing", "beats": [
                {"stage": "try", "text": "小熊先打开水龙头，弄湿双手，再抹一点肥皂。"},
                {"stage": "solve", "text": "手心手背搓一搓，指缝也搓一搓，再用清水冲干净。"}]},
            {"title": "记住好习惯", "scene_key": "hand_washing", "beats": [
                {"stage": "recap", "text": "记住啦，吃东西前要洗手，玩完也要洗手。"},
                {"stage": "action", "text": "请你和大人一起洗洗手，把小手擦干。"}]},
            {"title": "下次见", "scene_key": "hand_washing", "beats": [
                {"stage": "goodbye", "text": "小手干净啦，谢谢你一起练习，再见，小朋友！"},
                {"stage": "interaction", "text": "吃点心前，你准备先做什么呢？告诉身边的大人吧！"}]},
        ],
    },
}

BLOCKED_KIDS_TERMS = (
    "巴菲特", "暴利", "毁灭", "生死威胁", "武器", "鲜血", "恐怖", "鬼怪",
    "杀人", "惩罚", "羞辱", "坏孩子", "笨蛋", "投资回报", "复利效应",
    "复利", "资产", "投资", "财富", "股票", "暴力", "危险模仿", "自残",
    "毒品", "酗酒", "可口可乐", "迪士尼", "抖音", "广告", "收益率", "金融杠杆",
    "深入机制分析", "底层运行机制", "成人的顶级智慧", "宇宙法则", "投资收益",
)
REQUIRED_TEXT_MARKERS = {
    "greeting": ("小朋友",),
    "problem": ("怎么办", "要怎么办", "呢？"),
    "try": ("拿起", "先", "想到了"),
    "solve": ("办法", "轮流", "刷", "住进", "绿灯", "冲干净", "搓一搓"),
    "recap": ("记住",),
    "action": ("你", "请", "一起"),
    "goodbye": ("再见",),
    "interaction": ("？", "吗？", "呢？"),
}
CHARACTERS = ("小狐狸", "小兔子", "小猫", "小熊", "小狗", "小星星")
VISIBLE_TEXT_KEYS = {"title", "text", "note", "subtitle", "caption", "label"}


class UnsupportedKidsTopicError(ValueError):
    """Raised when a topic is adult-oriented or has no suitable child-safe template."""


def _replace_characters(spec: dict[str, Any], hero: str) -> None:
    default_hero = spec.get("hero", "小狐狸")
    friend = spec.get("friend", "")
    if not hero or hero == default_hero:
        return
    def swap(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: swap(item) for key, item in value.items()}
        if isinstance(value, list):
            return [swap(item) for item in value]
        if not isinstance(value, str):
            return value
        if hero == friend and friend:
            token = "__HANDDRAW_HERO__"
            return value.replace(default_hero, token).replace(friend, default_hero).replace(token, hero)
        return value.replace(default_hero, hero)
    spec["pages"] = swap(spec["pages"])
    spec["hero"] = hero


def select_kids_storyboard(topic: str) -> dict[str, Any]:
    """Route to a matching child-safe template; never silently substitute a theme."""
    raw = str(topic or "").strip()
    if not raw:
        raise UnsupportedKidsTopicError("幼儿故事必须提供具体主题；未生成默认替代故事。")
    blocked = sorted(term for term in BLOCKED_KIDS_TERMS if term in raw)
    if blocked:
        raise UnsupportedKidsTopicError(f"主题不适合 2–6 岁幼儿，已拒绝生成：{', '.join(blocked)}")
    normalized = raw.lower()
    if any(word in normalized for word in ("刷牙", "牙齿", "牙膏", "口腔", "dent")):
        key = "brush_teeth"
    elif any(word in normalized for word in ("洗手", "肥皂", "洗干净双手", "handwash")):
        key = "wash_hands"
    elif any(word in normalized for word in ("过马路", "红绿灯", "人行横道", "斑马线", "交通安全")):
        key = "crosswalk"
    elif any(word in normalized for word in ("收拾", "整理", "玩具", "tidy", "clean up")):
        key = "tidy_toys"
    elif any(word in normalized for word in ("分享", "轮流", "一起玩", "玩球", "share", "turn taking")):
        key = "fox_turn_taking"
    else:
        raise UnsupportedKidsTopicError(f"暂不支持该幼儿主题：{raw}。请选择分享/轮流、刷牙、洗手、收拾玩具或安全过马路；不会套用无关模板。")
    spec = deepcopy(KIDS_TOPIC_STORYBOARDS[key])
    requested_hero = next((name for name in CHARACTERS if name in raw), "")
    _replace_characters(spec, requested_hero)
    spec["title"] = raw if len(raw) <= 36 else KIDS_TOPIC_STORYBOARDS[key]["title"]
    spec["topic_key"] = key
    spec["stages"] = list(STAGES)
    return spec


def validate_kids_on_screen_text(texts: list[str]) -> dict[str, Any]:
    """Check all user-visible overlay/title text for adult or prohibited topics."""
    visible = [str(value) for value in texts if value is not None]
    blocked = sorted({term for term in BLOCKED_KIDS_TERMS if any(term in value for value in visible)})
    return {"checked_text_count": len(visible), "blocked_terms_found": blocked, "passed": not blocked}


def _visible_texts(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in VISIBLE_TEXT_KEYS and isinstance(item, str):
                found.append(item)
            elif isinstance(item, (dict, list)):
                found.extend(_visible_texts(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_visible_texts(item))
    return found


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
    require_audio_measurements: bool = False,
) -> dict[str, Any]:
    """Report local rule checks; missing measurements fail closed at final gate."""
    beats = [beat for page in pages for beat in page.get("beats", [])]
    script = "\n".join(str(beat.get("text") or "") for beat in beats)
    visible_texts = [topic, *_visible_texts(pages)]
    blocked = sorted({term for term in BLOCKED_KIDS_TERMS if any(term in value for value in [script, *visible_texts])})
    stages = [str(beat.get("stage") or "") for beat in beats]
    stage_sequence_ok = preview or stages == STAGES
    missing_markers = []
    for beat in beats:
        stage = str(beat.get("stage") or "")
        markers = REQUIRED_TEXT_MARKERS.get(stage, ())
        if markers and not any(marker in str(beat.get("text") or "") for marker in markers):
            missing_markers.append(stage)
    familiar_words = any(word in script for word in (*CHARACTERS, "小朋友"))
    caption_minimum = 56 if aspect == "9:16" else 48
    lufs_finite = audio_lufs is not None and __import__("math").isfinite(float(audio_lufs))
    peak_finite = true_peak_dbtp is not None and __import__("math").isfinite(float(true_peak_dbtp))
    checks = {
        "blocked_terms_absent": not blocked,
        "stage_sequence": stage_sequence_ok,
        "stage_language_markers": not missing_markers,
        "child_facing_language": familiar_words,
        "caption_font_minimum": int(caption_font_size) >= caption_minimum,
        "pace_within_3_5_chars_per_second": (characters_per_second is not None and __import__("math").isfinite(float(characters_per_second)) and characters_per_second <= 3.5) if require_audio_measurements else (characters_per_second is None or (__import__("math").isfinite(float(characters_per_second)) and characters_per_second <= 3.5)),
        "integrated_loudness_minus_16_plus_minus_1_lufs": (lufs_finite and -17.0 <= float(audio_lufs) <= -15.0) if require_audio_measurements else (audio_lufs is None or (lufs_finite and -17.0 <= float(audio_lufs) <= -15.0)),
        "true_peak_at_or_below_minus_1_5_dbtp": (peak_finite and float(true_peak_dbtp) <= -1.5) if require_audio_measurements else (true_peak_dbtp is None or (peak_finite and float(true_peak_dbtp) <= -1.5)),
        "audio_measurements_present": (lufs_finite and peak_finite) if require_audio_measurements else True,
    }
    return {
        "schema_version": 2, "gate": "kids_anime_rule_based", "review_type": "automated_only", "human_review": "pending",
        "topic": topic, "theme": "preschool_daily_life_or_social_emotional_learning", "aspect": aspect, "preview": preview,
        "beat_count": len(beats), "stage_sequence": stages, "expected_stage_sequence": STAGES,
        "blocked_terms_found": blocked, "visible_text_checked_count": len(visible_texts),
        "missing_stage_markers": missing_markers, "characters_per_second": characters_per_second,
        "audio_lufs": audio_lufs, "true_peak_dbtp": true_peak_dbtp,
        "caption_font_size": int(caption_font_size), "caption_minimum": caption_minimum,
        "checks": checks, "passed": all(checks.values()),
        "notes": ["规则筛查不等同人工审片；发布前仍需成人审核。"],
    }
