"""Spike 级几何运镜测量:两帧间尺度变化比(zoom-out < 1 < zoom-in)。

方法:frame0 中央 50% 作模板,多尺度精确归一化互相关(NCC,积分图实现),
最佳尺度即 content scale ratio。无 cv2 依赖(numpy + scipy + PIL)。
"""

from __future__ import annotations

import numpy as np
from PIL import Image
from scipy.signal import correlate


def load_gray(path: str, width: int = 320) -> np.ndarray:
    img = Image.open(path).convert("L")
    ratio = width / img.width
    img = img.resize((width, max(1, int(img.height * ratio))), Image.BILINEAR)
    return np.asarray(img, dtype=np.float64)


def _box_sums(image: np.ndarray, th: int, tw: int) -> tuple[np.ndarray, np.ndarray]:
    """积分图求 valid 位置局部和/平方和(对齐精确,无滤波器原点歧义)。"""
    padded = np.pad(image, ((0, 1), (0, 1)), mode="constant")
    integral = padded.cumsum(axis=0).cumsum(axis=1)
    return integral[th:, tw:] - integral[:-th, tw:] - integral[th:, :-tw] + integral[:-th, :-tw]


def _ncc_map(image: np.ndarray, template: np.ndarray) -> np.ndarray:
    """精确归一化互相关图(积分图实现)。"""
    th, tw = template.shape
    n = float(th * tw)
    t = template - template.mean()
    denom_t = float(np.sqrt((t * t).sum()))
    if denom_t == 0:
        return np.zeros((image.shape[0] - th + 1, image.shape[1] - tw + 1))
    numer = correlate(image, t, mode="valid")  # ΣI·T − mean_T·ΣI
    sum_i = _box_sums(image, th, tw)
    sumsq_i = _box_sums(image * image, th, tw)
    denom_i = np.sqrt(np.maximum(sumsq_i - sum_i * sum_i / n, 0))
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(denom_i > 0, numer / (denom_i * denom_t), 0)
    return np.clip(out, -1.0, 1.0)


def estimate_scale_change(
    frame0: np.ndarray, frame1: np.ndarray,
    *, s_min: float = 0.55, s_max: float = 1.0, step: float = 0.025,
) -> tuple[float, float]:
    """返回 (best_scale, confidence=NCC 峰值)。zoom-out 表现为 best_scale < 1。"""
    h, w = frame0.shape
    tpl = frame0[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]
    th, tw = tpl.shape
    best_s, best_peak = 1.0, -1.0
    s = s_min
    while s <= s_max + 1e-9:
        nw, nh = max(8, int(tw * s)), max(8, int(th * s))
        resized = np.asarray(
            Image.fromarray(tpl.astype(np.uint8)).resize((nw, nh), Image.BILINEAR),
            dtype=np.float64,
        )
        if resized.shape[0] <= frame1.shape[0] and resized.shape[1] <= frame1.shape[1]:
            peak = float(_ncc_map(frame1, resized).max())
            if peak > best_peak:
                best_peak, best_s = peak, round(s, 4)
        s += step
    return best_s, best_peak
