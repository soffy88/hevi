"""voicepro_translate 3O 包的 schema 契约。

对应 Voice-Pro 的专业翻译能力模型。
对齐 Voice-Pro 的翻译 pipeline: 文本预处理 → LLM 翻译 → 术语替换 → 质量评估
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# ─── 翻译提供商 ─────────────────────────────────────


class TranslateProvider(str, Enum):
    """翻译服务提供商。"""
    DEEPL = "deepl"
    DEEP_TRANSLATOR = "deep_translator"  # Google / Bing / LibreTranslate
    AZURE_TRANSLATOR = "azure_translator"
    LLM_TRANSLATE = "llm_translate"  # GPT / Gemini / DeepSeek


# ─── 翻译配置模型 ──────────────────────────────────


class TranslateConfig(BaseModel):
    """翻译配置。"""
    provider: TranslateProvider = TranslateProvider.DEEP_TRANSLATOR
    source_lang: str = "auto"
    target_lang: str = "zh-CN"
    # DeepL 特有
    deepl_api_key: str = ""
    # Azure Translator 特有
    azure_key: str = ""
    azure_region: str = ""
    # Deep Translator 特有
    backend: str = "GoogleTranslator"  # GoogleTranslator / BingTranslator / LibreTranslator
    # LLM 翻译特有
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = ""
    llm_api_key: str = ""
    # 术语库
    terminology_map: dict[str, str] = Field(default_factory=dict)
    # 翻译质量
    quality_threshold: float = 0.8


# ─── 翻译结果模型 ─────────────────────────────────


class TranslateResult(BaseModel):
    """单条翻译结果。"""
    source_text: str = ""
    translated_text: str = ""
    source_lang: str = ""
    target_lang: str = ""
    provider: TranslateProvider = TranslateProvider.DEEP_TRANSLATOR
    kept_original: bool = False  # 是否保留原文（翻译失败时）
    attempts: int = 1
    quality_score: float = 0.0  # 0-1


class TranslateBatchResult(BaseModel):
    """批量翻译结果。"""
    results: list[TranslateResult] = Field(default_factory=list)
    total_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    avg_quality: float = 0.0


# ─── 术语替换模型 ─────────────────────────────────


class TerminologyEntry(BaseModel):
    """术语库条目。"""
    source: str = ""
    target: str = ""
    context: str = ""  # 上下文说明


# ─── 工厂函数 ─────────────────────────────────────


def make_translate_config(
    provider: TranslateProvider | str = TranslateProvider.DEEP_TRANSLATOR,
    source_lang: str = "auto",
    target_lang: str = "zh-CN",
) -> TranslateConfig:
    """创建翻译配置。"""
    if isinstance(provider, str):
        provider = TranslateProvider(provider)
    return TranslateConfig(
        provider=provider,
        source_lang=source_lang,
        target_lang=target_lang,
    )


def make_translate_result(
    source_text: str,
    translated_text: str,
    source_lang: str,
    target_lang: str,
    provider: TranslateProvider | str,
    kept_original: bool = False,
) -> TranslateResult:
    """创建翻译结果实例。"""
    if isinstance(provider, str):
        provider = TranslateProvider(provider)
    return TranslateResult(
        source_text=source_text,
        translated_text=translated_text,
        source_lang=source_lang,
        target_lang=target_lang,
        provider=provider,
        kept_original=kept_original,
    )