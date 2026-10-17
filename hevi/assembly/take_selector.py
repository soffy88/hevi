"""多 take 选择器（对标 video-use beat-structure assembly）。

给定同一内容的多个 take（如多次录制），按 beat 结构自动选择最佳片段组合：
  - 每个 beat 从所有 take 中选最佳版本
  - 支持手动指定每 beat 的 take 偏好
  - 评分维度：流畅度、能量、完整性
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from hevi.assembly.edit_craft import EditRange, Word

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────────────


@dataclass
class TakeBeat:
    """单个 take 中一个 beat 的信息。"""

    take_id: str
    beat: str
    start: float
    end: float
    words: list[Word] = field(default_factory=list)
    score: float = 0.0  # 0-1, 综合评分
    fluency: float = 0.0  # 流畅度
    energy: float = 0.0  # 能量/表现力
    completeness: float = 0.0  # 完整性
    notes: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def compute_score(self, weights: dict[str, float] | None = None) -> float:
        """加权综合评分。"""
        w = weights or {"fluency": 0.4, "energy": 0.3, "completeness": 0.3}
        self.score = (
            self.fluency * w["fluency"]
            + self.energy * w["energy"]
            + self.completeness * w["completeness"]
        )
        return self.score


@dataclass
class TakeSet:
    """同一内容的所有 take 集合。"""

    beats: dict[str, list[TakeBeat]] = field(default_factory=dict)
    # beat_name → [TakeBeat from take_0, TakeBeat from take_1, ...]

    @property
    def beat_names(self) -> list[str]:
        return list(self.beats.keys())

    @property
    def take_ids(self) -> list[str]:
        ids: set[str] = set()
        for tb_list in self.beats.values():
            for tb in tb_list:
                ids.add(tb.take_id)
        return sorted(ids)


@dataclass
class SelectionResult:
    """beat-by-beat 选择结果。"""

    selections: dict[str, TakeBeat] = field(default_factory=dict)
    # beat_name → 选中的 TakeBeat
    total_score: float = 0.0
    strategy: str = "auto"  # "auto" | "manual"

    def to_edit_ranges(self, source_key: str = "main") -> list[EditRange]:
        """转为 EditRange 列表，可直接放入 EDL。"""
        ranges: list[EditRange] = []
        for beat_name in sorted(self.selections.keys()):
            tb = self.selections[beat_name]
            ranges.append(EditRange(
                source=source_key,
                start=tb.start,
                end=tb.end,
                beat=tb.beat,
                quote="",
                reason=f"selected from {tb.take_id} (score={tb.score:.2f})",
            ))
        return ranges

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "total_score": self.total_score,
            "selections": {
                beat: {
                    "take_id": tb.take_id,
                    "beat": tb.beat,
                    "start": tb.start,
                    "end": tb.end,
                    "score": tb.score,
                    "fluency": tb.fluency,
                    "energy": tb.energy,
                    "completeness": tb.completeness,
                }
                for beat, tb in self.selections.items()
            },
        }


# ── 选择逻辑 ──────────────────────────────────────────────────────────


def select_best_takes(
    take_set: TakeSet,
    *,
    weights: dict[str, float] | None = None,
    manual_overrides: dict[str, str] | None = None,
    min_score: float = 0.0,
) -> SelectionResult:
    """按 beat 选择最佳 take。

    Args:
        take_set: 所有 take 的 beat 数据
        weights: 评分权重 {"fluency": 0.4, "energy": 0.3, "completeness": 0.3}
        manual_overrides: 手动指定 beat → take_id
        min_score: 最低可接受评分

    Returns:
        SelectionResult
    """
    manual = manual_overrides or {}
    result = SelectionResult(
        strategy="manual" if manual else "auto",
    )

    total = 0.0
    for beat_name, candidates in take_set.beats.items():
        # 计算所有候选的评分
        for c in candidates:
            c.compute_score(weights)

        # 手动指定优先
        if beat_name in manual:
            preferred_id = manual[beat_name]
            for c in candidates:
                if c.take_id == preferred_id:
                    result.selections[beat_name] = c
                    total += c.score
                    break
            else:
                logger.warning(
                    "manual override beat=%s take=%s not found, using auto",
                    beat_name, preferred_id,
                )
                best = max(candidates, key=lambda x: x.score)
                result.selections[beat_name] = best
                total += best.score
            continue

        # 自动选最高分
        if candidates:
            best = max(candidates, key=lambda x: x.score)
            if best.score >= min_score:
                result.selections[beat_name] = best
            else:
                logger.warning(
                    "beat=%s best score %.2f < min %.2f, selecting anyway",
                    beat_name, best.score, min_score,
                )
                result.selections[beat_name] = best
            total += result.selections[beat_name].score

    result.total_score = total
    return result


def build_take_set_from_words(
    take_words: dict[str, list[Word]],
    beat_boundaries: list[dict[str, Any]],
    *,
    scores: dict[str, dict[str, dict[str, float]]] | None = None,
) -> TakeSet:
    """从词级时间戳 + beat 分界构建 TakeSet。

    Args:
        take_words: {take_id: [Word, ...]}
        beat_boundaries: [{"beat": "intro", "start": 0.0, "end": 5.0}, ...]
        scores: 可选预设评分 {take_id: {beat: {fluency: 0.8, ...}}}
    """
    take_set = TakeSet()
    score_data = scores or {}

    for beat_info in beat_boundaries:
        beat_name = beat_info["beat"]
        beat_start = float(beat_info["start"])
        beat_end = float(beat_info["end"])

        candidates: list[TakeBeat] = []
        for take_id, words in take_words.items():
            # 找该 beat 区间内的词
            beat_words = [
                w for w in words
                if w.start >= beat_start and w.end <= beat_end
            ]
            if not beat_words:
                continue

            tb = TakeBeat(
                take_id=take_id,
                beat=beat_name,
                start=beat_words[0].start,
                end=beat_words[-1].end,
                words=beat_words,
            )

            # 加载预设评分
            take_scores = score_data.get(take_id, {}).get(beat_name, {})
            tb.fluency = take_scores.get("fluency", 0.5)
            tb.energy = take_scores.get("energy", 0.5)
            tb.completeness = take_scores.get("completeness", 0.5)
            tb.compute_score()

            candidates.append(tb)

        if candidates:
            take_set.beats[beat_name] = candidates

    return take_set
