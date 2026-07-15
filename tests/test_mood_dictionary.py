"""抽象词→具象现象词典测试(HEVI 路线图 Phase3 #38)。"""

from __future__ import annotations

from hevi.style.mood_dictionary import (
    ABSTRACT_TO_CONCRETE,
    expand_mood_to_concrete,
    list_known_moods,
)


def test_known_mood_expands_to_concrete_phenomena():
    r = expand_mood_to_concrete("温馨")
    assert r != "温馨"
    assert "steam" in r or "shadow" in r or "clothesline" in r


def test_unknown_mood_returned_unchanged():
    assert expand_mood_to_concrete("一个不存在的情绪词") == "一个不存在的情绪词"


def test_empty_mood_returned_unchanged():
    assert expand_mood_to_concrete("") == ""


def test_list_known_moods_matches_dict_keys():
    assert list_known_moods() == list(ABSTRACT_TO_CONCRETE)
