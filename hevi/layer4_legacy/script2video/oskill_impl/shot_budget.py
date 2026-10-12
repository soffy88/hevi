"""镜头预算 —— 让 `target_duration_s` 真正约束镜头数（DRAMAPLAN bug1）。

背景（STATUS.md 247-260）：短剧通道 `target_duration_s` 怎么设，单集都收敛到约 10 镜。
根因在上游已安装包（**禁止修改**）：
  - `oskill.script_writer._chapters_for_duration()` 对 <300 s 至少给 2 章；
  - `oskill.storyboard_planner` 每章场景/镜头数完全不受 `target_duration_s` 约束。

hevi 侧的修法：调用前按目标时长算好**镜头预算**，在 `shot_gen_fn` 返回后做后处理
（超出预算则把相邻镜头**合并**成一个更长镜头，或按需裁剪），并**按预期章数均摊**每章
镜头数，避免第一章吃掉全部预算。锁定分镜（SPEC-003）路径不裁剪——用户已人工锁定镜头数。

本模块是纯算法（oskill 边界，无 IO、无 LLM），符合 3O：可被单元测试直接驱动。
"""

from __future__ import annotations

import copy
import math
from typing import Any

# 每个镜头的目标时长（秒）。短视频 5s/镜是常见基准；预算 = 目标时长 / 该值。
DEFAULT_SECONDS_PER_SHOT = 5.0
DEFAULT_MIN_SHOTS = 1
# 单集镜头数硬上限，防止超长时长把预算算成几百镜（也防止 LLM 失控）。
DEFAULT_MAX_SHOTS = 120


def shot_budget_for_duration(
    target_duration_s: float,
    *,
    seconds_per_shot: float = DEFAULT_SECONDS_PER_SHOT,
    min_shots: int = DEFAULT_MIN_SHOTS,
    max_shots: int = DEFAULT_MAX_SHOTS,
) -> int:
    """目标时长 → 镜头数预算（单调不减，落在 [min_shots, max_shots]）。

    例（seconds_per_shot=5）：30s→6，60s→12，120s→24，300s→60。
    """
    if seconds_per_shot <= 0:
        raise ValueError("seconds_per_shot must be > 0")
    if target_duration_s <= 0:
        return max(1, int(min_shots))
    budget = int(round(float(target_duration_s) / float(seconds_per_shot)))
    return max(int(min_shots), min(int(max_shots), budget))


def expected_chapters_for_duration(target_duration_s: float) -> int:
    """镜像上游 `oskill.script_writer._chapters_for_duration` 的章节数档位。

    只读镜像（不 import 上游私有函数，也不修改它），用于把总镜头预算**均摊到每章**。
    上游档位：<300s→2，<900s→4，<2700s→8，否则 16。
    """
    d = float(target_duration_s)
    if d < 300:
        return 2
    if d < 900:
        return 4
    if d < 2700:
        return 8
    return 16


def shot_budget_per_chapter(
    target_duration_s: float,
    *,
    n_chapters: int | None = None,
    seconds_per_shot: float = DEFAULT_SECONDS_PER_SHOT,
    min_shots_per_chapter: int = 1,
) -> int:
    """每章镜头数上限 = ceil(总预算 / 预期章数)，至少 `min_shots_per_chapter`。"""
    chapters = int(n_chapters) if n_chapters else expected_chapters_for_duration(target_duration_s)
    chapters = max(1, chapters)
    total = shot_budget_for_duration(target_duration_s, seconds_per_shot=seconds_per_shot)
    return max(int(min_shots_per_chapter), math.ceil(total / chapters))


def _get(obj: Any, key: str, default: Any = "") -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _set(obj: Any, key: str, value: Any) -> Any:
    """不可变更新：pydantic model_copy / dataclass replace / 浅拷贝兜底。"""
    if hasattr(obj, "model_copy"):
        return obj.model_copy(update={key: value})
    clone = copy.copy(obj)
    setattr(clone, key, value)
    return clone


def merge_shot_plans(group: list[Any]) -> Any:
    """把相邻的若干镜头合并成一个镜头（拼接 prompt/台词，时长相加）。"""
    if not group:
        raise ValueError("group must not be empty")
    if len(group) == 1:
        return group[0]
    prompts = " ".join(str(_get(p, "image_prompt", "") or "").strip() for p in group).strip()
    tts = " ".join(str(_get(p, "tts_text", "") or "").strip() for p in group).strip()
    duration = sum(float(_get(p, "duration_s", 0) or 0) for p in group)
    merged = _set(group[0], "image_prompt", prompts)
    merged = _set(merged, "tts_text", tts)
    merged = _set(merged, "duration_s", duration)
    return merged


def fit_shot_plans_to_budget(plans: list[Any], budget: int) -> list[Any]:
    """把镜头计划列表压到 `budget` 个以内：超出则**均匀合并**相邻镜头。

    - `budget <= 0` 或空列表 → 空列表；
    - 已 ≤ budget → 原样返回（不复制、不改顺序）；
    - 超出 → 按 `i * budget // n` 分组，组内合并（保留首镜 id，拼接 prompt/tts，时长相加）。

    返回列表长度严格 ≤ budget（当 budget ≥ 1 且 plans 非空）。
    """
    if not plans or budget <= 0:
        return []
    if len(plans) <= budget:
        return list(plans)
    n = len(plans)
    groups: list[list[Any]] = [[] for _ in range(budget)]
    for i, plan in enumerate(plans):
        groups[min(budget - 1, i * budget // n)].append(plan)
    return [merge_shot_plans(group) for group in groups if group]


def split_single_shot_plan(plan: Any, count: int) -> list[Any]:
    """把单个镜头按台词内容**顺序分组**拆分为 count 个子镜头。

    分句/分段按顺序均匀分配到子镜（全部保留，拼接后与原文一致）；
    内容不足 count 份时按字符级再细分（绝不丢内容、不造空 tts）。
    """
    if count <= 1:
        return [plan]
    total_dur = float(_get(plan, "duration_s", 0) or 0)
    base_dur = round(total_dur / count, 2)
    original_id = str(_get(plan, "shot_id", "shot") or "shot")
    original_prompt = str(_get(plan, "image_prompt", "") or "").strip()
    original_tts = str(_get(plan, "tts_text", "") or "").strip()

    import re

    # 按标点切分并保留标点本身（拼接后与原文逐字一致）
    raw_tokens = [t for t in re.split(r"(?<=[，,。！？!?；;\n])", original_tts) if t.strip()]
    if not raw_tokens:
        raw_tokens = [original_tts] if original_tts else []

    # 无内容时仍需提供空子镜（用空 tts）：返回 count 个空子镜，时长均匀分配
    if not raw_tokens:
        raw_tokens = [""]

    def _char_level(flat: str) -> list[list[str]]:
        # 按字符均分；只在均分点附近（±per/3）找标点切，找不到就按均分点切，绝不回退成单字镜
        out: list[list[str]] = []
        n_chars = len(flat)
        start = 0
        for j in range(count):
            if j == count - 1 or start >= n_chars:
                out.append([flat[start:]])
                start = n_chars
                continue
            remaining = n_chars - start
            slots_left = count - j
            per = max(1, remaining // slots_left)
            ideal = min(n_chars, start + per)
            win = max(1, per // 3)
            lo = max(start + 1, ideal - win)
            hi = min(n_chars - (slots_left - 1), ideal + win)
            best = None
            for c in range(lo, hi + 1):
                if flat[c - 1] in "，,。！？!?；;\n":
                    if best is None or abs(c - ideal) < abs(best - ideal):
                        best = c
            cut = best if best is not None else ideal
            cut = max(start + 1, min(cut, n_chars - (slots_left - 1)))
            out.append([flat[start:cut]])
            start = cut
        return out

    def _token_level(tokens: list[str]) -> list[list[str]]:
        # 句/段数足够：按字数均衡的相邻分组（保持顺序，每组至少 1 段）
        out: list[list[str]] = []
        i = 0
        remaining = sum(len(t) for t in tokens)
        for k in range(count):
            left = count - k
            if left == 1:
                out.append(tokens[i:])
                break
            target = remaining / left
            g = [tokens[i]]
            acc = len(tokens[i])
            i += 1
            while i < len(tokens) - (left - 1) and acc + len(tokens[i]) / 2 <= target:
                g.append(tokens[i])
                acc += len(tokens[i])
                i += 1
            remaining -= acc
            out.append(g)
        return out

    def _ratio(gs: list[list[str]]) -> float:
        lens = [len("".join(g)) for g in gs]
        return (max(lens) / max(1, min(lens))) if lens else 1.0

    n = len(raw_tokens)
    flat_text = "".join(raw_tokens)
    if n >= count:
        groups = _token_level(raw_tokens)
        # 字数允许时子镜字数 max/min ≤ 2，否则退到字符级均分
        if _ratio(groups) > 2 and len(flat_text) >= 2 * count:
            alt = _char_level(flat_text)
            if _ratio(alt) < _ratio(groups):
                groups = alt
    else:
        groups = _char_level(flat_text)

    parts: list[Any] = []
    accum_dur = 0.0
    for j, group in enumerate(groups):
        dur = round(total_dur - accum_dur, 2) if j == count - 1 else base_dur
        accum_dur += dur
        sid = f"{original_id}_{j+1}"
        clause_text = "".join(group)
        # 子镜画面描述按镜头序号给出景别递进（避免子镜画面完全相同）
        camera_notes = ["远景交代环境", "中景角色互动", "近景情绪推进", "特写定格收束"]
        note = camera_notes[j % len(camera_notes)]
        gist = clause_text.strip()[:24]
        prompt = (
            f"{original_prompt}（分镜{j+1}/{count}，{note}，表现「{gist}」）"
            if original_prompt and gist
            else (f"{original_prompt}（分镜{j+1}/{count}，{note}）" if original_prompt else "")
        )
        sub = _set(plan, "shot_id", sid)
        sub = _set(sub, "duration_s", dur)
        sub = _set(sub, "image_prompt", prompt)
        sub = _set(sub, "tts_text", clause_text)
        parts.append(sub)
    return parts


def expand_shot_plans_to_budget(plans: list[Any], budget: int) -> list[Any]:
    """把镜头计划列表扩展到 `budget` 个：不足则将长镜头均匀拆分为多镜。

    - `budget <= 0` 或空列表 → 空列表；
    - 已 >= budget → 原样返回；
    - 不足 → 按容量均摊拆分子镜头，返回列表长度严格 == budget。
    """
    if not plans or budget <= 0:
        return []
    if len(plans) >= budget:
        return list(plans)
    n = len(plans)
    sub_counts = [budget // n + (1 if i < (budget % n) else 0) for i in range(n)]
    expanded: list[Any] = []
    for plan, count in zip(plans, sub_counts, strict=True):
        expanded.extend(split_single_shot_plan(plan, count))
    return expanded


def adjust_shot_plans_to_budget(plans: list[Any], budget: int) -> list[Any]:
    """镜头预算适配：多则均匀合并，少则均匀拆分，严格适配到 budget 镜。"""
    if not plans or budget <= 0:
        return []
    if len(plans) > budget:
        return fit_shot_plans_to_budget(plans, budget)
    if len(plans) < budget:
        return expand_shot_plans_to_budget(plans, budget)
    return list(plans)


__all__ = [
    "DEFAULT_SECONDS_PER_SHOT",
    "adjust_shot_plans_to_budget",
    "expected_chapters_for_duration",
    "expand_shot_plans_to_budget",
    "fit_shot_plans_to_budget",
    "merge_shot_plans",
    "shot_budget_for_duration",
    "shot_budget_per_chapter",
    "split_single_shot_plan",
]
