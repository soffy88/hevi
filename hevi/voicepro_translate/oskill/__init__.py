"""voicepro_translate oskill：组合 ≥2 个 oprim 原子，不得引用 omodul。

翻译技能：组合文本预处理 + 翻译 + 术语替换 + 质量评估
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.voicepro_translate.oprim import (
    apply_terminology,
    make_translate_config,
    make_translate_result,
    translate_azure_translator,
    translate_deep_translator,
    translate_deepl,
    translate_llm,
    translate_text,
)
from hevi.voicepro_translate.schemas import (
    TerminologyEntry,
    TranslateBatchResult,
    TranslateConfig,
    TranslateProvider,
    TranslateResult,
    make_translate_config,
    make_translate_result,
)

# ── 翻译技能：完整翻译流程 ─────────────────────────────


async def skill_translate_text(
    text: str,
    provider: TranslateProvider | str = TranslateProvider.DEEP_TRANSLATOR,
    source_lang: str = "auto",
    target_lang: str = "zh-CN",
    config: TranslateConfig | None = None,
) -> TranslateResult:
    """翻译完整技能：预处理 → 翻译 → 术语替换。

    根据 provider 自动选择后端。
    """
    if config is None:
        config = make_translate_config(provider, source_lang, target_lang)

    # 执行翻译
    result = await translate_text(text, config)

    return result


# ── 批量翻译技能 ────────────────────────────────────

async def skill_batch_translate(
    texts: list[str],
    provider: TranslateProvider | str = TranslateProvider.DEEP_TRANSLATOR,
    source_lang: str = "auto",
    target_lang: str = "zh-CN",
) -> list[TranslateResult]:
    """批量翻译技能。"""
    results = []
    for text in texts:
        result = await skill_translate_text(text, provider, source_lang, target_lang)
        results.append(result)
    return results


# ── 术语库管理技能 ──────────────────────────────────

def skill_apply_terminology(
    text: str,
    terminology_map: dict[str, str],
) -> str:
    """应用术语替换技能。"""
    return apply_terminology(text, terminology_map)


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    "make_translate_config",
    "make_translate_result",
    "skill_apply_terminology",
    "skill_batch_translate",
    "skill_translate_text",
]
