"""Auto-split from hicode whl."""

from __future__ import annotations

import re
from typing import Any


def select_skill(
    task: str,
    *,
    skill_index: list[dict[str, Any]],
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """根据任务描述从 skill 索引中选择最相关的 skill（纯内存）。

    渐进披露第一步：只用 SkillMeta（name+description+tags），不读 body。

    Args:
        task: 任务描述字符串。
        skill_index: SkillMeta dict 列表（含 name/description/tags）。
        top_k: 最多返回数量，默认 3。

    Returns:
        最相关的 SkillMeta dict 列表（按相关度排序）。

    Example:
        >>> skills = select_skill("refactor python code",
        ...     skill_index=[{"name": "refactor_python", "description": "..."}])
        >>> skills[0]["name"]
        'refactor_python'
    """
    task_words = set(re.findall(r"\w+", task.lower()))
    scored: list[tuple[float, dict]] = []

    for meta in skill_index:
        name_words = set(re.findall(r"\w+", meta.get("name", "").lower()))
        desc_words = set(re.findall(r"\w+", meta.get("description", "").lower()))
        tag_words = set(re.findall(r"\w+", " ".join(meta.get("tags", [])).lower()))
        all_words = name_words | desc_words | tag_words
        score = len(task_words & all_words) / max(len(task_words), 1)
        # 名称直接匹配加权
        if task_words & name_words:
            score += 0.5
        scored.append((score, meta))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for score, m in scored[:top_k] if score >= 0]
