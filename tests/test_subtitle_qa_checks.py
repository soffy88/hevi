"""Offline unit tests for the W3 subtitle QA checks.

Covers: cue readability (CPS / minimum duration), no-spoiler early-start
assertion, and ASR critical-word errors (negations / numbers).  Pure data
only -- no models, no ffmpeg, no network.
"""

from __future__ import annotations

import pytest

from hevi.assembly.subtitle_timeline_atoms import (
    CueMs,
    check_cue_early_start,
    normalize_cues,
    validate_cue_readability,
    validate_srt,
)
from hevi.audio.asr_verify import critical_word_errors, verify_and_retry

# ---------------------------------------------------------------- readability


def test_readability_passes_comfortable_cue() -> None:
    assert validate_cue_readability([CueMs(0, 2000, "你好世界")]) == []


def test_readability_flags_too_fast_cjk() -> None:
    violations = validate_cue_readability([CueMs(0, 1000, "这是一个非常长的字幕句子需要慢慢读才行")])
    assert [v["kind"] for v in violations] == ["cps_exceeded"]
    assert violations[0]["cjk_chars"] > 15
    assert violations[0]["required_duration_s"] > 1.0


def test_readability_flags_min_duration_only() -> None:
    violations = validate_cue_readability([CueMs(0, 500, "你好")])
    assert [v["kind"] for v in violations] == ["duration_too_short"]


def test_readability_flags_zero_duration() -> None:
    violations = validate_cue_readability([CueMs(1000, 1000, "你好")])
    assert [v["kind"] for v in violations] == ["non_positive_duration"]


def test_readability_latin_uses_latin_limit() -> None:
    fast = validate_cue_readability([CueMs(0, 1000, "a" * 45)])
    assert [v["kind"] for v in fast] == ["cps_exceeded"]
    assert fast[0]["latin_chars"] == 45
    # Same length in CJK would be judged against the tighter CJK limit.
    ok = validate_cue_readability([CueMs(0, 1000, "hello world this is fine")])
    assert ok == []


def test_readability_thresholds_are_parameters() -> None:
    cue = CueMs(0, 1000, "这是一个非常长的字幕句子需要慢慢读才行")
    assert validate_cue_readability([cue], max_cps=30.0) == []
    short = CueMs(0, 500, "你好")
    assert validate_cue_readability([short], min_dur_s=0.4) == []
    with pytest.raises(ValueError):
        validate_cue_readability([cue], max_cps=0)


def test_readability_accepts_dict_cues_in_seconds() -> None:
    violations = validate_cue_readability([{"start": 0.0, "end": 0.5, "text": "你好"}])
    assert [v["kind"] for v in violations] == ["duration_too_short"]
    assert violations[0]["start_ms"] == 0 and violations[0]["end_ms"] == 500


def test_normalize_cues_readability_is_opt_in() -> None:
    raw = [{"start_ms": 0, "end_ms": 500, "text": "你好"}]
    # Default: historical behaviour, unreadable-but-valid cues pass through.
    assert normalize_cues(raw, audio_duration_ms=1000) == [CueMs(0, 500, "你好")]
    with pytest.raises(ValueError, match="readability"):
        normalize_cues(raw, audio_duration_ms=1000, strict_readability=True)


def test_validate_srt_readability_is_opt_in() -> None:
    srt = "1\n00:00:00,000 --> 00:00:00,500\n你好\n"
    assert validate_srt(srt, audio_duration_ms=1000) == [CueMs(0, 500, "你好")]
    with pytest.raises(ValueError, match="readability"):
        validate_srt(srt, audio_duration_ms=1000, strict_readability=True)


# ------------------------------------------------------------- early start

_WORDS = [
    {"word": "你好", "start": 1.0, "end": 1.4},
    {"word": "世界", "start": 1.5, "end": 2.0},
    {"word": "再见", "start": 3.0, "end": 3.5},
]


def test_early_start_flags_spoiler_cue() -> None:
    violations = check_cue_early_start([CueMs(900, 2000, "你好世界")], _WORDS)
    assert len(violations) == 1
    v = violations[0]
    assert v["kind"] == "early_start"
    assert v["cue_start_s"] == 0.9 and v["first_word_start_s"] == 1.0
    assert v["early_by_s"] == pytest.approx(0.1)


def test_early_start_passes_on_time_and_within_tolerance() -> None:
    assert check_cue_early_start([CueMs(1000, 2000, "你好世界")], _WORDS) == []
    # 30 ms early is inside the default 50 ms tolerance.
    assert check_cue_early_start([CueMs(970, 2000, "你好世界")], _WORDS) == []
    violations = check_cue_early_start(
        [CueMs(970, 2000, "你好世界")], _WORDS, tolerance_s=0.01
    )
    assert len(violations) == 1


def test_early_start_matches_each_cue_to_its_own_words() -> None:
    cues = [CueMs(1000, 1400, "你好"), CueMs(2500, 3400, "再见")]
    violations = check_cue_early_start(cues, _WORDS)
    assert len(violations) == 1
    assert violations[0]["index"] == 1
    assert violations[0]["first_word"] == "再见"


def test_early_start_unmatched_cue_is_skipped_not_flagged() -> None:
    assert check_cue_early_start([CueMs(0, 500, "完全不存在的台词")], _WORDS) == []


def test_early_start_supports_ms_word_timestamps_and_second_dict_cues() -> None:
    words = [{"word": "hello", "start_ms": 2000, "end_ms": 2400}]
    violations = check_cue_early_start([{"start": 1.0, "end": 2.4, "text": "Hello!"}], words)
    assert len(violations) == 1
    assert violations[0]["first_word_start_s"] == 2.0


# ---------------------------------------------------------- critical words


def test_critical_words_pass_when_negations_and_numbers_match() -> None:
    result = critical_word_errors("我没有买过120元的票", "我没有买过120元的票")
    assert result["passed"] is True
    assert result["errors"] == []
    assert result["numbers"]["reference"] == ["120"]


def test_critical_words_flags_dropped_negation() -> None:
    result = critical_word_errors("我没有去过那里", "我有去过那里")
    assert result["passed"] is False
    assert result["negations"]["mismatches"] == [
        {"word": "没", "reference_count": 1, "hypothesis_count": 0, "delta": -1}
    ]
    assert any("没" in error for error in result["errors"])


def test_critical_words_flags_inserted_negation() -> None:
    result = critical_word_errors("明天我们去公园", "明天我们不去公园")
    assert result["passed"] is False
    assert result["negations"]["mismatches"][0]["word"] == "不"


def test_critical_words_flags_arabic_number_change() -> None:
    result = critical_word_errors("票价是120元", "票价是12元")
    assert result["passed"] is False
    assert result["numbers"]["reference"] == ["120"]
    assert result["numbers"]["hypothesis"] == ["12"]
    assert result["numbers"]["first_mismatch_index"] == 0


def test_critical_words_treats_chinese_and_arabic_spellings_as_equal() -> None:
    result = critical_word_errors("总计一千二百元，二零二六年出发", "总计1200元，2026年出发")
    assert result["numbers"]["reference"] == ["1200", "2026"]
    assert result["numbers"]["match"] is True
    assert result["passed"] is True


def test_critical_words_flags_chinese_number_change_and_percent() -> None:
    result = critical_word_errors("二十三人增长了120%", "三十二人增长了12%")
    assert result["passed"] is False
    assert result["numbers"]["reference"] == ["23", "120%"]
    assert result["numbers"]["hypothesis"] == ["32", "12%"]


async def test_verify_and_retry_attaches_critical_words_without_changing_cer_gate(
    tmp_path,
) -> None:
    audio = tmp_path / "line.wav"
    audio.write_bytes(b"audio")
    reference = "我们今天一起去公园散步然后去市场买了很多新鲜的水果和蔬菜最后回家一起做饭没有剩下任何东西大家都吃得很开心也很满足"
    hypothesis = reference.replace("没", "", 1)  # 1 char in a long line: CER < 2%

    async def asr(_path):
        return {"text": hypothesis, "words": []}

    result = await verify_and_retry(reference, audio, asr=asr, retries=0)
    assert result["passed"] is True  # CER gate unchanged (backward compatible)
    assert result["cer"] < 0.02
    assert result["critical_words"]["passed"] is False
    assert result["critical_words"]["negations"]["mismatches"][0]["word"] == "没"
