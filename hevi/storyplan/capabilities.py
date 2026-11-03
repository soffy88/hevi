"""StoryPlan 能力兼容垫片 —— 注册信息的单一事实来源是统一注册表。

历史上本模块自带私有 ``Capability`` / ``CapabilityResult`` / ``_REGISTRY``
并重复注册 ``story_plan`` / ``story_check`` / ``take_select`` /
``storyplan.critique``，与统一注册表 ``hevi/capabilities/registry.py``
行为分叉（私有 render 回 ``payload=...``、统一只回 ``qa``；私有
``story_plan`` render 不建 ``out_dir`` 直调必崩；私有 ``take_select``
的 ``validate_params`` 因模块级 ``list = list_capabilities`` 遮蔽内置
``list`` 而对任何非空 candidates 必抛 ``TypeError``）。

现已消除双注册：

* 四个能力的 name / description / params_schema / render 只在统一
  注册表定义一份，本模块不再保存任何注册数据；
* 本模块仅保留同名导出（``Capability`` / ``CapabilityResult`` /
  ``get`` / ``resolve`` / ``list_capabilities`` / ``list`` /
  ``register`` / ``_REGISTRY``），全部转发统一注册表；可见范围仍
  限定为上述四个 StoryPlan 能力，与旧私有注册表的列表形状一致，
  故 ``hevi/storyplan/api.py`` 的 ``GET /capabilities`` 响应形状不变
  （字段值改由统一注册表提供，如 params_schema 的
  ``additionalProperties: false``）；
* ``validate_params`` 走统一实现（jsonschema 校验，非法参数抛
  ``CapabilityError``）；需要完整 payload 的调用方请直调核心函数
  （``hevi.storyplan.autofill.autofill_story_plan`` /
  ``hevi.storyplan.check.run_story_check`` /
  ``hevi.storyplan.take_select.select_best_take`` /
  ``hevi.storyplan.critique.render_storyplan_critique``），
  ``hevi/storyplan/api.py`` 的 POST 端点本就如此。
"""

from __future__ import annotations

from typing import Any

from hevi.capabilities import registry as _unified_registry
from hevi.capabilities.registry import Capability, CapabilityResult

__all__ = [
    "STORYPLAN_CAPABILITY_NAMES",
    "Capability",
    "CapabilityResult",
    "get",
    "list",
    "list_capabilities",
    "register",
    "resolve",
]

#: 本垫片对外可见的 StoryPlan 能力名（成员过滤，不是注册数据：
#: 每项的 description / schema / render 均取自统一注册表）。
STORYPLAN_CAPABILITY_NAMES: tuple[str, ...] = (
    "story_plan",
    "story_check",
    "take_select",
    "storyplan.critique",
)


def get(name: str) -> Capability:
    """按名取 StoryPlan 能力（转发统一注册表）。

    名字不在 StoryPlan 四个能力之内时，保持旧私有注册表的错误语义：
    抛 ``RuntimeError(f"Unknown capability: {name}")``。
    """
    if name not in STORYPLAN_CAPABILITY_NAMES:
        raise RuntimeError(f"Unknown capability: {name}")
    return _unified_registry.get(name)


def resolve(name: str) -> Capability:
    """Alias of :func:`get`（与旧私有模块一致）。"""
    return get(name)


def register(cap: Capability) -> Capability:
    """转发统一注册表的 ``register``（旧私有模块同名导出的兼容保留）。"""
    return _unified_registry.register(cap)


def list_capabilities(kind: str | None = None, aspect: str | None = None) -> list[Capability]:
    """列出四个 StoryPlan 能力（对象取自统一注册表，顺序与旧私有版一致）。"""
    out: list[Capability] = []
    for name in STORYPLAN_CAPABILITY_NAMES:
        cap = _unified_registry.get(name)
        if kind and cap.kind != kind:
            continue
        if aspect and aspect not in cap.aspects:
            continue
        out.append(cap)
    return out


# 旧私有模块的同名别名。注意：必须放在所有函数定义之后，且本模块
# 函数体内不得再把 ``list`` 当内置类型使用（旧实现的 TypeError 正源于此）。
list = list_capabilities


def __getattr__(name: str) -> Any:
    # PEP 562 兼容：旧代码 ``from hevi.storyplan.capabilities import _REGISTRY``
    # 仍可拿到 {name: Capability} 快照（内容实时取自统一注册表）。
    if name == "_REGISTRY":
        return {cap.name: cap for cap in list_capabilities()}
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
