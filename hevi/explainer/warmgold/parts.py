"""暖黑金图解的零件库。

每个零件是一个可复用的“演示段”：它要证明什么、一个点代表什么、只改哪个条件、
观众看到的结果、结论与适用条件。零件只产出与风格无关的图元，渲染器统一上色。
清单落到 ``parts.json``，新增零件会自动出现在清单里。
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hevi.explainer.warmgold import simulate

Primitive = dict[str, Any]


@dataclass(frozen=True)
class PartSpec:
    id: str
    label: str
    proves: str  # 要证明的变化
    reference: str  # 不变参照
    one_dot_means: str  # 一个点代表什么
    only_changed: str  # 只改的条件
    conclusion: str  # 结论与适用条件
    simulated: bool
    draw: Callable[[dict[str, Any], float], dict[str, Any]] = field(repr=False, compare=False)

    def six_lines(self) -> dict[str, str]:
        return {
            "要证明的变化": self.proves,
            "不变参照": self.reference,
            "一个点代表什么": self.one_dot_means,
            "只改的条件": self.only_changed,
            "观众看到的结果": self.conclusion,
            "适用条件": "只在画面标明的条件下成立；不推广成人生结论。",
        }

    def manifest(self) -> dict[str, Any]:
        data = {k: v for k, v in asdict(self).items() if k != "draw"}
        data["six_lines"] = self.six_lines()
        return data


def _c(x: float, y: float, r: float, fill: str = "gold", opacity: float = 1.0) -> Primitive:
    return {"k": "c", "x": x, "y": y, "r": r, "f": fill, "o": round(opacity, 3)}


def _l(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    fill: str = "gold",
    width: float = 1.0,
    opacity: float = 1.0,
) -> Primitive:
    return {
        "k": "l",
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "f": fill,
        "w": width,
        "o": round(opacity, 3),
    }


def _r(
    x: float,
    y: float,
    w: float,
    h: float,
    fill: str = "panel",
    opacity: float = 1.0,
    stroke: str = "",
) -> Primitive:
    return {
        "k": "r",
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "f": fill,
        "o": round(opacity, 3),
        "s": stroke,
    }


def _t(
    x: float,
    y: float,
    text: str,
    size: float = 0.026,
    fill: str = "ivory_dim",
    anchor: str = "middle",
) -> Primitive:
    return {"k": "t", "x": x, "y": y, "s": text, "size": size, "f": fill, "a": anchor}


def _p(
    points: list[tuple[float, float]], fill: str = "gold", width: float = 1.4, opacity: float = 1.0
) -> Primitive:
    return {
        "k": "p",
        "pts": [[round(x, 4), round(y, 4)] for x, y in points],
        "f": fill,
        "w": width,
        "o": round(opacity, 3),
    }


def _ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


def draw_beads_funnel(params: dict[str, Any], t: float) -> dict[str, Any]:
    n = int(params.get("n", 54))
    bins = int(params.get("bins", 9))
    plan = simulate.beads_plan(n, bins, int(params.get("seed", 7)))
    items: list[Primitive] = [
        _l(0.30, 0.06, 0.50, 0.28, "gold", 1.2),
        _l(0.70, 0.06, 0.50, 0.28, "gold", 1.2),
        _l(0.30, 0.06, 0.70, 0.06, "gold", 0.8, 0.5),
    ]
    shown = 0
    counts = [0] * bins
    for x, drop, slot in plan:
        if t < drop:
            continue
        shown += 1
        p = min(1.0, (t - drop) / 0.22)
        y = 0.28 + 0.38 * _ease(p)
        items.append(_c(x, y, 0.010, "gold_bright" if p < 1 else "gold", 0.95 if p < 1 else 0.6))
        if p >= 1:
            counts[slot] += 1
    for i in range(bins):
        h = 0.030 + 0.34 * (counts[i] / max(1, n))
        x = 0.08 + i * (0.84 / bins)
        items.append(_r(x, 0.94 - h, 0.84 / bins * 0.72, h, "gold", 0.35, "gold"))
    items.append(_t(0.5, 0.99, "个体落点随机 · 整体形状稳定", 0.022))
    return {"items": items, "readout": f"{shown}/{n}", "simulated": True, "anchor": "落下的珠子"}


def draw_survivors_dim(params: dict[str, Any], t: float) -> dict[str, Any]:
    total = int(params.get("total", 12))
    keep = int(params.get("keep", 1))
    items: list[Primitive] = []
    for i in range(total):
        x = 0.08 + i * (0.84 / max(1, total - 1))
        dim_at = (i + 1) / (total + 2)
        is_kept = i == total - 1 - keep // 2
        if is_kept:
            fill, op = "gold_bright", 1.0
        elif t >= dim_at:
            fill, op = "past", 0.35
        else:
            fill, op = "ivory", 0.85
        items.append(_c(x, 0.42, 0.026, fill, op))
        items.append(_l(x, 0.46, x, 0.64, fill, 1.4, op))
        items.append(_l(x - 0.025, 0.56, x + 0.025, 0.56, fill, 1.2, op))
    items.append(_t(0.5, 0.78, f"看得到的 {keep} 个 · 看不到的 {total - keep} 个", 0.024))
    return {"items": items, "readout": f"{keep}/{total}", "simulated": False, "anchor": "一排人"}


def draw_threshold_net(params: dict[str, Any], t: float) -> dict[str, Any]:
    n = int(params.get("n", 49))
    edges = simulate.threshold_graph(n, int(params.get("seed", 11)), float(params.get("p", 0.22)))
    active = min(1.0, 0.05 + 0.95 * _ease(t))
    lit = set(simulate.threshold_reach(n, edges, active))
    side = 7
    items: list[Primitive] = []
    pos = {
        i: (0.12 + (i % side) * (0.76 / (side - 1)), 0.16 + (i // side) * (0.56 / (side - 1)))
        for i in range(n)
    }
    for a, b in edges:
        on = a in lit and b in lit
        items.append(
            _l(
                pos[a][0],
                pos[a][1],
                pos[b][0],
                pos[b][1],
                "gold" if on else "past",
                1.0,
                0.9 if on else 0.18,
            )
        )
    for i in range(n):
        x, y = pos[i]
        items.append(
            _c(
                x,
                y,
                0.014 if i in lit else 0.010,
                "gold_bright" if i in lit else "past",
                1.0 if i in lit else 0.35,
            )
        )
    items.append(_t(0.5, 0.80, f"点亮比例 {int(active * 100)}%", 0.024))
    return {"items": items, "readout": f"{len(lit)}/{n}", "simulated": True, "anchor": "一张网"}


def draw_gauge(params: dict[str, Any], t: float) -> dict[str, Any]:
    base = float(params.get("base", 3.2))
    span = float(params.get("span", 2.0))
    path = simulate.walk_path(120, int(params.get("seed", 3)), 0.05)
    value = base + span * (path[min(len(path) - 1, int(t * (len(path) - 1)))] - 0.5)
    frac = max(0.0, min(1.0, (value - (base - span / 2)) / span))
    angle = math.pi * (1 - frac)
    cx, cy, R = 0.5, 0.66, 0.30
    items = [_l(cx - R, cy, cx + R, cy, "gold", 1.0, 0.4)]
    for i in range(11):
        a = math.pi * (1 - i / 10)
        r0 = R - 0.02 if i % 5 else R - 0.04
        items.append(
            _l(
                cx + r0 * math.cos(a),
                cy - r0 * math.sin(a),
                cx + R * math.cos(a),
                cy - R * math.sin(a),
                "gold",
                1.2,
                0.8,
            )
        )
    items.append(
        _l(
            cx,
            cy,
            cx + (R - 0.05) * math.cos(angle),
            cy - (R - 0.05) * math.sin(angle),
            "gold_bright",
            2.4,
        )
    )
    items.append(_c(cx, cy, 0.014, "ivory"))
    items.append(_t(cx, 0.80, f"{value:.1f}", 0.05, "ivory"))
    return {"items": items, "readout": f"{value:.1f}", "simulated": True, "anchor": "一个读数"}


def draw_timeline(params: dict[str, Any], t: float) -> dict[str, Any]:
    labels = params.get("labels") or ["起点", "变化", "现在"]
    items: list[Primitive] = [_l(0.08, 0.55, 0.92, 0.55, "gold", 1.2, 0.7)]
    play = 0.08 + 0.84 * _ease(t)
    for i, label in enumerate(labels):
        x = 0.08 + 0.84 * (i / max(1, len(labels) - 1))
        on = x <= play + 1e-6
        items.append(_c(x, 0.55, 0.014, "gold_bright" if on else "past", 1.0 if on else 0.3))
        items.append(_t(x, 0.44, label, 0.024, "ivory" if on else "past"))
    items.append(_l(play, 0.40, play, 0.70, "ivory", 1.4, 0.8))
    return {"items": items, "readout": None, "simulated": False, "anchor": "一条时间轴"}


def draw_fork(params: dict[str, Any], t: float) -> dict[str, Any]:
    labels = params.get("labels") or ["不改", "只改这一件"]
    items: list[Primitive] = [_l(0.5, 0.86, 0.5, 0.60, "ivory", 1.6, 0.8)]
    up = _ease(min(1.0, t / 0.55))
    down = _ease(max(0.0, (t - 0.35) / 0.55))
    items.append(_l(0.5, 0.60, 0.50 - 0.30 * up, 0.30, "past", 1.6, 0.5 + 0.5 * up))
    items.append(_l(0.5, 0.60, 0.50 + 0.30 * down, 0.30, "gold_bright", 2.0, 0.4 + 0.6 * down))
    items.append(_t(0.22, 0.24, labels[0], 0.026, "ivory_dim"))
    items.append(_t(0.78, 0.24, labels[1], 0.026, "ivory" if down > 0.5 else "past"))
    items.append(_c(0.5, 0.60, 0.012, "gold"))
    return {"items": items, "readout": None, "simulated": False, "anchor": "一个分叉"}


def draw_balance(params: dict[str, Any], t: float) -> dict[str, Any]:
    left = float(params.get("left", 0.25))
    right = float(params.get("right", 0.75))
    diff = (right - left) * _ease(t)
    angle = max(-0.22, min(0.22, diff * 0.25))
    cx = 0.5
    dx, dy = math.cos(angle), math.sin(angle)
    items = [_l(cx - 0.30 * dx, 0.52 - 0.30 * dy, cx + 0.30 * dx, 0.52 + 0.30 * dy, "gold", 2.0)]
    items.append(_l(cx, 0.52, cx, 0.78, "gold", 1.2, 0.8))
    items.append(_l(cx - 0.10, 0.78, cx + 0.10, 0.78, "gold", 1.4))
    items.append(
        _l(cx - 0.30 * dx, 0.52 - 0.30 * dy, cx - 0.30 * dx, 0.44 - 0.30 * dy, "past", 1.0, 0.7)
    )
    items.append(
        _l(cx + 0.30 * dx, 0.52 + 0.30 * dy, cx + 0.30 * dx, 0.44 + 0.30 * dy, "past", 1.0, 0.7)
    )
    items.append(_t(cx - 0.30 * dx, 0.40 - 0.30 * dy, f"{left:.0%}", 0.028, "ivory_dim"))
    items.append(_t(cx + 0.30 * dx, 0.40 + 0.30 * dy, f"{right:.0%}", 0.028, "ivory"))
    return {"items": items, "readout": None, "simulated": False, "anchor": "一杆天平"}


def draw_cum_jump(params: dict[str, Any], t: float) -> dict[str, Any]:
    n = 80
    pts: list[tuple[float, float]] = []
    for i in range(n + 1):
        p = i / n
        if p > t + 1e-9:
            break
        y = 0.86 - 0.58 * (p**2.2)
        if p > 0.62:
            y -= 0.16 * _ease((p - 0.62) / 0.18)
        pts.append((0.08 + 0.84 * p, y))
    items = [
        _l(0.08, 0.86, 0.08, 0.16, "gold", 0.8, 0.5),
        _l(0.08, 0.86, 0.94, 0.86, "gold", 0.8, 0.5),
    ]
    if len(pts) > 1:
        items.append(_p(pts, "gold_bright", 2.4))
    if pts:
        items.append(_c(pts[-1][0], pts[-1][1], 0.013, "ivory"))
    items.append(_t(0.5, 0.96, "前段几乎不动 · 过阈值才突变", 0.022))
    return {"items": items, "readout": None, "simulated": False, "anchor": "一条累积曲线"}


def draw_random_walk(params: dict[str, Any], t: float) -> dict[str, Any]:
    path = simulate.walk_path(160, int(params.get("seed", 3)))
    idx = max(2, int(len(path) * _ease(t)))
    items = [_l(0.08, 0.52, 0.94, 0.52, "past", 1.0, 0.6)]
    items.append(_t(0.90, 0.48, "参照线", 0.02, "past"))
    pts = [(0.08 + 0.84 * i / (len(path) - 1), 0.80 - 0.56 * path[i]) for i in range(idx)]
    items.append(_p(pts, "gold_bright", 2.0))
    items.append(_c(pts[-1][0], pts[-1][1], 0.012, "ivory"))
    items.append(_t(0.5, 0.94, "每一步都随机 · 走久了有方向", 0.022))
    return {
        "items": items,
        "readout": f"{path[idx - 1]:.2f}",
        "simulated": True,
        "anchor": "一条随机路径",
    }


def draw_sampling_box(params: dict[str, Any], t: float) -> dict[str, Any]:
    pts = simulate.sample_points(
        240, int(params.get("seed", 5)), float(params.get("gold_ratio", 0.18))
    )
    radius = 0.04 + 0.30 * _ease(t)
    items: list[Primitive] = []
    sampled_gold = sampled_total = 0
    for x, y, gold in pts:
        inside = (x - 0.5) ** 2 + (y - 0.40) ** 2 <= radius**2
        if inside:
            sampled_total += 1
            sampled_gold += gold
        items.append(_c(x, y, 0.007, "gold" if gold else "past", 0.9 if gold else 0.45))
    items.append(_c(0.5, 0.40, radius, "none", 0.0))
    items.append({"k": "ring", "x": 0.5, "y": 0.40, "r": radius, "f": "ivory", "o": 0.55})
    ratio = sampled_gold / max(1, sampled_total)
    items.append(_t(0.5, 0.80, f"样本里金色占 {ratio:.0%} · 总体 18%", 0.023))
    return {
        "items": items,
        "readout": f"{sampled_total}",
        "simulated": True,
        "anchor": "一个抽样框",
    }


def draw_queue_lanes(params: dict[str, Any], t: float) -> dict[str, Any]:
    lanes = simulate.queue_plan(3, 7, int(params.get("seed", 13)))
    you = int(params.get("lane", 1))
    items: list[Primitive] = []
    for li, times in enumerate(lanes):
        y = 0.22 + li * 0.20
        label = "你这条" if li == you else f"第 {li + 1} 条"
        items.append(_t(0.05, y + 0.012, label, 0.021, "ivory" if li == you else "past", "start"))
        items.append(
            _l(0.24, y, 0.92, y, "gold" if li == you else "past", 1.0, 0.8 if li == you else 0.35)
        )
        for when in times:
            x = 0.24 + 0.68 * min(1.0, when / 0.95)
            on = t >= min(1.0, when / 0.95)
            items.append(
                _c(
                    x,
                    y,
                    0.011,
                    ("gold_bright" if li == you else "ivory") if on else "past",
                    1.0 if on else 0.25,
                )
            )
    items.append(_t(0.5, 0.90, "3 条队里，至少 1 条比你快：2/3", 0.022))
    return {"items": items, "readout": "2/3", "simulated": True, "anchor": "三条队"}


def draw_distribution_shift(params: dict[str, Any], t: float) -> dict[str, Any]:
    outlier = 0.0 if t < 0.55 else 1.0
    values = simulate.distribution_values(60, int(params.get("seed", 17)), outlier)
    hist = simulate.bar_histogram(values, 12)
    items: list[Primitive] = []
    peak = max(hist) or 1.0
    for i, h in enumerate(hist):
        x = 0.08 + i * (0.84 / 12)
        items.append(
            _r(
                x,
                0.82 - 0.56 * h / peak,
                0.84 / 12 * 0.72,
                0.56 * h / peak,
                "gold" if i < 10 else "danger",
                0.55,
            )
        )
    med = simulate.median(values)
    avg = simulate.mean(values)
    items.append(_l(0.08 + 0.84 * med, 0.18, 0.08 + 0.84 * med, 0.84, "gold_bright", 2.0))
    items.append(_t(0.08 + 0.84 * med, 0.14, "中位数", 0.021, "gold_bright"))
    items.append(
        _l(0.08 + 0.84 * min(0.99, avg), 0.18, 0.08 + 0.84 * min(0.99, avg), 0.84, "danger", 2.0)
    )
    items.append(_t(0.08 + 0.84 * min(0.99, avg), 0.24, "平均数", 0.021, "danger"))
    return {
        "items": items,
        "readout": f"{med:.2f} / {avg:.2f}",
        "simulated": True,
        "anchor": "一张分布",
    }


def draw_dual_curves(params: dict[str, Any], t: float) -> dict[str, Any]:
    curves = simulate.forgetting_curves(90, int(params.get("seed", 19)))
    idx = max(2, int(len(curves) * _ease(t)))
    cram = [(0.08 + 0.84 * i / (len(curves) - 1), 0.84 - 0.62 * curves[i][0]) for i in range(idx)]
    spaced = [(0.08 + 0.84 * i / (len(curves) - 1), 0.84 - 0.62 * curves[i][1]) for i in range(idx)]
    items = [
        _l(0.08, 0.84, 0.08, 0.14, "gold", 0.8, 0.4),
        _l(0.08, 0.84, 0.94, 0.84, "gold", 0.8, 0.4),
    ]
    items.append(_p(cram, "past", 1.8))
    items.append(_p(spaced, "gold_bright", 2.4))
    items.append(_t(0.80, 0.24, "间隔复习", 0.021, "gold_bright"))
    items.append(_t(0.80, 0.34, "集中突击", 0.021, "past"))
    items.append(_t(0.5, 0.94, "同样总时长 · 只改复习间隔", 0.022))
    return {"items": items, "readout": None, "simulated": False, "anchor": "两条曲线"}


PARTS: tuple[PartSpec, ...] = (
    PartSpec(
        "beads_funnel",
        "珠子落板",
        "个体落点随机，整体分布稳定",
        "板的形状与珠子总数",
        "一颗珠子",
        "只让每次落点随机",
        "单个结果不可预测，整体形状可预测。",
        True,
        draw_beads_funnel,
    ),
    PartSpec(
        "survivors_dim",
        "幸存者变暗",
        "只看见留下来的，会高估成功率",
        "同一批出发的人",
        "一个人",
        "只改‘是否被看见’",
        "结论只适用于被看见的样本；看不见的那部分决定真实比例。",
        False,
        draw_survivors_dim,
    ),
    PartSpec(
        "threshold_net",
        "网络过阈值",
        "连接足够多时，整体突然连通",
        "同一张网络",
        "一个节点",
        "只改点亮比例",
        "阈值前后是两种状态；阈值位置取决于网络结构。",
        True,
        draw_threshold_net,
    ),
    PartSpec(
        "gauge",
        "读数表",
        "感觉会漂，读数要对着参照看",
        "刻度本身",
        "一个读数",
        "只改被测的量",
        "读数变化不等于原因；先确认刻度没动。",
        True,
        draw_gauge,
    ),
    PartSpec(
        "timeline",
        "时间轴",
        "把‘一直’拆成可核对的三段",
        "同一根时间轴",
        "一个时间点",
        "只改观察窗口",
        "结论只在标注的时间窗口内成立。",
        False,
        draw_timeline,
    ),
    PartSpec(
        "fork",
        "分叉",
        "同一个起点，只改一个条件就分岔",
        "共同的起点",
        "一条路径",
        "只改一个条件",
        "分岔后的差异归给那个条件，不归给运气。",
        False,
        draw_fork,
    ),
    PartSpec(
        "balance",
        "对比天平",
        "两边一起看，才知道哪边更重",
        "同一把秤",
        "一份重量",
        "只改一侧的量",
        "只看单边会误判；比较必须同尺度。",
        False,
        draw_balance,
    ),
    PartSpec(
        "cum_jump",
        "累积突变",
        "前段几乎不动，过阈值才突变",
        "同一条累积曲线",
        "一次累积",
        "只改累积量",
        "线性和非线性要分开看；阈值由机制决定。",
        False,
        draw_cum_jump,
    ),
    PartSpec(
        "random_walk",
        "随机游走",
        "每一步随机，走久了出现方向",
        "一条固定参照线",
        "一步",
        "只改时间长度",
        "短期看运气，长期看漂移项。",
        True,
        draw_random_walk,
    ),
    PartSpec(
        "sampling_box",
        "抽样框",
        "样本不等于总体",
        "同一个总体",
        "一个样本点",
        "只改抽样范围",
        "样本比例偏离总体时，先问抽样是否随机。",
        True,
        draw_sampling_box,
    ),
    PartSpec(
        "queue_lanes",
        "三条队",
        "你这条最慢，常常只是因为你只看得见自己这条",
        "同一段时间",
        "一个排队的人",
        "只改你站哪条",
        "单次体验不能证明队伍有问题；比较所有队才成立。",
        True,
        draw_queue_lanes,
    ),
    PartSpec(
        "distribution_shift",
        "分布平移",
        "平均数被少数极端值拉动，中位数不动",
        "同一张分布图",
        "一个人",
        "只改是否加入极端值",
        "看平均数前先看分布形状；偏态数据用中位数。",
        True,
        draw_distribution_shift,
    ),
    PartSpec(
        "dual_curves",
        "双曲线",
        "同样总时长，间隔不同结果不同",
        "同样的总复习时间",
        "一次复习",
        "只改复习间隔",
        "结论只在记忆类任务、标注的时间范围内成立。",
        False,
        draw_dual_curves,
    ),
)

PARTS_BY_ID = {part.id: part for part in PARTS}
PART_IDS = tuple(part.id for part in PARTS)


def get_part(part_id: str) -> PartSpec:
    try:
        return PARTS_BY_ID[part_id]
    except KeyError as exc:
        raise KeyError(f"unknown part: {part_id}; available={', '.join(PART_IDS)}") from exc


def draw(part_id: str, params: dict[str, Any] | None, t: float) -> dict[str, Any]:
    spec = get_part(part_id)
    payload = spec.draw(dict(params or {}), min(1.0, max(0.0, t)))
    payload.setdefault("items", [])
    payload["part_id"] = part_id
    payload["sim_note"] = simulate.sim_note(part_id)
    payload["six_lines"] = spec.six_lines()
    return payload


def parts_manifest() -> dict[str, Any]:
    return {
        "style": "warm_gold_diagram",
        "count": len(PARTS),
        "parts": [part.manifest() for part in PARTS],
    }


def write_parts(path: Path | None = None) -> Path:
    target = Path(path) if path else Path(__file__).with_suffix("") / "parts.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(parts_manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target
