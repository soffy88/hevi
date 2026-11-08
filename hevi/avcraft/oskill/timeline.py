"""停顿剪辑 → 可编辑时间线（思路：Auto-Editor 的“有声区+边距”、BaoCut 的逐段可改时间线）。

时间线 JSON（schema avcraft.timeline/v1）:
{"schema","source","duration","params",
 "clips":[{"id","start","end","kind":"speech|pause","keep":bool,"reason","text"?}]}
人或 Agent 只需改 keep / start / end / text，再交给 export 渲染。
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "avcraft.timeline/v1"


def build_pause_timeline(
    silences: list[tuple[float, float]],
    duration: float,
    *,
    margin: float = 0.12,
    min_pause: float = 0.5,
    keep_pause_max: float = 0.0,
    min_speech: float = 0.15,
    source: str = "",
) -> dict:
    """silences→交替的 speech/pause 片段。

    - 静音两侧各留 margin 秒（防止吞字）；收缩后短于 min_pause 的静音视为语流内停顿，保留。
    - keep_pause_max>0 时，被剪停顿保留中间这么长（节奏不那么“跳”）。
    - 短于 min_speech 的孤立有声片段（咔哒声）标记为删除。
    """
    cuts: list[tuple[float, float]] = []
    for s, e in sorted(silences):
        a = s + (margin if s > 0 else 0.0)
        b = e - (margin if e < duration else 0.0)
        if b - a < min_pause:
            continue
        if keep_pause_max > 0:
            mid = (a + b) / 2
            half = min(keep_pause_max, b - a) / 2
            if b - a > keep_pause_max:
                cuts.append((a, mid - half))
                cuts.append((mid + half, b))
                continue
            continue
        cuts.append((round(a, 3), round(b, 3)))
    clips, t, i = [], 0.0, 0
    for a, b in cuts:
        if a > t:
            clips.append(
                {
                    "id": f"c{i}",
                    "start": round(t, 3),
                    "end": round(a, 3),
                    "kind": "speech",
                    "keep": True,
                    "reason": "voiced",
                }
            )
            i += 1
        clips.append(
            {
                "id": f"c{i}",
                "start": round(a, 3),
                "end": round(b, 3),
                "kind": "pause",
                "keep": False,
                "reason": f"silence {b - a:.2f}s",
            }
        )
        i += 1
        t = b
    if t < duration:
        clips.append(
            {
                "id": f"c{i}",
                "start": round(t, 3),
                "end": round(duration, 3),
                "kind": "speech",
                "keep": True,
                "reason": "voiced",
            }
        )
    for c in clips:
        if c["kind"] == "speech" and c["end"] - c["start"] < min_speech:
            c["keep"], c["reason"] = False, f"blip <{min_speech}s"
    return {
        "schema": SCHEMA,
        "source": source,
        "duration": round(duration, 3),
        "params": {
            "margin": margin,
            "min_pause": min_pause,
            "keep_pause_max": keep_pause_max,
            "min_speech": min_speech,
        },
        "clips": clips,
    }


def keep_ranges(tl: dict, join_gap: float = 0.02) -> list[tuple[float, float]]:
    """时间线里 keep=True 的区间，相邻（间隔≤join_gap）合并。"""
    out: list[list[float]] = []
    for c in sorted((c for c in tl["clips"] if c.get("keep")), key=lambda c: c["start"]):
        if out and c["start"] - out[-1][1] <= join_gap:
            out[-1][1] = max(out[-1][1], c["end"])
        else:
            out.append([c["start"], c["end"]])
    return [(a, b) for a, b in out if b > a]


def timeline_set_keep(tl: dict, clip_ids: list[str], keep: bool, reason: str = "manual") -> dict:
    ids = set(clip_ids)
    for c in tl["clips"]:
        if c["id"] in ids:
            c["keep"], c["reason"] = keep, reason
    return tl


# Persistence lives in obase/timeline_io.py (oskill must not own IO);
# re-exported here so the established import path keeps working.
from hevi.avcraft.obase.timeline_io import load_timeline, save_timeline

__all__ = ["load_timeline", "save_timeline"]


# ====================================================================== P1：统一编辑时间线
# 向后兼容扩展：同一份 avcraft.timeline/v1 可选再带
#   "cues":    [{"id","start","end","text","tr"?,"deleted":bool}]   —— 源时间轴上的字幕句
#   "markers": [{"t","kind":"scene","score"}]                          —— 场景切换点（只做参考/切分，不删）
#   "ops":     [...]                                                    —— 可回放的编辑操作日志
# 视频保留 = clips.keep；字幕输出 = 未删除 cues 经 map_time 映射到成片时间。


def timeline_from_cues(cues: list[dict], duration: float, *, source: str = "") -> dict:
    """由字幕句建一条“全保留”时间线（剪辑与字幕共用）。"""
    return {
        "schema": SCHEMA,
        "source": source,
        "duration": round(duration, 3),
        "params": {},
        "clips": [{"id": "c0", "start": 0.0, "end": round(duration, 3), "kind": "speech",
                   "keep": True, "reason": "init"}],
        "cues": [
            {"id": c.get("id", i + 1), "start": round(c["start"], 3), "end": round(c["end"], 3),
             "text": c["text"], **({"tr": c["tr"]} if c.get("tr") is not None else {}), "deleted": False}
            for i, c in enumerate(cues)
        ],
        "ops": [],
    }


def split_clips_at(tl: dict, times: list[float], eps: float = 1e-3) -> dict:
    """在给定时间点切分片段（子片段 id = 原id.k，继承 kind/keep/reason）。"""
    ts = sorted(set(round(t, 3) for t in times))
    out = []
    for c in sorted(tl["clips"], key=lambda c: c["start"]):
        cuts = [t for t in ts if c["start"] + eps < t < c["end"] - eps]
        if not cuts:
            out.append(c)
            continue
        edges = [c["start"], *cuts, c["end"]]
        for k, (a, b) in enumerate(zip(edges, edges[1:])):
            out.append({**c, "id": f"{c['id']}.{k}", "start": round(a, 3), "end": round(b, 3)})
    tl["clips"] = out
    return tl


def set_region_keep(tl: dict, start: float, end: float, keep: bool, reason: str,
                    *, protect_kinds: tuple = ()) -> int:
    """把 [start,end] 内的片段设为 keep（先切分）。protect_kinds 中的 kind 不改。返回改动数。"""
    split_clips_at(tl, [start, end])
    n = 0
    for c in tl["clips"]:
        if c["start"] >= start - 1e-3 and c["end"] <= end + 1e-3 and c["kind"] not in protect_kinds:
            if c["keep"] != keep:
                n += 1
            c["keep"], c["reason"] = keep, reason
    return n


def merge_cut_signals(tl: dict, signals: dict, policy: dict | None = None) -> dict:
    """把多路画面信号并入时间线（思路：Auto-Editor 多 edit 方法取并/交）。

    signals: {"black":[(s,e)],"freeze":[(s,e)],"scene":[(t,score)]}
    policy:  {"black":{"min":0.3,"protect_speech":False}, "freeze":{"min":2.0,"protect_speech":True,"keep_head":0.5}}
      - protect_speech=True：与有声片段/字幕句重叠的部分不删（解说配静帧不能剪）
      - keep_head：静止段保留开头这么多秒（避免硬跳）；speech_pad：保护有声区两侧余量
    scene 只作为切分点和 markers 写入，不删除。
    """
    pol = {"black": {"min": 0.3, "protect_speech": False},
           "freeze": {"min": 2.0, "protect_speech": True, "keep_head": 0.5, "speech_pad": 0.25}}
    for k, v in (policy or {}).items():
        pol[k] = {**pol.get(k, {}), **v}
    speech = [(c["start"], c["end"]) for c in tl.get("cues", []) if not c.get("deleted")]
    if not speech:
        speech = [(c["start"], c["end"]) for c in tl["clips"] if c["kind"] == "speech"]
    stats = {}
    for name in ("black", "freeze"):
        p = pol.get(name) or {}
        n = 0
        for s, e in signals.get(name, []):
            if e - s < p.get("min", 0):
                continue
            s2 = s + p.get("keep_head", 0.0)
            pieces = [(s2, e)]
            if p.get("protect_speech"):
                pad = p.get("speech_pad", 0.25)
                for a, b in speech:  # 从区间中扣掉有声部分（两侧留 pad，句间短间隙不剪）
                    a, b = a - pad, b + pad
                    nxt = []
                    for x, y in pieces:
                        if b <= x or a >= y:
                            nxt.append((x, y))
                            continue
                        if a > x:
                            nxt.append((x, a))
                        if b < y:
                            nxt.append((b, y))
                    pieces = nxt
            for x, y in pieces:
                if y - x >= 0.2:
                    n += set_region_keep(tl, x, y, False, f"{name} {s:.2f}-{e:.2f}")
        stats[name] = n
    scenes = signals.get("scene", [])
    if scenes:
        split_clips_at(tl, [t for t, _ in scenes])
        tl["markers"] = sorted(
            [m for m in tl.get("markers", []) if m.get("kind") != "scene"]
            + [{"t": round(t, 3), "kind": "scene", "score": round(sc, 2)} for t, sc in scenes],
            key=lambda m: m["t"])
    tl.setdefault("params", {})["visual_policy"] = pol
    tl["params"]["visual_stats"] = stats
    return tl


def _cue(tl: dict, cid) -> dict:
    for c in tl.get("cues", []):
        if str(c["id"]) == str(cid):
            return c
    raise KeyError(f"cue {cid} not found")


def apply_ops(tl: dict, ops: list[dict], *, record: bool = True) -> dict:
    """Agent/人 逐句编辑（BaoCut 思路），可回放：
      {"op":"delete","cue":id}           删句：字幕删除 + 视频区间 [start,end] 剪掉
      {"op":"restore","cue":id}          恢复
      {"op":"retext","cue":id,"text":..,"tr"?:..}   改字（tr 不给则标 tr_stale）
      {"op":"retime","cue":id,"start"?:..,"end"?:..} 改时（源时间轴，夹在相邻句之间）
      {"op":"drop"|"keep","start":s,"end":e}        直接按区间剪/留
    """
    for op in ops:
        kind = op["op"]
        if kind in ("delete", "restore"):
            c = _cue(tl, op["cue"])
            c["deleted"] = kind == "delete"
            tag = f"op:delete cue {c['id']}"
            if kind == "delete":  # 只动当前保留的片段，恢复时能精确回滚
                split_clips_at(tl, [c["start"], c["end"]])
                for k in tl["clips"]:
                    if k["keep"] and k["start"] >= c["start"] - 1e-3 and k["end"] <= c["end"] + 1e-3:
                        k["keep"], k["reason"] = False, tag
            else:
                for k in tl["clips"]:
                    if k["reason"] == tag:
                        k["keep"], k["reason"] = True, f"op:restore cue {c['id']}"
        elif kind == "retext":
            c = _cue(tl, op["cue"])
            c["text"] = op["text"]
            if "tr" in op:
                c["tr"], c["tr_stale"] = op["tr"], False
            elif c.get("tr"):
                c["tr_stale"] = True
        elif kind == "retime":
            cues = sorted(tl["cues"], key=lambda x: x["start"])
            c = _cue(tl, op["cue"])
            i = cues.index(c)
            lo = cues[i - 1]["end"] if i > 0 else 0.0
            hi = cues[i + 1]["start"] if i + 1 < len(cues) else tl["duration"]
            s = max(lo, float(op.get("start", c["start"])))
            e = min(hi, float(op.get("end", c["end"])))
            if e - s < 0.1:
                raise ValueError(f"retime cue {c['id']} collapses ({s},{e})")
            c["start"], c["end"] = round(s, 3), round(e, 3)
        elif kind in ("drop", "keep"):
            set_region_keep(tl, float(op["start"]), float(op["end"]), kind == "keep", f"op:{kind}")
        else:
            raise ValueError(f"unknown op {kind}")
        if record:
            tl.setdefault("ops", []).append(op)
    return tl


def map_time(ranges: list[tuple[float, float]], t: float, side: str = "start") -> float | None:
    """源时间 → 成片时间。t 落在被剪区间时：side=start 吸附到下一保留点，end 吸附到上一保留点。"""
    acc = 0.0
    for i, (a, b) in enumerate(ranges):
        if a - 1e-6 <= t <= b + 1e-6:
            return round(acc + min(max(t, a), b) - a, 3)
        if t < a:
            return round(acc, 3) if side == "start" else (round(acc, 3) if i else None)
        acc += b - a
    return round(acc, 3) if side == "end" and ranges else None


def render_cues(tl: dict, min_dur: float = 0.2) -> list[dict]:
    """未删除字幕句映射到成片时间轴（被剪掉的部分自动裁掉，完全被剪的句子丢弃）。"""
    ranges = keep_ranges(tl)
    out = []
    for c in sorted(tl.get("cues", []), key=lambda c: c["start"]):
        if c.get("deleted"):
            continue
        kept = sum(max(0.0, min(b, c["end"]) - max(a, c["start"])) for a, b in ranges)
        if kept < min_dur:
            continue
        s, e = map_time(ranges, c["start"], "start"), map_time(ranges, c["end"], "end")
        if s is None or e is None or e - s < min_dur:
            continue
        o = {k: v for k, v in c.items() if k not in ("deleted",)}
        o["start"], o["end"] = s, e
        out.append(o)
    for i in range(1, len(out)):  # 不重叠
        if out[i]["start"] < out[i - 1]["end"]:
            out[i - 1]["end"] = out[i]["start"]
    return out
