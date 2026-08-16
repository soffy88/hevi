"""帧预算 —— 按时长自动决定"喂给 LLM 多少帧"的 token 经济(3O 内化 Phase A)。

来源: bradautomates/claude-video 的 frame-budget 表。Token 成本由帧数主导;
长视频无脑全抽会烧穿上下文。规则(与来源一致,数值可被调用方覆盖):

  duration <= 30s      → 30 帧(密集)
  30s  < duration <= 1m → 40 帧
  1m   < duration <= 3m → 60 帧
  3m   < duration <= 10m→ 80 帧
  > 10m                 → 100 帧(稀疏扫描,提示聚焦重跑)

3O 归属(待上游): `oprim.frame_budget_for_duration`。纯算法,无 IO,可平移零改动。
"""

from __future__ import annotations

#: (上限秒, 帧数)。按 duration 升序;命中第一个 duration <= cap 的行。
FRAME_BUDGET_TABLE: tuple[tuple[float, int], ...] = (
    (30.0, 30),
    (60.0, 40),
    (180.0, 60),
    (600.0, 80),
    (float("inf"), 100),
)


def frame_budget_for_duration(duration_s: float, *, cap: int | None = None) -> int:
    """按时长取帧预算。

    Args:
        duration_s: 视频时长(秒)。<=0 视为未知,取最大档。
        cap: 可选硬上限(如用户显式限制 token 预算)。

    Returns:
        建议帧数(>= 1)。
    """
    if duration_s <= 0:
        budget = FRAME_BUDGET_TABLE[-1][1]
    else:
        budget = next(b for limit, b in FRAME_BUDGET_TABLE if duration_s <= limit)
    if cap is not None:
        budget = min(budget, max(cap, 1))
    return max(budget, 1)


def focused_budget(start_s: float | None, end_s: float | None, *, max_fps: float = 2.0) -> int:
    """聚焦模式:用户点名时间段(`--start/--end`)时的帧数。

    密集按秒取,封顶 2 fps(与来源一致)—— 聚焦 30 秒窗口远好过全片稀疏扫描。
    """
    if start_s is None and end_s is None:
        return 0  # 非聚焦,调用方应走 frame_budget_for_duration
    lo = start_s or 0.0
    hi = end_s if end_s is not None else lo + 60.0
    window = max(hi - lo, 1.0)
    return max(int(window * max_fps), 1)
