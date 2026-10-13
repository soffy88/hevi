"""定时分镜表 —— 每 10s 一段, 段内三拍, continuity 双向。

规则(STICKDIR_TASK.md §(a)):

* 每 10s 一段, 段内三拍 ``[0–3s][3–7s][7–10s]``, 每 2–3s 一个动作节拍。
* 每拍给 动作(pose)、道具、视觉隐喻、镜头(推/拉/摇/跟/震)、转场、SFX、BGM 提示。
* **段尾状态 = 下段开头状态**: 上一段最后一拍的动作 == 下一段第一拍的动作,
  ``continuity_out`` / ``continuity_in`` 两边都写。
* 9:16 用纵深/上下堆叠调度, 16:9 用左中右调度。
* 所有枚举项来自 :mod:`whitelist`;外部(LLM)供给的越界项由 :func:`sanitize_beats`
  修正或整条回退确定性方案。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hevi.layer4_legacy.stickdir import whitelist

#: 每段时长
SEGMENT_SECONDS = 10


@dataclass
class Beat:
    """一段内的一拍。"""

    index: int
    t0: float
    t1: float
    action: str
    prop: str
    metaphor: str
    camera: str
    staging: str
    sfx: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "t0": self.t0,
            "t1": self.t1,
            "action": self.action,
            "prop": self.prop,
            "metaphor": self.metaphor,
            "camera": self.camera,
            "staging": self.staging,
            "sfx": self.sfx,
            "note": self.note,
        }


@dataclass
class Segment:
    """一个 10s 段。"""

    index: int
    start: float
    end: float
    stage: str
    narration: str
    beats: list[Beat]
    transition: str
    bgm: str
    continuity_in: str
    continuity_out: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "stage": self.stage,
            "narration": self.narration,
            "beats": [b.to_dict() for b in self.beats],
            "transition": self.transition,
            "bgm": self.bgm,
            "continuity_in": self.continuity_in,
            "continuity_out": self.continuity_out,
        }


@dataclass
class Storyboard:
    aspect: str
    duration: int
    style: str
    segments: list[Segment]
    corrections: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "aspect": self.aspect,
            "duration": self.duration,
            "style": self.style,
            "segment_seconds": SEGMENT_SECONDS,
            "segments": [s.to_dict() for s in self.segments],
            "corrections": list(self.corrections),
        }


# ---------------------------------------------------------------------------
# 叙事弧 → 段映射
# ---------------------------------------------------------------------------


def arc_for(style: str) -> tuple[str, ...]:
    return whitelist.ARC_STAGES_STYLE3 if style == "3" else whitelist.ARC_STAGES


def allocate_stages(arc: tuple[str, ...], n: int) -> list[str]:
    """把 ``arc`` 的比例铺到 ``n`` 段上;首段=arc[0], 末段=arc[-1]。"""
    if n <= 0:
        raise ValueError("n must be >= 1")
    if n == 1:
        return [arc[-1]]
    out: list[str] = []
    for i in range(n):
        # 位置 i/(n-1) 映射到 arc 索引
        pos = i * (len(arc) - 1) / (n - 1)
        out.append(arc[int(round(pos))])
    out[0] = arc[0]
    out[-1] = arc[-1]
    return out


# ---------------------------------------------------------------------------
# 每叙事阶段的拍设计(确定性方案)
# ---------------------------------------------------------------------------

#: 阶段 → 3 拍 (action, prop, metaphor, camera) + 段级 sfx/transition/bgm
_STAGE_PLAN: dict[str, dict[str, Any]] = {
    "hook": {
        "beats": [
            ("surprise", "none", "iceberg", "push_in"),
            ("point", "arrow", "abyss", "track"),
            ("run", "none", "mountain", "pull_out"),
        ],
        "sfx": "riser",
        "transition": "whip_pan",
        "bgm": "curious",
    },
    "disrupt": {
        "beats": [
            ("think", "none", "mirror", "static"),
            ("shrug", "box", "maze", "pan"),
            ("walk", "none", "bridge", "track"),
        ],
        "sfx": "glitch",
        "transition": "match_cut",
        "bgm": "tense",
    },
    "mechanism": {
        "beats": [
            ("draw_line", "line", "funnel", "push_in"),
            ("raise", "gear", "domino", "orbit"),
            ("walk", "line", "ladder", "track"),
        ],
        "sfx": "click",
        "transition": "cut",
        "bgm": "calm",
    },
    "conclusion": {
        "beats": [
            ("point", "chart", "horizon", "pull_out"),
            ("raise", "chart", "mountain", "tilt"),
            ("celebrate", "none", "horizon", "static"),
        ],
        "sfx": "chime",
        "transition": "fade",
        "bgm": "warm",
    },
    "callback": {
        "beats": [
            ("think", "none", "mirror", "push_in"),
            ("point", "arrow", "bridge", "static"),
            ("wave", "none", "horizon", "pull_out"),
        ],
        "sfx": "ding",
        "transition": "fade",
        "bgm": "warm",
    },
    # Style 3 弧
    "setup": {
        "beats": [
            ("stand", "fire", "none", "static"),
            ("point", "spear", "none", "pan"),
            ("walk", "rock", "mountain", "track"),
        ],
        "sfx": "impact",
        "transition": "cut",
        "bgm": "playful",
    },
    "escalation": {
        "beats": [
            ("march", "spear", "domino", "track"),
            ("push_door", "door", "cage", "push_in"),
            ("run", "rope", "abyss", "shake"),
        ],
        "sfx": "boom",
        "transition": "whip_pan",
        "bgm": "tense",
    },
    "payoff": {
        "beats": [
            ("sit", "fire", "hourglass", "pull_out"),
            ("shrug", "none", "mirror", "static"),
            ("wave", "none", "horizon", "pull_out"),
        ],
        "sfx": "downer",
        "transition": "fade",
        "bgm": "somber",
    },
}

#: 动作是否"有持续运动"(用于段尾锚点选择)
_MOVING = {"walk", "run", "jump", "march", "dance", "wave", "celebrate", "shuffle", "twist", "kick"}


def _staging_sequence(aspect: str, seg_index: int) -> list[str]:
    """该画幅下的调度序列(每段旋转起点, 保证段间不同)。"""
    options = whitelist.staging_for(aspect)
    n = len(options)
    start = (seg_index * 2) % n
    return [options[(start + i) % n] for i in range(len(whitelist.BEATS))]


def sanitize_beats(
    raw_beats: list[dict[str, Any]],
    aspect: str,
    seg_index: int,
    fallback: dict[str, Any],
) -> tuple[list[dict[str, str]], list[str]]:
    """把外部(LLM)拍选择收敛到白名单;越界项修正, 无法修正则整拍回退。"""
    corrections: list[str] = []
    staging = _staging_sequence(aspect, seg_index)
    out: list[dict[str, str]] = []
    fb_beats = fallback["beats"]
    for i in range(len(whitelist.BEATS)):
        src = raw_beats[i] if i < len(raw_beats) and isinstance(raw_beats[i], dict) else {}
        fb = fb_beats[i] if i < len(fb_beats) else fb_beats[-1]
        row: dict[str, str] = {}
        for j, field_name in enumerate(("action", "prop", "metaphor", "camera")):
            val = str(src.get(field_name) or "")
            default = fb[j]
            fixed, changed = whitelist.coerce(field_name, val, default)
            row[field_name] = fixed
            if changed and val:
                corrections.append(f"seg{seg_index} beat{i} {field_name}={val!r} -> {fixed!r}")
        row["staging"] = staging[i]
        out.append(row)
    return out, corrections


# ---------------------------------------------------------------------------
# 旁白 → 段分配
# ---------------------------------------------------------------------------


def distribute_narration(stages: list[dict[str, str]], segment_stages: list[str]) -> list[str]:
    """把旁白按叙事顺序均衡分配到各段(按字数预算, 保证不越段)。

    先按句拆分(保留叙事顺序), 再贪心装段:每段约 ``total/n`` 字;遇到叙事阶段
    边界且当前段已过 60% 预算时提前换段。这样每段旁白 ≈ 10s, 段间不重叠。
    """
    import re

    n = len(segment_stages)
    if n == 0:
        return []
    clause_re = re.compile(r"[^。！？；，、]+[。！？；，、]?")
    sents: list[tuple[str, str]] = []  # (stage, clause)
    for s in stages:
        clauses = [c.strip() for c in clause_re.findall(s["text"]) if c.strip()]
        for sent in clauses or [s["text"]]:
            sents.append((s["stage"], sent))
    if not sents:
        return [""] * n

    total = sum(len(sent) for _st, sent in sents)
    # 按"句中点占全文的比例"分配段号, 保证各段字数尽量均等且不越段
    buckets: list[list[str]] = [[] for _ in range(n)]
    cum = 0
    for _stage, sent in sents:
        mid = cum + len(sent) / 2
        bucket = min(int(mid / max(total, 1) * n), n - 1)
        buckets[bucket].append(sent)
        cum += len(sent)
    return ["".join(b) for b in buckets]


# ---------------------------------------------------------------------------
# 组装
# ---------------------------------------------------------------------------


def build_storyboard(
    *,
    aspect: str,
    duration: int,
    style: str,
    narration_stages: list[dict[str, str]] | None = None,
    llm_beats: list[list[dict[str, Any]]] | None = None,
) -> Storyboard:
    """构造定时分镜表。

    ``llm_beats``(可选)是 LLM 给出的每段拍选择, 经白名单收敛;越界项记入
    ``corrections``。
    """
    if aspect not in whitelist.ASPECT:
        raise ValueError(f"aspect must be one of {whitelist.ASPECT}; got {aspect!r}")
    if style not in whitelist.STYLE:
        raise ValueError(f"style must be one of {whitelist.STYLE}; got {style!r}")
    if duration % SEGMENT_SECONDS != 0:
        raise ValueError(f"duration must be a multiple of {SEGMENT_SECONDS}; got {duration}")

    arc = arc_for(style)
    n = duration // SEGMENT_SECONDS
    seg_stages = allocate_stages(arc, n)
    narr = distribute_narration(narration_stages or [], seg_stages)

    segments: list[Segment] = []
    corrections: list[str] = []
    prev_out = "pose:stand"

    for i in range(n):
        stage = seg_stages[i]
        plan = _STAGE_PLAN[stage]
        if llm_beats is not None and i < len(llm_beats):
            rows, corr = sanitize_beats(llm_beats[i], aspect, i, plan)
            corrections.extend(corr)
        else:
            staging = _staging_sequence(aspect, i)
            rows = [
                {
                    "action": b[0],
                    "prop": b[1],
                    "metaphor": b[2],
                    "camera": b[3],
                    "staging": staging[k],
                }
                for k, b in enumerate(plan["beats"])
            ]

        # 段首继承上段段尾动作(continuity)
        if i > 0:
            inherited = prev_out.split(":", 1)[1]
            if inherited in whitelist.ACTION:
                rows[0]["action"] = inherited

        beats: list[Beat] = []
        for k, row in enumerate(rows):
            t0, t1 = whitelist.BEATS[k]
            beats.append(
                Beat(
                    index=k,
                    t0=t0,
                    t1=t1,
                    action=row["action"],
                    prop=row["prop"],
                    metaphor=row["metaphor"],
                    camera=row["camera"],
                    staging=row["staging"],
                    sfx=plan["sfx"] if k == 2 else "none",
                    note=whitelist.BEAT_LABELS[k],
                )
            )
        out_action = beats[-1].action
        if out_action not in _MOVING:
            # 段尾锚点必须是"有运动"的动作, 否则 3s 窗口内轮廓不变
            out_action = "walk"
            beats[-1].action = out_action
            corrections.append(f"seg{i} climax action forced to moving anchor 'walk'")
        cont_out = f"pose:{out_action}"
        segments.append(
            Segment(
                index=i,
                start=float(i * SEGMENT_SECONDS),
                end=float((i + 1) * SEGMENT_SECONDS),
                stage=stage,
                narration=narr[i] if i < len(narr) else "",
                beats=beats,
                transition=plan["transition"],
                bgm=plan["bgm"],
                continuity_in=prev_out,
                continuity_out=cont_out,
            )
        )
        prev_out = cont_out

    return Storyboard(
        aspect=aspect, duration=duration, style=style, segments=segments, corrections=corrections
    )


def check_continuity(sb: Storyboard) -> list[str]:
    """校验段尾/段首一致;返回违规描述(空 = 通过)。"""
    bad: list[str] = []
    for i in range(len(sb.segments) - 1):
        a, b = sb.segments[i], sb.segments[i + 1]
        if a.continuity_out != b.continuity_in:
            bad.append(f"seg{i}.out={a.continuity_out!r} != seg{i + 1}.in={b.continuity_in!r}")
        if a.beats[-1].action != b.beats[0].action:
            bad.append(
                f"seg{i} end action {a.beats[-1].action!r} != seg{i + 1} start {b.beats[0].action!r}"
            )
    return bad


def check_staging(sb: Storyboard) -> list[str]:
    """校验调度位置属于该画幅白名单。"""
    allowed = set(whitelist.staging_for(sb.aspect))
    bad: list[str] = []
    for seg in sb.segments:
        for beat in seg.beats:
            if beat.staging not in allowed:
                bad.append(
                    f"seg{seg.index} beat{beat.index} staging {beat.staging!r} not in {allowed}"
                )
    return bad


__all__ = [
    "SEGMENT_SECONDS",
    "Beat",
    "Segment",
    "Storyboard",
    "allocate_stages",
    "arc_for",
    "build_storyboard",
    "check_continuity",
    "check_staging",
    "distribute_narration",
    "sanitize_beats",
]
