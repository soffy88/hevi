"""prosody 测试 —— 韵律规划层(差距 B3)。

覆盖: 分句/停顿分级/重音/语速/情绪提示/中英双语言/空输入/cue 转换/SRT 合并。
"""

from __future__ import annotations

from hevi.audio.prosody import (
    analyze_prosody,
    merge_with_srt,
    plan_to_cues,
)


def test_sentence_split_and_pause():
    plan = analyze_prosody("你好。世界很大！真的吗？")
    texts = [u.text for u in plan.units]
    assert texts == ["你好。", "世界很大！", "真的吗？"]
    assert plan.units[0].pause_ms == 600  # 。
    assert plan.units[1].pause_ms == 500  # ！
    assert plan.units[2].pause_ms == 500  # ？


def test_comma_is_not_sentence_break():
    plan = analyze_prosody("风很大，雨也大。")
    assert len(plan.units) == 1
    assert plan.units[0].text == "风很大，雨也大。"
    assert plan.units[0].pause_ms == 600


def test_emphasis_quoted_words():
    plan = analyze_prosody('他说“必须”离开。')
    assert "必须" in plan.units[0].emphasis


def test_emphasis_zh_keywords():
    plan = analyze_prosody("我们绝对不能再犯同样的错误。")
    assert "绝对" in plan.units[0].emphasis


def test_emphasis_en_keywords():
    plan = analyze_prosody("We must never repeat this.", lang="en")
    assert "must" in plan.units[0].emphasis
    assert "never" in plan.units[0].emphasis


def test_speed_by_length():
    plan = analyze_prosody("短。")
    assert plan.units[0].speed > 1.0
    plan2 = analyze_prosody("这是一个特别特别长的句子，它超过了二十八个字符的长度限制，所以应该降速。")
    assert plan2.units[0].speed < 1.0


def test_base_speed_scaling():
    plan = analyze_prosody("短。", base_speed=0.8)
    assert plan.units[0].speed == round(1.05 * 0.8, 3)


def test_tone_hint():
    plan = analyze_prosody("快跑！")
    assert plan.units[0].tone == "urgent"
    plan2 = analyze_prosody("你好。")
    assert plan2.units[0].tone in ("happy", "neutral")


def test_empty_input():
    plan = analyze_prosody("   ")
    assert plan.units == []
    assert plan_to_cues(plan) == []


def test_plan_to_cues_shape():
    plan = analyze_prosody("快点。")
    cues = plan_to_cues(plan)
    assert cues[0]["text"] == "快点。"
    assert {"text", "pause_ms", "speed", "emphasis", "tone"} <= set(cues[0])


def test_merge_with_srt_matches():
    plan = analyze_prosody("你好。世界很大。")
    segments = [
        {"text": "你好。", "start": 0.0, "end": 1.2},
        {"text": "世界很大。", "start": 1.3, "end": 2.6},
    ]
    merged = merge_with_srt(plan, segments)
    assert len(merged) == 2
    assert all(m.get("pause_ms") is not None for m in merged)
    assert merged[0]["pause_ms"] == 600


def test_merge_with_srt_partial_match():
    plan = analyze_prosody("第一句。第二句。第三句。")
    segments = [{"text": "第一句。", "start": 0.0, "end": 1.0}]
    merged = merge_with_srt(plan, segments)
    assert len(merged) == 1
    assert merged[0]["prosody_matched"] is not False
    # 未配对段保持原样且标记
    segments2 = [{"text": "未知段", "start": 0.0, "end": 1.0}]
    merged2 = merge_with_srt(plan, segments2)
    assert merged2[0]["prosody_matched"] is False


def test_newline_blank_becomes_pause():
    plan = analyze_prosody("第一段。\n\n第二段。")
    texts = [u.text for u in plan.units]
    assert len(texts) == 2
    assert texts[1] == "第二段。"
