"""Defensive parsing for Remotion props at the explainer assembly boundary.

LLM 直出(E0)、旧客户端、浏览器中间层都可能把嵌套对象(``visual_config``、
``chart_data``)序列化成 JSON 字符串再传进来。下游 Python 装配逻辑对这些字段做
``["key"]`` / ``.update(...)`` 链式访问,字符串会直接抛 ``TypeError`` /
``AttributeError`` 炸掉整个装配事务;Remotion 模板也依赖对象形状。

这里提供统一的防御解析:字符串 → ``json.loads`` → dict/list,解析失败或类型不符
→ 安全默认值。**所有进入 Remotion manifest 的 props 都必须先过这层**——
确稿台、legacy E0、注入的 Provider 三条入口统一收敛到此。
"""

from __future__ import annotations

import json
from typing import Any

from hevi.explainer.contracts import ExplainerCue

# visual_config 中已知的"嵌套对象"字段:LLM/客户端可能把它们字符串化,要还原成 dict。
_DICT_KEYS = frozenset(
    {
        "chart_data",
        "chart_config",
        "split_left",
        "split_right",
        "left_label",
        "right_label",
        "metadata",
    }
)
# 已知的"对象/标量数组"字段:字符串化时要还原成 list。
_LIST_KEYS = frozenset(
    {
        "cards",
        "items",
        "points",
        "formula_lines",
        "cta_emojis",
        "sink_emojis",
        "keywords",
        "subtitle_lines",
        "audio_segments",
    }
)


def safe_dict(val: Any) -> dict[str, Any]:
    """防御性转字典:dict 原样返回;JSON 字符串自动 ``json.loads``;其余 → {}。

    - 空字符串 / 解析失败 / 解析结果不是对象 → {} (不抛异常)
    - pydantic 模型 → model_dump 后返回
    """
    if isinstance(val, dict):
        return val
    if hasattr(val, "model_dump"):
        try:
            dumped = val.model_dump(mode="json")
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            return {}
    if isinstance(val, str):
        text = val.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def safe_list(val: Any) -> list[Any]:
    """防御性转列表:list 原样返回;JSON 数组字符串自动解析;其余 → []。"""
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        text = val.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def safe_str(val: Any, default: str = "") -> str:
    """防御性转字符串:None/非标量 → default;标量 → str()。"""
    if val is None:
        return default
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float, bool)):
        return str(val)
    return default


def normalise_visual_config(config: Any) -> dict[str, Any]:
    """把任意来源的 visual_config 规整为可安全进入 Remotion 的 dict。

    1. 整体是 JSON 字符串 → 先 ``json.loads`` 还原成 dict;
    2. 已知的嵌套对象字段(如 ``chart_data``)若仍为 JSON 字符串 → 逐字段还原;
    3. 已知的对象数组字段(如 ``cards``)若为 JSON 数组字符串 → 还原成 list;
    4. 其余标量原样保留。
    """
    base = safe_dict(config)
    result: dict[str, Any] = {}
    for key, value in base.items():
        if key in _DICT_KEYS:
            result[key] = safe_dict(value)
        elif key in _LIST_KEYS:
            result[key] = safe_list(value)
        else:
            result[key] = value
    return result


def process_cues_for_remotion(cues: Any) -> list[ExplainerCue]:
    """装配入参(任意形状)规整为可安全进入 Remotion 的 ExplainerCue 列表。

    对应确稿台/旧客户端把 cue 序列化成字符串或丢失嵌套类型的场景:
    1. 整个 cue 是 JSON 字符串 → 先还原成 dict;
    2. cue 是 dict / pydantic 模型 → 字段缺省交给 ExplainerCue 校验补齐;
    3. ``visual_config`` / ``chart_data`` 等嵌套对象若为 JSON 字符串 → 还原;
    4. 无法解析的脏条目直接丢弃(不炸掉整条装配事务)。

    Returns:
        规整后的 cue 列表;入参不是 list 时返回 []。
    """
    if not isinstance(cues, list):
        return []
    processed: list[ExplainerCue] = []
    for item in cues:
        cue = safe_dict(item)
        if not cue:
            continue
        cue["visual_config"] = normalise_visual_config(cue.get("visual_config"))
        if cue.get("chart_data") is not None:
            cue["chart_data"] = safe_dict(cue.get("chart_data"))
        try:
            processed.append(ExplainerCue.model_validate(cue))
        except Exception:
            # 单条脏 cue 丢弃,不让坏数据阻断整条装配。
            continue
    return processed


__all__ = [
    "normalise_visual_config",
    "process_cues_for_remotion",
    "safe_dict",
    "safe_list",
    "safe_str",
]
