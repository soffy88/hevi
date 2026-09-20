"""voicepro_translate 3O 包：专业翻译。

Voice-Pro 的翻译能力内部化：
文本预处理 → LLM 翻译 → 术语替换 → 质量评估

注意:layer4_legacy 实现从本包的 ``schemas`` 子模块取契约。若这里在导入时就
eagerly 拉取 oprim/oskill 实现,会与 ``oprim_impl -> hevi.voicepro_translate.schemas``
形成循环导入。故实现名走惰性 ``__getattr__``,``schemas`` 契约照旧即刻可用。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

# ── Schemas(无实现依赖,可即刻导出) ──
from hevi.voicepro_translate.schemas import (
    TerminologyEntry,
    TranslateBatchResult,
    TranslateConfig,
    TranslateProvider,
    TranslateResult,
    make_translate_config,
    make_translate_result,
)

# ── Oprim / Oskill(惰性,避免循环导入) ──
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "apply_terminology": (
        "hevi.layer4_legacy.voicepro_translate.oprim_impl",
        "apply_terminology",
    ),
    "translate_azure_translator": (
        "hevi.layer4_legacy.voicepro_translate.oprim_impl",
        "translate_azure_translator",
    ),
    "translate_deep_translator": (
        "hevi.layer4_legacy.voicepro_translate.oprim_impl",
        "translate_deep_translator",
    ),
    "translate_deepl": (
        "hevi.layer4_legacy.voicepro_translate.oprim_impl",
        "translate_deepl",
    ),
    "translate_llm": (
        "hevi.layer4_legacy.voicepro_translate.oprim_impl",
        "translate_llm",
    ),
    "translate_text": (
        "hevi.layer4_legacy.voicepro_translate.oprim_impl",
        "translate_text",
    ),
    "skill_apply_terminology": (
        "hevi.layer4_legacy.voicepro_translate.oskill_impl",
        "skill_apply_terminology",
    ),
    "skill_batch_translate": (
        "hevi.layer4_legacy.voicepro_translate.oskill_impl",
        "skill_batch_translate",
    ),
    "skill_translate_text": (
        "hevi.layer4_legacy.voicepro_translate.oskill_impl",
        "skill_translate_text",
    ),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    return getattr(import_module(module_name), attr)


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
