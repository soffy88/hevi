"""动画运行时选择 —— Remotion / HyperFrames / Manim / ffmpeg。

配方 `render_runtime` 锁定优先;没锁才按意图挑。禁止静默换栈。
"""

from __future__ import annotations

from typing import Any

RUNTIMES = ("remotion", "hyperframes", "manim", "ffmpeg")

_HYPER_HINTS = (
    "kinetic",
    "typography",
    "片头",
    "标题卡",
    "promo",
    "motion graphic",
    "动效",
    "music-to-video",
    "lower-third",
    "花字",
)
_MANIM_HINTS = ("manim", "公式", "equation", "3b1b", "代码即画面", "证明")
_FFMPEG_HINTS = ("recut", "拆条", "concat", "译制", "只重导出")


def select_runtime(
    *,
    locked: str | None = None,
    intent: str = "",
    line_id: str = "",
) -> dict[str, Any]:
    """返回 {runtime, locked, reason}。"""
    if locked and locked in RUNTIMES:
        return {"runtime": locked, "locked": True, "reason": "recipe.lock"}
    blob = f"{intent} {line_id}".lower()
    if any(h in blob for h in _MANIM_HINTS):
        return {"runtime": "manim", "locked": False, "reason": "intent.manim"}
    if any(h in blob for h in _HYPER_HINTS):
        return {"runtime": "hyperframes", "locked": False, "reason": "intent.hyperframes"}
    if any(h in blob for h in _FFMPEG_HINTS):
        return {"runtime": "ffmpeg", "locked": False, "reason": "intent.ffmpeg"}
    return {"runtime": "remotion", "locked": False, "reason": "default.remotion"}
