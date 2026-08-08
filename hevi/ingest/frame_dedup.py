"""帧去重 —— 16×16 灰度缩略图 + 均差阈值的近重复帧剔除(3O 内化 Phase A)。

来源: bradautomates/claude-video 的 dedup 设计。屏幕录制/长静止画面会产出
大量近重复帧,每帧都是一张计费图片。去重发生在预算封顶**之前**,把预算花在
"真正不同的帧"上。

实现细节(与来源对齐):
- 一次 ffmpeg 调用把每帧缩到 16×16 灰度;这里是纯算法部分(缩略图由调用方
  提供),**无任何图像库依赖** —— 均值差只吃 bytes。
- 与**上一个被保留的帧**比较(而非上一帧):慢渐变也能被抓住。
- 阈值故意低(2.0/255 均亮差),一行代码 diff、滚动一行、两个不同颜色的扁平
  slide 都不该被误杀。

3O 归属(待上游): `oprim.frame_dedup`。纯算法,可平移零改动。
"""

from __future__ import annotations

from collections.abc import Callable

#: 每像素均亮差阈值(0–255 尺度)。<= 该值判为近重复。
DEDUP_THRESHOLD = 2.0


def frame_delta(thumb_a: bytes, thumb_b: bytes, *, pixel_count: int | None = None) -> float:
    """两个 16×16 灰度缩略图的平均每像素亮差。

    Args:
        thumb_a / thumb_b: 等长灰度缩略图字节(每字节一像素)。
        pixel_count: 像素数;None 时取 len(thumb_a)。长度不匹配视为最大差异。

    Returns:
        0.0–255.0 的均差。
    """
    if len(thumb_a) != len(thumb_b):
        return 255.0
    n = pixel_count if pixel_count is not None else len(thumb_a)
    if n <= 0:
        return 0.0
    total = sum(abs(a - b) for a, b in zip(thumb_a, thumb_b, strict=False))
    return total / n


def dedupe_frames(
    thumbs: list[bytes],
    *,
    threshold: float = DEDUP_THRESHOLD,
    thumb_fn: Callable[[bytes, bytes], float] | None = None,
) -> tuple[list[int], int]:
    """贪心去重:返回 (保留的候选下标, 丢弃数)。

    Args:
        thumbs: 与候选帧一一对应的 16×16 灰度缩略图(bytes)。
        threshold: 均差阈值(默认 2.0)。
        thumb_fn: 调试用 delta 注入点;None 时用 frame_delta。

    Returns:
        (survivors, dropped_count): survivors 是保留下来的**原始下标**列表。
    """
    if not thumbs:
        return [], 0
    delta = thumb_fn if thumb_fn is not None else frame_delta
    survivors: list[int] = []
    last_kept: bytes | None = None
    dropped = 0
    for i, thumb in enumerate(thumbs):
        if last_kept is None or delta(thumb, last_kept) > threshold:
            survivors.append(i)
            last_kept = thumb
        else:
            dropped += 1
    return survivors, dropped
