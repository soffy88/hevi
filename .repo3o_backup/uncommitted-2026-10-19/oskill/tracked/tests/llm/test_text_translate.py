"""Tests for oskill.llm.text_translate."""

from unittest.mock import MagicMock

import pytest

from oskill.llm.text_translate import text_translate


def _mock_llm(response: str = "翻译结果") -> MagicMock:
    m = MagicMock()
    m.call.return_value = response
    return m


class TestTextTranslate:
    def test_en_to_zh_natural(self) -> None:
        llm = _mock_llm("美联储维持利率不变")
        result = text_translate(text="Fed holds rates steady", target_lang="zh", llm_client=llm)
        assert result["translated_text"] == "美联储维持利率不变"
        assert result["style"] == "natural"
        assert result["source_lang_detected"] == "en"

    def test_zh_to_en_reverse(self) -> None:
        llm = _mock_llm("Hello world")
        result = text_translate(text="你好世界", target_lang="en", llm_client=llm)
        assert result["translated_text"] == "Hello world"
        assert result["source_lang_detected"] == "zh"

    def test_auto_detect_source_lang(self) -> None:
        llm = _mock_llm("결과")
        result = text_translate(
            text="한국어 텍스트", target_lang="zh", source_lang="auto", llm_client=llm
        )
        assert result["source_lang_detected"] == "ko"

    def test_summary_style_with_max_chars(self) -> None:
        llm = _mock_llm("这是一段很长的翻译结果" * 10)
        result = text_translate(
            text="Long English text " * 50,
            target_lang="zh",
            llm_client=llm,
            style="summary",
            max_summary_chars=20,
        )
        assert len(result["translated_text"]) <= 20

    def test_empty_text_raises(self) -> None:
        llm = _mock_llm()
        with pytest.raises(ValueError, match="empty"):
            text_translate(text="", target_lang="zh", llm_client=llm)

    def test_long_text_chunked(self) -> None:
        llm = _mock_llm("chunk result")
        long_text = "A" * 10000
        text_translate(text=long_text, target_lang="zh", llm_client=llm)
        assert llm.call.call_count >= 2  # Should be chunked

    def test_llm_failure_raises(self) -> None:
        llm = MagicMock()
        llm.call.side_effect = RuntimeError("LLM down")
        with pytest.raises(RuntimeError):
            text_translate(text="hello", target_lang="zh", llm_client=llm)

    def test_multilang_japanese(self) -> None:
        llm = _mock_llm("日本語の翻訳")
        result = text_translate(
            text="こんにちは世界", target_lang="en", source_lang="auto", llm_client=llm
        )
        assert result["source_lang_detected"] == "ja"
