"""暖黑金图解的确定性模拟。

「能模拟就别画」：随机游走、抽样、排队、渗流等都由这里的真实模拟驱动，
渲染器只负责把模拟结果画出来，并标注「一次模拟」。
"""

from __future__ import annotations

import math
import random
from functools import lru_cache


def _rng(seed: int) -> random.Random:
    return random.Random(int(seed))


@lru_cache(maxsize=256)
def beads_plan(n: int = 54, bins: int = 9, seed: int = 7) -> tuple[tuple[float, float, int], ...]:
    """珠子落板：返回每颗珠子的 (落点 x, 落入时间 0..1, 最终槽位)。"""
    rng = _rng(seed)
    out: list[tuple[float, float, int]] = []
    for i in range(n):
        x = 0.5
        slot = 0
        for level in range(6):
            step = 0.5 ** (level + 1)
            if rng.random() < 0.5:
                x -= step * 0.55
                slot <<= 1
            else:
                x += step * 0.55
                slot = (slot << 1) | 1
        x = min(0.94, max(0.06, x))
        drop = (i + 1) / (n + 6)
        out.append((x, drop, slot % bins))
    return tuple(out)


@lru_cache(maxsize=256)
def threshold_graph(n: int = 49, seed: int = 11, p: float = 0.22) -> tuple[tuple[int, int], ...]:
    """固定一张随机图；调用方只改“亮起来的比例”，不重画图。"""
    rng = _rng(seed)
    side = math.ceil(math.sqrt(n))
    edges: list[tuple[int, int]] = []
    for i in range(n):
        r, c = divmod(i, side)
        for dr, dc in ((0, 1), (1, 0)):
            j = (r + dr) * side + (c + dc)
            if r + dr < side and c + dc < side and j < n and rng.random() < p:
                edges.append((i, j))
    return tuple(edges)


def threshold_reach(n: int, edges: tuple[tuple[int, int], ...], active: float) -> list[int]:
    """逐步点亮：返回当前已亮的节点（按 BFS 从 0 号开始，受 active 比例限制）。"""
    limit = max(1, round(n * active))
    adj: dict[int, list[int]] = {i: [] for i in range(n)}
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    lit = {0}
    frontier = [0]
    while frontier and len(lit) < limit:
        nxt: list[int] = []
        for node in frontier:
            for nb in adj[node]:
                if nb not in lit and len(lit) < limit and len(lit) < n:
                    lit.add(nb)
                    nxt.append(nb)
        frontier = nxt
    return sorted(lit)


@lru_cache(maxsize=128)
def walk_path(
    steps: int = 160, seed: int = 3, step: float = 0.016, bias: float = 0.0
) -> tuple[float, ...]:
    rng = _rng(seed)
    value = 0.5
    path = [value]
    for _ in range(steps):
        value += bias + rng.gauss(0.0, step)
        value = min(0.94, max(0.06, value))
        path.append(value)
    return tuple(path)


@lru_cache(maxsize=256)
def sample_points(
    total: int = 240, seed: int = 5, gold_ratio: float = 0.18
) -> tuple[tuple[float, float, int], ...]:
    """总体：240 个点，18% 是金色（少数派），其余象牙色。"""
    rng = _rng(seed)
    pts: list[tuple[float, float, int]] = []
    for i in range(total):
        x = rng.uniform(0.04, 0.96)
        y = rng.uniform(0.05, 0.72)
        pts.append((x, y, 1 if i < int(total * gold_ratio) else 0))
    rng.shuffle(pts)
    return tuple(pts)


@lru_cache(maxsize=256)
def queue_plan(lanes: int = 3, agents: int = 7, seed: int = 13) -> tuple[tuple[float, ...], ...]:
    """三条队：每条每个客户的完成时刻（越小越快）。真实来自服务时间抽样。"""
    rng = _rng(seed)
    out: list[tuple[float, ...]] = []
    for lane in range(lanes):
        t = 0.0
        times: list[float] = []
        rate = 0.075 + 0.012 * lane
        for _ in range(agents):
            t += rng.expovariate(1.0 / rate)
            times.append(round(t, 4))
        out.append(tuple(times))
    return tuple(out)


@lru_cache(maxsize=256)
def distribution_values(n: int = 60, seed: int = 17, outlier: float = 0.0) -> tuple[float, ...]:
    rng = _rng(seed)
    values = [min(0.86, max(0.04, rng.gauss(0.42, 0.09))) for _ in range(n)]
    if outlier:
        values.append(outlier)
    return tuple(values)


def mean(values: tuple[float, ...]) -> float:
    return sum(values) / max(1, len(values))


def median(values: tuple[float, ...]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


@lru_cache(maxsize=128)
def forgetting_curves(points: int = 90, seed: int = 19) -> tuple[tuple[float, float], ...]:
    """两条保持率曲线：集中突击 vs 间隔复习（教学示意，标注「示意」）。"""
    rng = _rng(seed)
    cram: list[float] = []
    spaced: list[float] = []
    c, s = 1.0, 1.0
    for i in range(points):
        c = max(0.06, c * (0.94 + rng.uniform(-0.012, 0.012)))
        if i in (18, 42, 66):
            s = min(1.0, s + 0.42)
        s = max(0.08, s * (0.985 + rng.uniform(-0.004, 0.004)))
        cram.append(round(c, 4))
        spaced.append(round(s, 4))
    return tuple(zip(cram, spaced, strict=True))


def bar_histogram(values: tuple[float, ...], bins: int = 10) -> list[float]:
    counts = [0] * bins
    for v in values:
        idx = min(bins - 1, max(0, int(v * bins)))
        counts[idx] += 1
    return [c / max(1, len(values)) for c in counts]


def sim_note(part_id: str) -> str:
    return (
        "一次模拟"
        if part_id
        in {"beads_funnel", "threshold_net", "random_walk", "sampling_box", "queue_lanes"}
        else "示意"
    )
