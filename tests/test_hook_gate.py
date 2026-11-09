"""S17: opening hook gate + voice-before-storyboard wiring."""

from __future__ import annotations

from hevi.qa.hook_gate import check_hook, ensure_opening_hook, rewrite_opening


def test_strong_opening_passes():
    report = check_hook("16岁被卖进戏班，25岁吞药离世，30万人为她送葬。她叫阮玲玉。")
    assert report["pass"], report
    assert {"concrete_anchor", "conflict_or_reversal"} <= set(report["signals"])


def test_generic_preamble_fails():
    report = check_hook("大家好，今天我们来聊聊人工智能。它很重要。")
    assert not report["pass"]
    assert any(i["code"] == "generic_preamble" for i in report["issues"])


def test_rewrite_only_changes_the_opening():
    text = "大家好，今天我们来聊聊咖啡。第二句保留。第三句也保留。"
    out = ensure_opening_hook(text, topic="咖啡")
    assert out["rewritten"]
    assert out["text"].endswith("第二句保留。第三句也保留。")
    assert out["text"].split("。")[0] != "大家好，今天我们来聊聊咖啡"
    assert out["recheck"]["pass"], out["recheck"]


def test_rewrite_does_not_invent_numbers():
    text = "今天聊聊咖啡。它很常见。"
    out = rewrite_opening(text, topic="咖啡")
    assert "咖啡" in out["opening"]
    assert not any(ch.isdigit() for ch in out["opening"])


def test_rewrite_keeps_a_strong_opening_untouched():
    text = "第一秒就不对劲：他递出的不是钥匙。后面照旧。"
    out = rewrite_opening(text, topic="钥匙")
    assert out["changed"] is False
    assert out["text"] == text
