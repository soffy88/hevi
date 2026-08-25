"""voicepro_translate oprim：无状态原子，不得引用 oskill/omodul。

翻译原子：DeepL / Deep-Translator / Azure Translator / LLM 翻译
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

from hevi.voicepro_translate.schemas import (
    TerminologyEntry,
    TranslateBatchResult,
    TranslateConfig,
    TranslateProvider,
    TranslateResult,
    make_translate_config,
    make_translate_result,
)

# ── DeepL 翻译 ─────────────────────────────────────

async def translate_deepl(
    text: str,
    source_lang: str = "auto",
    target_lang: str = "zh-CN",
    api_key: str = "",
) -> TranslateResult:
    """使用 DeepL API 翻译。"""
    try:
        import deepl
    except ImportError:
        raise RuntimeError("deepl 未安装")

    client = deepl.Translator(api_key)
    result = client.translate_text(
        text,
        source_lang=source_lang,
        target_lang=target_lang,
    )

    return make_translate_result(
        source_text=text,
        translated_text=result.text,
        source_lang=source_lang,
        target_lang=target_lang,
        provider=TranslateProvider.DEEPL,
    )


# ── Deep-Translator 翻译 ──────────────────────────

async def translate_deep_translator(
    text: str,
    source_lang: str = "auto",
    target_lang: str = "zh-CN",
    backend: str = "GoogleTranslator",
) -> TranslateResult:
    """使用 Deep-Translator API 翻译。

    支持 Google / Bing / LibreTranslate 后端。
    """
    try:
        from deep_translator import (
            BingTranslator,
            GoogleTranslator,
            LibreTranslator,
        )
    except ImportError:
        raise RuntimeError("deep-translator 未安装")

    translator_cls = {
        "GoogleTranslator": GoogleTranslator,
        "BingTranslator": BingTranslator,
        "LibreTranslator": LibreTranslator,
    }.get(backend, GoogleTranslator)

    translator = translator_cls(
        source=source_lang if source_lang != "auto" else None,
        target=target_lang,
    )

    translated = translator.translate(text)

    return make_translate_result(
        source_text=text,
        translated_text=translated,
        source_lang=source_lang,
        target_lang=target_lang,
        provider=TranslateProvider.DEEP_TRANSLATOR,
    )


# ── Azure Translator 翻译 ─────────────────────────

async def translate_azure_translator(
    text: str,
    source_lang: str = "auto",
    target_lang: str = "zh-CN",
    api_key: str = "",
    region: str = "eastus",
) -> TranslateResult:
    """使用 Azure Translator 翻译。"""
    # 占位：实际实现需调用 Azure SDK
    return make_translate_result(
        source_text=text,
        translated_text=text,  # 占位
        source_lang=source_lang,
        target_lang=target_lang,
        provider=TranslateProvider.AZURE_TRANSLATOR,
    )


# ── LLM 翻译 ─────────────────────────────────────

async def translate_llm(
    text: str,
    source_lang: str = "auto",
    target_lang: str = "zh-CN",
    model: str = "gpt-4o-mini",
    base_url: str = "",
    api_key: str = "",
    terminology_map: dict[str, str] | None = None,
) -> TranslateResult:
    """使用 LLM 翻译（支持 OpenAI / Gemini / DeepSeek / 通义千问）。

    LLM 翻译的优势：
    - 上下文感知
    - 术语库自动应用
    - 自然语义保持
    """
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise RuntimeError("openai 未安装")

    client = AsyncOpenAI(
        base_url=base_url if base_url else None,
        api_key=api_key,
    )

    # 构建翻译 prompt
    prompt = f"请将以下文本翻译为 {target_lang}。"
    if terminology_map:
        prompt += "\n术语库：\n"
        for k, v in terminology_map.items():
            prompt += f"- {k} → {v}\n"
    prompt += f"\n文本：\n{text}"

    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )

    translated = response.choices[0].message.content

    return make_translate_result(
        source_text=text,
        translated_text=translated,
        source_lang=source_lang,
        target_lang=target_lang,
        provider=TranslateProvider.LLM_TRANSLATE,
    )


# ── 通用翻译（根据 provider 自动选择） ───────────

async def translate_text(
    text: str,
    config: TranslateConfig,
) -> TranslateResult:
    """通用翻译：根据 provider 自动选择后端。"""
    if config.provider == TranslateProvider.DEEPL:
        return await translate_deepl(
            text, config.source_lang, config.target_lang, config.deepl_api_key,
        )
    if config.provider == TranslateProvider.DEEP_TRANSLATOR:
        return await translate_deep_translator(
            text, config.source_lang, config.target_lang, config.backend,
        )
    if config.provider == TranslateProvider.AZURE_TRANSLATOR:
        return await translate_azure_translator(
            text, config.source_lang, config.target_lang,
            config.azure_key, config.azure_region,
        )
    if config.provider == TranslateProvider.LLM_TRANSLATE:
        return await translate_llm(
            text, config.source_lang, config.target_lang,
            config.llm_model, config.llm_base_url, config.llm_api_key,
            config.terminology_map,
        )
    raise ValueError(f"不支持的翻译提供商: {config.provider}")


# ── 术语替换 ─────────────────────────────────────

def apply_terminology(
    text: str,
    terminology_map: dict[str, str],
) -> str:
    """应用术语替换到翻译结果。"""
    for source, target in terminology_map.items():
        text = text.replace(source, target)
    return text


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    "TerminologyEntry",
    "TranslateBatchResult",
    "TranslateConfig",
    "TranslateProvider",
    "TranslateResult",
    "apply_terminology",
    "make_translate_config",
    "make_translate_result",
    "translate_azure_translator",
    "translate_deep_translator",
    "translate_deepl",
    "translate_llm",
    "translate_text",
]
