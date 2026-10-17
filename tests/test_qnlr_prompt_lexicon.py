"""prompt_lexicon 作用域隔离守卫单测——角色提示禁用材质类建筑词。"""

from __future__ import annotations

import pytest

from hevi.qnlr.prompt_lexicon import (
    assert_no_building_words,
    build_character_prompt,
)


def test_building_word_in_character_prompt_rejected() -> None:
    # 事故复现：austere / black-lacquer 串进角色域。
    with pytest.raises(ValueError, match="材质类建筑词"):
        build_character_prompt("a king in austere black-lacquer robe")
    with pytest.raises(ValueError, match="材质类建筑词"):
        assert_no_building_words("terracotta bronze statue face")


def test_clean_character_prompt_passes_and_has_realism_anchor() -> None:
    p = build_character_prompt("a 32-year-old king of Qin, authoritative gaze, dark robe and cap")
    assert "skin" in p and "catchlight" in p  # 写实锚在
    assert "terracotta" not in p.lower() and "statue" not in p.lower()
    # ★ 写实锚必须前置（CLIP 77 token 截断，排后会被丢弃）
    assert p.startswith("color photograph"), "写实锚未前置——会被 CLIP 截断丢弃"


def test_color_words_not_falsely_blocked() -> None:
    # "black"(色) 允许；"black-lacquer"(材质) 禁——边界不误伤颜色。
    assert_no_building_words("a dark black robe, muted earth tones")  # 不抛
