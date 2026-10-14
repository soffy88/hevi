"""交付承诺 × 实测运动证据 —— 把排产前定死的承诺拿到合成前门对账(oskill 边界, 零 I/O)。

背景(为什么需要这个纯算法): `hevi/production/delivery_promise.py` 在**排产前**把
"这单承诺交付什么"定死(motion_led / avatar_presenter 之类), 并写进每集任务的
config_json(`hevi/season_planner/dispatch.py::resolve_delivery_promise`)。但承诺本身
不含证据 —— 要证明成片真的兑现了, 必须把**量出来的**帧序列折算成承诺能读懂的切点
清单, 再交回 `DeliveryPromise.validate_cuts` 判。

本模块只做这一层折算, 不 import 生产合同、不解码、不落盘:
  `cuts_from_segments()`  : 实测的稠密帧分段 → 切点描述符(有运动的算 motion)
  `motion_evidence()`     : 折算出的运动比 / 静帧比, 供人话理由使用

切点描述符沿用 delivery_promise 认识的形状: ``{"source": ..., "type": ...}``,
其中 type ∈ delivery_promise._REAL_MOTION_TYPES 记为真实运动, 否则是非运动。
"""

from __future__ import annotations

from typing import Any

#: 与 delivery_promise._REAL_MOTION_TYPES 对齐的取值(字面量, 不 import 上游常量,
#: 保持 oskill 纯算法边界零依赖; 上游如有增补这里由集成层显式覆盖)。
MOTION_CUT_TYPES = ("video", "animation", "avatar")

#: 落在 delivery_promise._SLIDE_GRAMMAR_TYPES 之外的静帧类型名, 上游同样按非运动计。
STILL_CUT_TYPE = "still_card"


def cuts_from_segments(
    *,
    segments: list[tuple[int, int]],
    deltas: list[float],
    motion_floor: float,
) -> list[dict[str, Any]]:
    """把稠密帧分段折算成切点描述符。

    Args:
        segments: ``[(start, end), ...]``, end 为开区间, 由 ``_detect_segments``
            按 ``delta >= motion_floor`` 切出。
        deltas: 相邻稠密帧的帧差, 长度 = 帧数 − 1。
        motion_floor: 判定"这一段内部有运动"的帧差下限。

    Returns:
        每段一个描述符。只有**证明得了**是静帧的段(段长 ≥ 2 且段内所有帧差都低于
        下限)才记为非运动; 单帧段是两次切换之间的空隙, 量不出它动没动, 不能
        当成"停住了" —— 量不出来的不当作缺陷, 与本仓其它门的诚实规则一致。
    """
    cuts: list[dict[str, Any]] = []
    for i, (a, b) in enumerate(segments):
        inner = deltas[a : max(b - 1, a)]
        provably_still = (b - a) >= 2 and not any(d >= motion_floor for d in inner)
        cuts.append(
            {
                "source": f"review://segment-{i:03d}",
                "type": STILL_CUT_TYPE if provably_still else "video",
                "frames": b - a,
                "max_delta": round(max(inner), 4) if inner else 0.0,
            }
        )
    return cuts


def motion_evidence(cuts: list[dict[str, Any]]) -> dict[str, Any]:
    """从切点描述符汇总运动证据(供报告里写人话)。"""
    motion = [c for c in cuts if str(c.get("type")) in MOTION_CUT_TYPES]
    still = [c for c in cuts if c not in motion]
    total = len(cuts)
    return {
        "cuts": total,
        "motion_cuts": len(motion),
        "still_cuts": len(still),
        "motion_ratio": round(len(motion) / total, 3) if total else 0.0,
        "still_ratio": round(len(still) / total, 3) if total else 0.0,
    }


__all__ = ["MOTION_CUT_TYPES", "STILL_CUT_TYPE", "cuts_from_segments", "motion_evidence"]
