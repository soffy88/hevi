"""剪辑成片层 · 硬规则与 EDL 契约（对标 video-use 生产正确性）。

硬规则（不可静默违反）:
  1. 字幕最后烧录（overlay 之后）
  2. 分段 extract → concat（有 overlay 时禁止单 pass 双重编码）
  3. 每刀 30ms 音频 fade（防爆音）
  4. overlay 必须 PTS 偏移到输出时间窗
  5. master SRT 用输出时间轴偏移
  6. 绝不在词中间下刀
  7. cut edge 留 30–200ms padding
  8. 仅词级 verbatim ASR 可作剪辑依据
  9. transcript 按源缓存（调用方保证）
  10. 策略未确认前禁止执行剪辑
  11. 成片输出隔离到 edit/ 目录
  12. 自检不通过不得归档

本模块以纯函数为主，便于单测；渲染见 edit_render.py，自检见 cut_self_eval.py。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# ── 硬规则常量 ──────────────────────────────────────────────────────────

AUDIO_FADE_S = 0.03  # 30ms，规则 3
PAD_MS_MIN = 30
PAD_MS_MAX = 200
PAD_MS_DEFAULT = 50
SELF_EVAL_MAX_PASSES = 3
SILENCE_PHRASE_BREAK_S = 0.5  # takes 打包：≥0.5s 静音断句


class EditCraftError(RuntimeError):
    """剪辑硬规则被违反或 EDL 非法时抛出（禁止静默降级）。"""


@dataclass(frozen=True)
class Word:
    """词级时间戳（verbatim ASR 输出）。"""

    word: str
    start: float
    end: float


@dataclass(frozen=True)
class EditRange:
    """EDL 中一段：源文件上的 [start, end) + 语义元数据。"""

    source: str
    start: float
    end: float
    beat: str = ""
    quote: str = ""
    reason: str = ""

    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class OverlaySpec:
    file: str
    start_in_output: float
    duration: float


@dataclass
class EditDecisionList:
    """剪辑决策表（EDL）。"""

    version: int = 1
    sources: dict[str, str] = field(default_factory=dict)
    ranges: list[EditRange] = field(default_factory=list)
    grade: str = "none"
    overlays: list[OverlaySpec] = field(default_factory=list)
    subtitles: str | None = None
    total_duration_s: float | None = None
    strategy_confirmed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "sources": dict(self.sources),
            "ranges": [asdict(r) for r in self.ranges],
            "grade": self.grade,
            "overlays": [asdict(o) for o in self.overlays],
            "subtitles": self.subtitles,
            "total_duration_s": self.total_duration_s,
            "strategy_confirmed": self.strategy_confirmed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EditDecisionList:
        ranges = [
            EditRange(
                source=str(r["source"]),
                start=float(r["start"]),
                end=float(r["end"]),
                beat=str(r.get("beat") or ""),
                quote=str(r.get("quote") or ""),
                reason=str(r.get("reason") or ""),
            )
            for r in data.get("ranges") or []
        ]
        overlays = [
            OverlaySpec(
                file=str(o["file"]),
                start_in_output=float(o["start_in_output"]),
                duration=float(o["duration"]),
            )
            for o in data.get("overlays") or []
        ]
        return cls(
            version=int(data.get("version") or 1),
            sources={str(k): str(v) for k, v in (data.get("sources") or {}).items()},
            ranges=ranges,
            grade=str(data.get("grade") or "none"),
            overlays=overlays,
            subtitles=data.get("subtitles"),
            total_duration_s=(
                float(data["total_duration_s"])
                if data.get("total_duration_s") is not None
                else None
            ),
            strategy_confirmed=bool(data.get("strategy_confirmed", False)),
        )


# ── 规则 10：策略确认门 ─────────────────────────────────────────────────


def require_strategy_confirmation(edl: EditDecisionList | dict[str, Any]) -> None:
    """策略未确认则拒绝执行（规则 10）。"""
    confirmed = (
        edl.strategy_confirmed
        if isinstance(edl, EditDecisionList)
        else bool(edl.get("strategy_confirmed", False))
    )
    if not confirmed:
        raise EditCraftError(
            "策略未确认：禁止执行剪辑。请先完成 Ask → Confirm，再设 strategy_confirmed=true"
        )


# ── 规则 6–7：词边界与 padding ──────────────────────────────────────────


def snap_to_word_boundary(
    t: float,
    words: list[Word],
    *,
    side: Literal["start", "end"] = "start",
) -> float:
    """把时间戳吸附到最近词边界，禁止词中下刀（规则 6）。

    side=start → 吸附到 ≤t 的最近词起点（或下一词起点若 t 在词中）；
    side=end   → 吸附到 ≥t 的最近词终点。
    无词表时原样返回。
    """
    if not words:
        return t
    ordered = sorted(words, key=lambda w: w.start)

    if side == "start":
        # 若 t 落在某词内部，推到该词起点（或更前一边界）
        for w in ordered:
            if w.start <= t <= w.end:
                return w.start
        # t 在间隙：取后方词起点，若无则取前词终点
        for w in ordered:
            if w.start >= t:
                return w.start
        return ordered[-1].end

    # side == "end"
    for w in reversed(ordered):
        if w.start <= t <= w.end:
            return w.end
    for w in reversed(ordered):
        if w.end <= t:
            return w.end
    return ordered[0].start


def clamp_pad_ms(pad_ms: float) -> float:
    """padding 必须在 30–200ms 工作窗内（规则 7）。"""
    return max(PAD_MS_MIN, min(PAD_MS_MAX, float(pad_ms)))


def apply_cut_padding(
    start: float,
    end: float,
    *,
    pad_before_ms: float = PAD_MS_DEFAULT,
    pad_after_ms: float = 80.0,
    source_duration: float | None = None,
) -> tuple[float, float]:
    """给 cut 边缘加 padding，并夹到源时长内。"""
    pb = clamp_pad_ms(pad_before_ms) / 1000.0
    pa = clamp_pad_ms(pad_after_ms) / 1000.0
    s = max(0.0, start - pb)
    e = end + pa
    if source_duration is not None:
        e = min(e, float(source_duration))
    if e <= s:
        raise EditCraftError(f"padding 后区间非法: start={s:.3f} end={e:.3f}")
    return s, e


def snap_range_to_words(
    start: float,
    end: float,
    words: list[Word],
    *,
    pad_before_ms: float = PAD_MS_DEFAULT,
    pad_after_ms: float = 80.0,
    source_duration: float | None = None,
) -> tuple[float, float]:
    """词边界吸附 + padding 的组合入口。"""
    s = snap_to_word_boundary(start, words, side="start")
    e = snap_to_word_boundary(end, words, side="end")
    if e <= s and words:
        # 至少保留一个词
        covering = [w for w in words if w.start >= s or w.end <= e]
        if covering:
            s = covering[0].start
            e = covering[-1].end
    return apply_cut_padding(
        s,
        e,
        pad_before_ms=pad_before_ms,
        pad_after_ms=pad_after_ms,
        source_duration=source_duration,
    )


# ── 规则 5：输出时间轴 SRT ──────────────────────────────────────────────


@dataclass(frozen=True)
class SubtitleCue:
    start: float
    end: float
    text: str


def remap_cues_to_output_timeline(
    cues: list[SubtitleCue],
    ranges: list[EditRange],
) -> list[SubtitleCue]:
    """把源时间轴字幕重映射到成片时间轴（规则 5）。

    output_time = cue_time - segment_start + segment_offset
    只保留落在各 range 内的 cue（与 range 有交集则裁剪）。
    """
    out: list[SubtitleCue] = []
    offset = 0.0
    for r in ranges:
        for c in cues:
            # 交集
            cs = max(c.start, r.start)
            ce = min(c.end, r.end)
            if ce <= cs:
                continue
            out.append(
                SubtitleCue(
                    start=cs - r.start + offset,
                    end=ce - r.start + offset,
                    text=c.text,
                )
            )
        offset += r.duration()
    return out


def format_srt(cues: list[SubtitleCue]) -> str:
    """SubtitleCue 列表 → SRT 文本。"""

    def _fmt(t: float) -> str:
        if t < 0:
            t = 0.0
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines: list[str] = []
    for i, c in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f"{_fmt(c.start)} --> {_fmt(c.end)}")
        lines.append(c.text.strip())
        lines.append("")
    return "\n".join(lines)


# ── 规则 1：滤镜链顺序 ──────────────────────────────────────────────────


def assert_subtitles_last(filter_steps: list[str]) -> None:
    """校验字幕步骤在滤镜链最后（规则 1）。"""
    if not filter_steps:
        return
    sub_idxs = [i for i, s in enumerate(filter_steps) if "subtitle" in s.lower()]
    if not sub_idxs:
        return
    if max(sub_idxs) != len(filter_steps) - 1:
        raise EditCraftError(
            "硬规则违反：字幕必须在滤镜链最后一步（否则会被 overlay 遮挡）"
        )


def build_segment_afade_filter(duration_s: float, fade_s: float = AUDIO_FADE_S) -> str:
    """单段音频入出 fade 滤镜（规则 3）。"""
    d = max(duration_s, fade_s * 2 + 0.001)
    fade = min(fade_s, d / 2 - 0.001)
    out_st = max(0.0, d - fade)
    return f"afade=t=in:st=0:d={fade:.3f},afade=t=out:st={out_st:.3f}:d={fade:.3f}"


def overlay_setpts_expr(start_in_output: float) -> str:
    """overlay 时间轴偏移表达式（规则 4）。"""
    return f"setpts=PTS-STARTPTS+{start_in_output:.6f}/TB"


# ── EDL 校验 ────────────────────────────────────────────────────────────


def validate_edl(edl: EditDecisionList, *, require_confirm: bool = True) -> list[str]:
    """校验 EDL；返回警告列表。致命问题直接 raise EditCraftError。"""
    warnings: list[str] = []
    if require_confirm:
        require_strategy_confirmation(edl)
    if not edl.ranges:
        raise EditCraftError("EDL.ranges 为空，无法剪辑")
    if not edl.sources:
        raise EditCraftError("EDL.sources 为空")

    total = 0.0
    for i, r in enumerate(edl.ranges):
        if r.source not in edl.sources:
            raise EditCraftError(f"ranges[{i}].source={r.source!r} 不在 sources 中")
        if r.end <= r.start:
            raise EditCraftError(
                f"ranges[{i}] 非法区间 start={r.start} end={r.end}（end 必须 > start）"
            )
        if r.start < 0:
            raise EditCraftError(f"ranges[{i}].start 不能为负")
        total += r.duration()

    for j, o in enumerate(edl.overlays):
        if o.duration <= 0:
            raise EditCraftError(f"overlays[{j}].duration 必须 > 0")
        if o.start_in_output < 0:
            raise EditCraftError(f"overlays[{j}].start_in_output 不能为负")
        if o.start_in_output + o.duration > total + 0.5:
            warnings.append(
                f"overlays[{j}] 超出成片时长（start+dur={o.start_in_output + o.duration:.2f}s, total≈{total:.2f}s）"
            )

    if edl.total_duration_s is not None:
        if abs(edl.total_duration_s - total) > 0.25:
            warnings.append(
                f"total_duration_s={edl.total_duration_s:.3f} 与 ranges 合计 {total:.3f} 不一致"
            )
    return warnings


def compute_output_duration(ranges: list[EditRange]) -> float:
    return sum(r.duration() for r in ranges)


def edit_output_dir(videos_dir: str | Any) -> Any:
    """规则 11：所有会话输出进 <videos_dir>/edit/。"""
    from pathlib import Path

    p = Path(videos_dir) / "edit"
    p.mkdir(parents=True, exist_ok=True)
    return p
