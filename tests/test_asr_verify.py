from __future__ import annotations

import pytest

from hevi.audio.asr_verify import (
    AsrVerificationError,
    chunk_word_timestamps_for_mobile,
    normalize_text_for_asr,
    verify_and_retry,
)


def test_normalize_text_for_asr_handles_digits_percentages_and_punctuation() -> None:
    assert normalize_text_for_asr("2026年，增长120%！") == "二零二六年增长百分之一百二十"


def test_mobile_subtitle_chunks_respect_width() -> None:
    words = [
        {"word": word, "start_ms": i * 100, "end_ms": (i + 1) * 100}
        for i, word in enumerate("一二三四五六七八九十十一十二十三")
    ]
    lines = chunk_word_timestamps_for_mobile(words, max_chars_per_line=12)
    assert all(len(line["text"]) <= 12 for line in lines)
    assert "".join(line["text"] for line in lines) == "一二三四五六七八九十十一十二十三"


@pytest.mark.asyncio
async def test_verify_and_retry_only_retries_failed_sentence(tmp_path) -> None:
    audio = tmp_path / "line.wav"
    audio.write_bytes(b"audio")
    attempts = 0

    async def asr(_path):
        nonlocal attempts
        attempts += 1
        return {"text": "错误" if attempts == 1 else "目标旁白", "words": []}

    async def retry() -> object:
        return audio

    result = await verify_and_retry(
        "目标旁白", audio, asr=asr, retry_synthesize=retry, retries=1
    )
    assert result["passed"] is True
    assert result["attempt"] == 2


@pytest.mark.asyncio
async def test_verify_and_retry_raises_after_local_retries(tmp_path) -> None:
    audio = tmp_path / "line.wav"
    audio.write_bytes(b"audio")

    async def asr(_path):
        return {"text": "错误"}

    with pytest.raises(AsrVerificationError, match="CER"):
        await verify_and_retry("目标旁白", audio, asr=asr, retries=1)
