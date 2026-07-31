"""健壮 JSON 解析器（对标 ViMax robust_json_parser.py）。

容忍 LLM 输出中常见的 JSON 格式错误：
  - 尾部逗号 (trailing commas)
  - 单引号
  - 未转义的控制字符
  - 注释 (// 和 /* */)
  - 多余的逗号 (,,)
  - 缺少引号的 key
  - NaN / Infinity
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _remove_trailing_commas(text: str) -> str:
    """移除 JSON 中的尾部逗号。

    匹配 `]` 或 `}` 前的逗号（可能有空白符）。
    """
    # 处理数组/对象中的尾部逗号
    # 需要小心不要误删字符串内的逗号
    result: list[str] = []
    in_string = False
    escape_next = False
    i = 0

    while i < len(text):
        ch = text[i]

        if escape_next:
            result.append(ch)
            escape_next = False
            i += 1
            continue

        if ch == "\\":
            result.append(ch)
            escape_next = True
            i += 1
            continue

        if ch == '"':
            in_string = not in_string
            result.append(ch)
            i += 1
            continue

        if in_string:
            result.append(ch)
            i += 1
            continue

        # 不在字符串内
        if ch == ",":
            # 向前看：跳过空白，看下一个非空白字符是否是 ] 或 }
            j = i + 1
            while j < len(text) and text[j] in " \t\n\r":
                j += 1
            if j < len(text) and text[j] in "]}":
                # 跳过这个逗号
                i += 1
                continue

        result.append(ch)
        i += 1

    return "".join(result)


def _remove_json_comments(text: str) -> str:
    """移除 JSON 中的注释（// 和 /* */）。"""
    result: list[str] = []
    in_string = False
    escape_next = False
    i = 0

    while i < len(text):
        ch = text[i]

        if escape_next:
            result.append(ch)
            escape_next = False
            i += 1
            continue

        if ch == "\\":
            result.append(ch)
            escape_next = True
            i += 1
            continue

        if ch == '"':
            in_string = not in_string
            result.append(ch)
            i += 1
            continue

        if in_string:
            result.append(ch)
            i += 1
            continue

        # 检查注释
        if ch == "/" and i + 1 < len(text):
            next_ch = text[i + 1]
            if next_ch == "/":
                # 单行注释：跳到行尾
                j = i + 2
                while j < len(text) and text[j] != "\n":
                    j += 1
                i = j
                continue
            elif next_ch == "*":
                # 多行注释：跳到 */
                j = i + 2
                while j + 1 < len(text):
                    if text[j] == "*" and text[j + 1] == "/":
                        j += 2
                        break
                    j += 1
                else:
                    j = len(text)
                i = j
                continue

        result.append(ch)
        i += 1

    return "".join(result)


def _fix_single_quotes(text: str) -> str:
    """将单引号替换为双引号（仅在非字符串位置）。"""
    # 简单策略：如果单引号数量是偶数且双引号很少，尝试替换
    single_count = text.count("'")
    double_count = text.count('"')

    if single_count > 0 and double_count == 0 and single_count % 2 == 0:
        # 全是单引号，直接替换
        return text.replace("'", '"')

    # 混合情况：更保守的替换
    # 只替换明显是 JSON key 或 value 的单引号
    return text


def _fix_unquoted_keys(text: str) -> str:
    """给缺少引号的 key 加引号。"""
    # 匹配 {key: 或 ,key: 模式
    pattern = r'(?<=[{,\n])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:'
    return re.sub(pattern, r' "\1":', text)


def _fix_special_values(text: str) -> str:
    """修复 NaN、Infinity 等特殊值。"""
    # 不在字符串内的 NaN → null
    # 不在字符串内的 Infinity → 1e999
    # 不在字符串内的 -Infinity → -1e999

    # 简单替换（可能误改字符串内容，但 LLM 输出中这些值很少出现在字符串中）
    text = re.sub(r'\bNaN\b', 'null', text)
    text = re.sub(r'\bInfinity\b', '1e308', text)
    text = re.sub(r'\b-Infinity\b', '-1e308', text)
    return text


def _extract_json_object(text: str) -> str:
    """从文本中提取最外层的 JSON 对象/数组。"""
    text = text.strip()

    # 尝试找第一个 { 或 [ 和对应的最后一个 } 或 ]
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            continue
        # 从后往前找对应的结束符
        end = text.rfind(end_char)
        if end > start:
            return text[start:end + 1]

    return text


def robust_json_loads(
    text: str,
    *,
    extract: bool = True,
    strict: bool = False,
) -> Any:
    """健壮 JSON 解析。

    Args:
        text: JSON 文本（可能包含常见错误）
        extract: 是否从文本中提取 JSON 对象
        strict: 严格模式（不做任何修复，直接 json.loads）

    Returns:
        解析后的 Python 对象

    Raises:
        json.JSONDecodeError: 即使修复后仍无法解析
    """
    if strict:
        return json.loads(text)

    # 预处理
    cleaned = text.strip()

    # 提取 JSON 对象
    if extract:
        cleaned = _extract_json_object(cleaned)

    # 移除注释
    cleaned = _remove_json_comments(cleaned)

    # 修复尾部逗号
    cleaned = _remove_trailing_commas(cleaned)

    # 修复单引号
    cleaned = _fix_single_quotes(cleaned)

    # 修复缺少引号的 key
    cleaned = _fix_unquoted_keys(cleaned)

    # 修复特殊值
    cleaned = _fix_special_values(cleaned)

    # 尝试解析
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 再尝试更激进的修复
        # 移除多余逗号
        cleaned = re.sub(r',,', ',', cleaned)
        # 移除控制字符（除了 \n \r \t）
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', cleaned)
        return json.loads(cleaned)


def safe_json_loads(text: str, default: Any = None) -> Any:
    """安全 JSON 解析，失败返回默认值。"""
    try:
        return robust_json_loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.debug("JSON parse failed, returning default")
        return default


def extract_json_from_markdown(text: str) -> Any:
    """从 Markdown 代码块中提取 JSON。

    支持 ```json ... ``` 和 ``` ... ``` 格式。
    """
    # 匹配 ```json\n...\n``` 或 ```\n...\n```
    patterns = [
        r'```json\s*\n(.*?)\n\s*```',
        r'```\s*\n(.*?)\n\s*```',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return robust_json_loads(match.group(1))

    # 没有代码块，直接尝试解析
    return robust_json_loads(text)


def find_json_objects(text: str) -> list[Any]:
    """找到文本中所有 JSON 对象/数组。"""
    objects: list[Any] = []

    # 找所有 {} 和 [] 配对
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        i = 0
        while i < len(text):
            start = text.find(start_char, i)
            if start == -1:
                break
            end = text.find(end_char, start)
            if end == -1:
                break
            candidate = text[start:end + 1]
            try:
                obj = robust_json_loads(candidate, extract=False)
                objects.append(obj)
            except json.JSONDecodeError:
                pass
            i = end + 1

    return objects
