"""G0.2-C Anchor Resolver spike — 无状态语义锚点解析.

不是 Timeline,不拥有时间:只读 runtime_state(dialogue 事件 + fps),
输出 {frame, time_ms}。Timeline wins on 字段,本模块只做 anchor -> 时刻换算。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Anchor:
    type: str  # AFTER_DIALOGUE(本 spike 唯一支持的类型)
    target: str  # ScriptUnit unit_id(依赖 Spike A)
    edge: str = "start"
    offset_ms: int = 0  # 可为负,整数;语义:相对 dialogue end 的偏移


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
