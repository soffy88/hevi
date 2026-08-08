"""hevi.obase — Hevi 侧 base 层能力沉淀(Frontend SPEC v6.0 §2.4)。

3O 库的 `obase`(pip 依赖,git-pinned 不可改)提供 ProviderRegistry 运行时注册;
本包承载 Hevi 侧的"预置策略表"(presets)—— 前端不再维护 Provider 管理表单,
仅传 preset 名称或预设级别,由这里解析为完整的 provider 路由/成本/上下文策略。
"""

from hevi.obase.provider_presets import (
    PRESET_LEVELS,
    PRESETS,
    get_preset,
    list_presets,
)

__all__ = ["PRESETS", "PRESET_LEVELS", "get_preset", "list_presets"]
