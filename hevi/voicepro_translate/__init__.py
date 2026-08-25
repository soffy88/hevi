"""voicepro_translate 3O 包：专业翻译。

Voice-Pro 的翻译能力内部化：
文本预处理 → LLM 翻译 → 术语替换 → 质量评估
"""

from __future__ import annotations

# ── Oprim ──
from hevi.voicepro_translate.oprim import (
    apply_terminology,
    translate_azure_translator,
    translate_deep_translator,
    translate_deepl,
    translate_llm,
    translate_text,
)

# ── Oskill ──
from hevi.voicepro_translate.oskill import (
    skill_apply_terminology,
    skill_batch_translate,
    skill_translate_text,
)

# ── Schemas ──
from hevi.voicepro_translate.schemas import (
    TerminologyEntry,
    TranslateBatchResult,
    TranslateConfig,
    TranslateProvider,
    TranslateResult,
    make_translate_config,
    make_translate_result,
)

__all__ = [
    "TerminologyEntry",
    "TranslateBatchResult",
    "TranslateConfig",
    "TranslateProvider",
    "TranslateResult",
    "apply_terminology",
    "make_translate_config",
    "make_translate_result",
    "skill_apply_terminology",
    "skill_batch_translate",
    "skill_translate_text",
    "translate_azure_translator",
    "translate_deep_translator",
    "translate_deepl",
    "translate_llm",
    "translate_text",
]