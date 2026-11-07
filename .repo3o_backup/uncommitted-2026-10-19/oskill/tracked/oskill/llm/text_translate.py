"""oskill.llm.text_translate — LLM-powered text translation."""

from __future__ import annotations

from typing import Any, Protocol


class LLMCaller(Protocol):
    def call(self, prompt: str) -> str: ...


def text_translate(
    *,
    text: str,
    target_lang: str = "zh",
    source_lang: str = "auto",
    llm_client: LLMCaller,
    style: str = "natural",
    max_summary_chars: int = 0,
) -> dict[str, Any]:
    """Translate text using LLM.

    Parameters
    ----------
    text : source text to translate
    target_lang : target language code (zh, en, ja, ko, etc.)
    source_lang : source language ("auto" for LLM detection)
    llm_client : object with .call(prompt) -> str
    style : "literal" | "natural" | "summary"
    max_summary_chars : max chars for summary style (0 = no limit)

    Returns
    -------
    dict with: translated_text, source_lang_detected, style, char_count
    """
    if not text or not text.strip():
        raise ValueError("text must not be empty")

    # Build prompt based on style
    if style == "summary":
        limit_instruction = f" (max {max_summary_chars} chars)" if max_summary_chars > 0 else ""
        prompt = (
            f"Summarize and translate the following text into {target_lang}{limit_instruction}. "
            f"Output ONLY the translated summary, no explanation.\n\n{text}"
        )
    elif style == "literal":
        prompt = (
            f"Translate the following text literally into {target_lang}. "
            f"Preserve original structure. Output ONLY the translation.\n\n{text}"
        )
    else:  # natural
        prompt = (
            f"Translate the following text naturally into {target_lang}. "
            f"Output ONLY the translation.\n\n{text}"
        )

    # Handle long text by chunking
    max_chunk = 4000
    if len(text) > max_chunk:
        chunks = [text[i : i + max_chunk] for i in range(0, len(text), max_chunk)]
        translated_parts = []
        for chunk in chunks:
            chunk_prompt = prompt.replace(text, chunk)
            translated_parts.append(llm_client.call(chunk_prompt))
        translated_text = " ".join(translated_parts)
    else:
        translated_text = llm_client.call(prompt)

    # Truncate if summary with max_chars
    if style == "summary" and max_summary_chars > 0 and len(translated_text) > max_summary_chars:
        translated_text = translated_text[:max_summary_chars]

    # Detect source language (heuristic)
    # 先判 kana/hangul (日语/韩语独有),再判 CJK 汉字 (否则含汉字的日语会被误判为中文)
    detected_lang = source_lang
    if source_lang == "auto":
        if any("\u3040" <= c <= "\u30ff" for c in text[:100]):
            detected_lang = "ja"
        elif any("\uac00" <= c <= "\ud7af" for c in text[:100]):
            detected_lang = "ko"
        elif any("\u4e00" <= c <= "\u9fff" for c in text[:100]):
            detected_lang = "zh"
        else:
            detected_lang = "en"

    return {
        "translated_text": translated_text,
        "source_lang_detected": detected_lang,
        "style": style,
        "char_count": len(translated_text),
    }
