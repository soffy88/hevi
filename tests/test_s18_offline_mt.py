"""S18 offline MT fallback: glossary protection and translation self-check."""

from __future__ import annotations

from hevi.translation.offline_mt import (
    _norm,
    _protect,
    _restore,
    available,
    self_check,
)


def test_language_codes_normalise() -> None:
    assert _norm("zh-CN") == "zh"
    assert _norm("zh_CN") == "zh"
    assert _norm("en-US") == "en"
    assert _norm("JA") == "ja"


def test_glossary_placeholder_round_trip() -> None:
    protected, mapping = _protect(
        "The Dubai International Film Festival opened.", {"Dubai": "迪拜", "Film Festival": "电影节"}
    )
    assert "Dubai" not in protected
    assert "ZZG0ZZ" in protected
    restored = _restore(protected, mapping)
    assert "迪拜" in restored
    assert "电影节" in restored


def test_self_check_accepts_a_plausible_translation() -> None:
    source = ["Do you know the Dubai film festival?", "It opened last night."]
    translated = ["你知道迪拜电影节吗？", "它在昨晚开幕。"]
    back = ["Do you know the Dubai film festival?", "It opened last night."]
    check = self_check(source, translated, back=back, to_lang="zh-CN")
    assert check["pass"] is True
    assert check["cjk_ratio"] >= 0.5
    assert check["back_translation_overlap"] and check["back_translation_overlap"] > 0.5


def test_self_check_flags_missing_target_script_and_empty_lines() -> None:
    source = ["Hello world"]
    check = self_check(source, ["Hello world"], back=["Hello world"], to_lang="zh-CN")
    assert check["pass"] is False
    assert "target_script_missing" in check["problems"]
    empty = self_check(source, [""], back=None, to_lang="zh-CN")
    assert empty["pass"] is False
    assert "empty_or_missing_lines" in empty["problems"]


def test_self_check_flags_backtranslation_mismatch() -> None:
    check = self_check(["Hello world"], ["完全无关的句子"], back=["completely unrelated"], to_lang="zh-CN")
    assert check["pass"] is False
    assert "backtranslation_mismatch" in check["problems"]


def test_offline_models_present_on_host() -> None:
    # The black-box host installs both directions; a CI box without them should
    # not fail the suite.
    if not available("en", "zh"):
        import pytest

        pytest.skip("offline en->zh model not installed")
    assert available("en", "zh")
