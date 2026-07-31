"""filler / silence 自动选切（对标 video-use 去废话）。

输入词级 ASR，输出「保留区间」与建议 EDL ranges。
纯函数，不依赖 GPU。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from hevi.assembly.edit_craft import (
    EditDecisionList,
    EditRange,
    Word,
    apply_cut_padding,
)

# 中英常见口头禅 / 假起头（小写匹配；中文原样）
_FILLER_EXACT = frozenset(
    {
        "um",
        "uh",
        "uhm",
        "umm",
        "uhh",
        "ah",
        "er",
        "erm",
        "like",
        "youknow",
        "you",
        "know",  # 仅当单独成词且前后是 filler 上下文时由短语处理
        "呃",
        "嗯",
        "啊",
        "那个",
        "就是",
        "然后",
        "其实",
        "对吧",
        "怎么说",
        "这个",
    }
)

# 词本身几乎总是 filler 的（强匹配）
_FILLER_STRONG = frozenset(
    {
        "um",
        "uh",
        "uhm",
        "umm",
        "uhh",
        "呃",
        "嗯",
        "啊",
    }
)

_NON_WORD = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)


@dataclass(frozen=True)
class SilenceGap:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class FillerHit:
    word: str
    start: float
    end: float
    kind: str  # strong | phrase


@dataclass(frozen=True)
class KeptRange:
    """保留的源时间区间。"""

    start: float
    end: float
    reason: str = ""


@dataclass
class FillerCutPlan:
    kept: list[KeptRange]
    removed_fillers: list[FillerHit]
    silence_gaps: list[SilenceGap]
    source_duration: float

    def to_edit_ranges(self, source_id: str = "main") -> list[EditRange]:
        return [
            EditRange(
                source=source_id,
                start=k.start,
                end=k.end,
                beat="KEEP",
                reason=k.reason or "kept after filler/silence cut",
            )
            for k in self.kept
            if k.end > k.start
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_duration": self.source_duration,
            "kept": [{"start": k.start, "end": k.end, "reason": k.reason} for k in self.kept],
            "removed_fillers": [
                {"word": f.word, "start": f.start, "end": f.end, "kind": f.kind}
                for f in self.removed_fillers
            ],
            "silence_gaps": [
                {"start": g.start, "end": g.end, "duration": g.duration}
                for g in self.silence_gaps
            ],
        }


def normalize_token(text: str) -> str:
    t = _NON_WORD.sub("", text.strip().lower())
    return t


def is_filler_word(text: str, *, strong_only: bool = False) -> bool:
    tok = normalize_token(text)
    if not tok:
        return False
    if tok in _FILLER_STRONG:
        return True
    if strong_only:
        return False
    return tok in _FILLER_EXACT


def find_silence_gaps(
    words: list[Word],
    *,
    min_gap_s: float = 0.4,
    source_duration: float | None = None,
) -> list[SilenceGap]:
    """词间静音 ≥ min_gap_s 视为可剪间隙。"""
    if not words:
        return []
    ordered = sorted(words, key=lambda w: w.start)
    gaps: list[SilenceGap] = []
    # 片头静音
    if ordered[0].start >= min_gap_s:
        gaps.append(SilenceGap(0.0, ordered[0].start))
    for a, b in zip(ordered, ordered[1:], strict=False):
        gap = b.start - a.end
        if gap >= min_gap_s:
            gaps.append(SilenceGap(a.end, b.start))
    end = source_duration if source_duration is not None else ordered[-1].end
    tail = end - ordered[-1].end
    if tail >= min_gap_s:
        gaps.append(SilenceGap(ordered[-1].end, end))
    return gaps


def find_fillers(words: list[Word], *, strong_only: bool = False) -> list[FillerHit]:
    hits: list[FillerHit] = []
    for w in words:
        if is_filler_word(w.word, strong_only=strong_only):
            kind = "strong" if normalize_token(w.word) in _FILLER_STRONG else "phrase"
            # phrase 级弱 filler 仅当词很短时删除，避免误杀「然后我们…」叙事
            if kind == "phrase" and (w.end - w.start) > 0.45:
                continue
            hits.append(FillerHit(word=w.word, start=w.start, end=w.end, kind=kind))
    return hits


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda x: x[0])
    out = [ordered[0]]
    for s, e in ordered[1:]:
        ps, pe = out[-1]
        if s <= pe + 1e-3:
            out[-1] = (ps, max(pe, e))
        else:
            out.append((s, e))
    return out


def _subtract_intervals(
    total_start: float,
    total_end: float,
    remove: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """从 [total_start, total_end) 减去 remove 区间，得到保留段。"""
    keep: list[tuple[float, float]] = []
    cur = total_start
    for s, e in _merge_intervals(remove):
        s = max(s, total_start)
        e = min(e, total_end)
        if e <= s:
            continue
        if s > cur:
            keep.append((cur, s))
        cur = max(cur, e)
    if cur < total_end:
        keep.append((cur, total_end))
    return [(s, e) for s, e in keep if e - s > 1e-3]


def plan_filler_cut(
    words: list[Word],
    *,
    source_duration: float | None = None,
    min_silence_s: float = 0.4,
    cut_fillers: bool = True,
    cut_silence: bool = True,
    silence_keep_s: float = 0.12,
    min_keep_s: float = 0.25,
    pad_before_ms: float = 40.0,
    pad_after_ms: float = 60.0,
    strong_fillers_only: bool = False,
) -> FillerCutPlan:
    """根据词级时间戳生成保留计划。

    - cut_fillers: 去掉口头禅
    - cut_silence: 压缩长静音（保留 silence_keep_s 呼吸）
    """
    if not words:
        dur = source_duration or 0.0
        return FillerCutPlan(
            kept=[KeptRange(0.0, dur, "empty transcript — keep all")] if dur > 0 else [],
            removed_fillers=[],
            silence_gaps=[],
            source_duration=dur,
        )

    ordered = sorted(words, key=lambda w: w.start)
    dur = float(source_duration if source_duration is not None else ordered[-1].end)
    fillers = find_fillers(ordered, strong_only=strong_fillers_only) if cut_fillers else []
    gaps = find_silence_gaps(ordered, min_gap_s=min_silence_s, source_duration=dur)

    remove: list[tuple[float, float]] = []
    if cut_fillers:
        for f in fillers:
            remove.append((f.start, f.end))
    if cut_silence:
        for g in gaps:
            # 中间留一点呼吸，剪掉两头多余静音
            if g.duration <= silence_keep_s:
                continue
            excess = g.duration - silence_keep_s
            # 对称压缩
            half = excess / 2
            remove.append((g.start, g.start + half))
            remove.append((g.end - half, g.end))

    kept_raw = _subtract_intervals(0.0, dur, remove)
    kept: list[KeptRange] = []
    for s, e in kept_raw:
        if e - s < min_keep_s:
            continue
        # 可选 padding（夹到源时长）
        try:
            ps, pe = apply_cut_padding(
                s,
                e,
                pad_before_ms=pad_before_ms,
                pad_after_ms=pad_after_ms,
                source_duration=dur,
            )
        except Exception:
            ps, pe = s, e
        kept.append(
            KeptRange(
                start=ps,
                end=pe,
                reason="filler/silence clean",
            )
        )

    # 合并过近的 keep 段，避免碎切
    merged: list[KeptRange] = []
    for k in kept:
        if merged and k.start - merged[-1].end < 0.08:
            prev = merged[-1]
            merged[-1] = KeptRange(prev.start, k.end, prev.reason)
        else:
            merged.append(k)

    if not merged:
        # 安全网：全被剪光时保留整段
        merged = [KeptRange(0.0, dur, "fallback keep all — plan emptied")]

    return FillerCutPlan(
        kept=merged,
        removed_fillers=fillers,
        silence_gaps=gaps if cut_silence else [],
        source_duration=dur,
    )


def plan_to_edl(
    plan: FillerCutPlan,
    *,
    source_id: str,
    source_path: str,
    strategy_confirmed: bool = False,
    grade: str = "none",
) -> EditDecisionList:
    """FillerCutPlan → EditDecisionList（默认未确认，需用户点头）。"""
    return EditDecisionList(
        sources={source_id: source_path},
        ranges=plan.to_edit_ranges(source_id),
        grade=grade,
        strategy_confirmed=strategy_confirmed,
        total_duration_s=sum(k.end - k.start for k in plan.kept),
    )
