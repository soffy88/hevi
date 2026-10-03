"""G0.2-C Anchor Resolver spike — 无状态语义锚点解析.

不是 Timeline,不拥有时间:只读 runtime_state(dialogue 事件 + fps),
输出 {frame, time_ms}。Timeline wins on 字段,本模块只做 anchor -> 时刻换算。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hevi.audio.tts_alignment import AudioAlignment


@dataclass(frozen=True)
class Anchor:
    type: str  # AFTER_DIALOGUE(本 spike 唯一支持的类型)
    target: str  # ScriptUnit unit_id(依赖 Spike A)
    edge: str = "start"
    offset_ms: int = 0  # 可为负,整数;语义:相对 dialogue end 的偏移
    # R-P10-01:坐标系。line-local = 相对行音频起点;film-global = 成片时间线。
    coordinate: str = "line-local"


@dataclass(frozen=True)
class ResolvedAnchor:
    anchor_id: str
    source: str
    time_ms: int
    frame: int
    confidence: float
    evidence: tuple[str, ...] = field(default_factory=tuple)


class AnchorOrphaned(RuntimeError):
    """ANCHOR_ORPHANED:target 不存在,调用方 fail-loud。"""


class AnchorUnresolved(RuntimeError):
    """ANCHOR_UNRESOLVED:类型不支持/状态缺失,调用方 fail-loud。"""


def resolve_anchor(
    anchor: Anchor,
    *,
    dialogue_end_ms: dict[str, int],
    fps: int,
    anchor_id: str = "",
    timeline_hash: str = "",
    alignment_hash: str = "",
) -> ResolvedAnchor:
    """语义锚点 -> 帧精确时刻。纯函数,不触 Timeline model。

    dialogue_end_ms: {unit_id: 该句对白结束时刻 ms}(来自 AudioAlignment
    words[-1].end_ms,见 G0.2-B 修正规则,不用音频 duration)。
    """
    if anchor.type != "AFTER_DIALOGUE":
        raise AnchorUnresolved(f"unsupported anchor type: {anchor.type!r}")
    if anchor.target not in dialogue_end_ms:
        raise AnchorOrphaned(f"anchor target missing: {anchor.target!r}")
    if fps <= 0:
        raise AnchorUnresolved(f"invalid fps: {fps!r}")

    time_ms = dialogue_end_ms[anchor.target] + anchor.offset_ms
    if time_ms < 0:
        raise AnchorUnresolved(f"negative resolved time: {time_ms}ms")
    frame = round(time_ms * fps / 1000)
    evidence = tuple(e for e in (alignment_hash, timeline_hash) if e)
    return ResolvedAnchor(
        anchor_id=anchor_id or f"{anchor.type}:{anchor.target}:{anchor.offset_ms}",
        source=anchor.target,
        time_ms=time_ms,
        frame=frame,
        confidence=1.0,  # 确定性换算;含模型推断时再降置信度(后续工作)
        evidence=evidence,
    )


# ── A5:供给侧(谁提供 dialogue_end_ms / film 偏移)──────────────────────────


def dialogue_end_map(alignment: AudioAlignment) -> dict[str, int]:
    """A4 sidecar(AudioAlignment)→ {phrase_id(=unit_id): 末词结束 ms}。

    R-P10-01:对话结束必须是词级末词,不是音频总长(后者含尾静音)。
    """
    if not alignment.phrases:
        return {}
    out: dict[str, int] = {}
    for phrase in alignment.phrases:
        words = [w for w in alignment.words if phrase.start_ms <= w.end_ms <= phrase.end_ms]
        out[phrase.phrase_id] = words[-1].end_ms if words else phrase.end_ms
    return out


def compose_film_anchor(
    anchor: Anchor,
    *,
    alignment: AudioAlignment,
    segment_offset_ms: int,
    fps: int,
    timeline_hash: str = "",
    alignment_hash: str = "",
) -> ResolvedAnchor:
    """行内锚点 + 段偏移 = film 锚点(R-P10-01 的正解)。

    segment_offset_ms: 该段在成片时间线上的起点。输出恒为 film-global。
    """
    line_local = resolve_anchor(
        Anchor(anchor.type, anchor.target, anchor.edge, anchor.offset_ms, "line-local"),
        dialogue_end_ms=dialogue_end_map(alignment), fps=fps,
        alignment_hash=alignment_hash, timeline_hash=timeline_hash)
    time_ms = segment_offset_ms + line_local.time_ms
    return ResolvedAnchor(
        anchor_id=line_local.anchor_id, source=line_local.source,
        time_ms=time_ms, frame=round(time_ms * fps / 1000),
        confidence=line_local.confidence, evidence=line_local.evidence)
