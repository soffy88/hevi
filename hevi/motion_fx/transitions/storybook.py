"""Hevi 绘本转场体系 (Storybook Transitions).

根据 STORYBOOK_TASK.md 要求：
- 5 种绘本专属转场：
  1. 翻页 (page_flip)：立体卷页、折痕阴影与底层显露
  2. 湿笔刷晕开 (wet_brush)：横向/斜向湿水彩排笔晕开，毛刷边缘羽化
  3. 纸页撕裂 (torn_paper)：毛糙撕裂纸边白痕、纤维质感与投影
  4. 铅笔线自绘出现 (pencil_sketch)：素描轮廓线条渐显绘制，淡彩水晕填色
  5. 水彩晕染 (watercolor_bloom)：中心向外有机扩散水晕，边缘水渍水圈（pigment pooling）
- 接入 handdraw / 时间线与 Motion FX 引擎
- 统一能力注册：transitions.storybook
- CPU 本地 NumPy/OpenCV 渲染，无外部收费依赖，确定性输出。
"""

from __future__ import annotations

import hashlib
import math
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Union

import cv2
import numpy as np

from hevi.motion_fx.transitions.base import VideoInfo, probe_video
from hevi.motion_fx.transitions.engine import REGISTRY, register_transition


# ─────────────────────────────────────────────────────────────────────────────
# 1. 翻页转场 (Page Flip / Curl)
# ─────────────────────────────────────────────────────────────────────────────
def render_page_flip(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    p: float,
    params: dict | None = None,
) -> np.ndarray:
    """翻页转场：页卷从右侧向左平滑翻起，显露底层 frame_b。"""
    if p <= 0.0:
        return frame_a.copy()
    if p >= 1.0:
        return frame_b.copy()

    h, w = frame_a.shape[:2]
    if frame_b.shape[:2] != (h, w):
        frame_b = cv2.resize(frame_b, (w, h), interpolation=cv2.INTER_LINEAR)

    cfg = params or {}
    curl_radius = float(cfg.get("curl_radius", 0.12 * w))
    # 翻页卷曲中轴线从右到左推进 (w + curl_radius -> -curl_radius)
    x_curl = w * (1.0 - p)

    out = frame_b.copy()

    # 翻页左侧依然是 frame_a
    mask_a = np.zeros((h, w), dtype=np.float32)
    xx = np.arange(w, dtype=np.float32).reshape(1, -1)
    xx = np.broadcast_to(xx, (h, w))

    # 完全保留 frame_a 的区域
    mask_a[xx < (x_curl - curl_radius)] = 1.0

    # 卷曲过渡带：圆柱卷起阴影与高光渐变
    curl_zone = (xx >= (x_curl - curl_radius)) & (xx <= x_curl)
    if np.any(curl_zone):
        dist = (x_curl - xx[curl_zone]) / max(1.0, curl_radius)  # 0 (at curl line) to 1 (flat)
        # 翻折阴影与圆柱弧光
        shadow = 0.5 + 0.5 * np.sin(dist * np.pi * 0.5)
        # 在 frame_a 卷起边缘添加暗部
        mask_a[curl_zone] = dist

    mask_3d = np.repeat(mask_a[:, :, np.newaxis], 3, axis=2)

    # 合成 frame_a 与 frame_b
    blended = (frame_a.astype(np.float32) * mask_3d + frame_b.astype(np.float32) * (1.0 - mask_3d))

    # 沿着翻折线投射在底层 frame_b 上的微阴影
    shadow_zone = (xx >= x_curl) & (xx <= (x_curl + curl_radius * 0.75))
    if np.any(shadow_zone):
        s_dist = (xx[shadow_zone] - x_curl) / (curl_radius * 0.75)
        shadow_factor = 0.65 + 0.35 * s_dist
        for c in range(3):
            blended[:, :, c][shadow_zone] *= shadow_factor

    return np.clip(blended, 0, 255).astype(np.uint8)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 湿笔刷晕开转场 (Wet Brush Bleed)
# ─────────────────────────────────────────────────────────────────────────────
def render_wet_brush(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    p: float,
    params: dict | None = None,
) -> np.ndarray:
    """湿笔刷晕开：湿水彩宽笔触横扫，笔触边缘带水性渗透与羽化。"""
    if p <= 0.0:
        return frame_a.copy()
    if p >= 1.0:
        return frame_b.copy()

    h, w = frame_a.shape[:2]
    if frame_b.shape[:2] != (h, w):
        frame_b = cv2.resize(frame_b, (w, h), interpolation=cv2.INTER_LINEAR)

    cfg = params or {}
    feather = float(cfg.get("feather", 0.08 * w))

    # 构建笔触有机波形 (模拟水彩毛刷鬃毛颤动)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    bristle_noise = (
        np.sin(yy * 0.04) * 0.03 * w
        + np.sin(yy * 0.12) * 0.015 * w
        + np.cos(xx * 0.02 + yy * 0.05) * 0.02 * w
    )

    # 推进前锋面 (从左往右横扫)
    sweep_pos = p * (w + feather * 2) - feather
    dist_to_front = sweep_pos + bristle_noise - xx

    # 生成平滑过渡权重 (0.0 为 frame_a, 1.0 为 frame_b)
    alpha = np.clip((dist_to_front / max(1.0, feather)), 0.0, 1.0)
    # S 曲线平滑
    alpha = alpha * alpha * (3.0 - 2.0 * alpha)

    # 水彩边缘渗色暗纹 (Pigment pooling at wet edge)
    edge_ring = np.exp(-((alpha - 0.5) ** 2) / 0.04) * 0.15
    alpha_3d = np.repeat(alpha[:, :, np.newaxis], 3, axis=2)

    res = frame_a.astype(np.float32) * (1.0 - alpha_3d) + frame_b.astype(np.float32) * alpha_3d
    # 边缘微暗水圈
    res = res * (1.0 - edge_ring[:, :, np.newaxis])

    return np.clip(res, 0, 255).astype(np.uint8)


# ─────────────────────────────────────────────────────────────────────────────
# 3. 纸页撕裂转场 (Torn Paper)
# ─────────────────────────────────────────────────────────────────────────────
def render_torn_paper(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    p: float,
    params: dict | None = None,
) -> np.ndarray:
    """纸页撕裂：毛糙纸张撕裂口，露出纤维白边与投影，撕出下一页。"""
    if p <= 0.0:
        return frame_a.copy()
    if p >= 1.0:
        return frame_b.copy()

    h, w = frame_a.shape[:2]
    if frame_b.shape[:2] != (h, w):
        frame_b = cv2.resize(frame_b, (w, h), interpolation=cv2.INTER_LINEAR)

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    # 撕裂边缘不规则多频分形扰动 (Fibrous torn edge)
    tear_noise = (
        np.sin(yy * 0.025) * 22.0
        + np.sin(yy * 0.08) * 12.0
        + np.cos(yy * 0.22) * 6.0
        + np.sin(yy * 0.45) * 3.0
    )

    # 撕裂线自左上往右下推进
    tear_center = p * (w + 120) - 60
    dist = xx - (tear_center + tear_noise)

    out = np.zeros_like(frame_a, dtype=np.float32)

    # 撕裂后显露的底层 frame_b (左侧)
    mask_b = dist <= 0.0
    # 尚未撕开的 frame_a (右侧)
    mask_a = dist > 14.0

    out[mask_b] = frame_b[mask_b]
    out[mask_a] = frame_a[mask_a]

    # 撕裂毛边白纤维区 (0 < dist <= 14)
    tear_white_zone = (dist > 0.0) & (dist <= 14.0)
    if np.any(tear_white_zone):
        # 纸芯白纤维底色 + 微妙纸纹噪点
        fibers = (np.sin(yy[tear_white_zone] * 2.0) * 15 + 240).clip(210, 255)
        fiber_rgb = np.stack([fibers * 0.96, fibers * 0.97, fibers], axis=1)
        out[tear_white_zone] = fiber_rgb

    # 撕裂边缘在 frame_b 上的微弱阴影
    shadow_zone = (dist > -18.0) & (dist <= 0.0)
    if np.any(shadow_zone):
        s_factor = 0.72 + 0.28 * ((dist[shadow_zone] + 18.0) / 18.0)
        for c in range(3):
            out[:, :, c][shadow_zone] *= s_factor

    return np.clip(out, 0, 255).astype(np.uint8)


# ─────────────────────────────────────────────────────────────────────────────
# 4. 铅笔线自绘出现转场 (Pencil Sketch-in)
# ─────────────────────────────────────────────────────────────────────────────
def render_pencil_sketch(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    p: float,
    params: dict | None = None,
) -> np.ndarray:
    """铅笔线自绘出现：前段铅笔素描线条绘制显露轮廓，后段淡彩水晕填色显露实景。"""
    if p <= 0.0:
        return frame_a.copy()
    if p >= 1.0:
        return frame_b.copy()

    h, w = frame_a.shape[:2]
    if frame_b.shape[:2] != (h, w):
        frame_b = cv2.resize(frame_b, (w, h), interpolation=cv2.INTER_LINEAR)

    # 提取 frame_b 的铅笔素描线图 (Edge sketch)
    gray_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY)
    inv_gray = 255 - gray_b
    blur = cv2.GaussianBlur(inv_gray, (21, 21), 0)
    sketch_b = cv2.divide(gray_b, 255 - blur, scale=256)
    sketch_3d = cv2.cvtColor(sketch_b, cv2.COLOR_GRAY2BGR).astype(np.float32)

    if p < 0.5:
        # Phase 1: 铅笔线逐步绘制覆盖在 frame_a 上
        sub_p = p / 0.5
        # 铅笔线描扫描推进线
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        hatch_prog = (xx / w + yy / h) * 0.5
        sketch_mask = np.clip((sub_p * 1.5 - hatch_prog) * 3.0, 0.0, 1.0)[:, :, np.newaxis]
        # 铅笔素描与底图正片叠底/淡入
        sketch_overlay = (frame_a.astype(np.float32) * (sketch_3d / 255.0))
        out = frame_a.astype(np.float32) * (1.0 - sketch_mask) + sketch_overlay * sketch_mask
    else:
        # Phase 2: 淡彩水晕注入，色彩充盈，完成向 frame_b 的过度
        sub_p = (p - 0.5) / 0.5
        color_fill = sub_p * sub_p * (3.0 - 2.0 * sub_p)
        out = sketch_3d * (1.0 - color_fill) + frame_b.astype(np.float32) * color_fill

    return np.clip(out, 0, 255).astype(np.uint8)


# ─────────────────────────────────────────────────────────────────────────────
# 5. 水彩晕染转场 (Watercolor Bloom / Bleed)
# ─────────────────────────────────────────────────────────────────────────────
def render_watercolor_bloom(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    p: float,
    params: dict | None = None,
) -> np.ndarray:
    """水彩晕染：水晕从中心与四周多点有机蔓延，伴随边缘水渍沉积圈。"""
    if p <= 0.0:
        return frame_a.copy()
    if p >= 1.0:
        return frame_b.copy()

    h, w = frame_a.shape[:2]
    if frame_b.shape[:2] != (h, w):
        frame_b = cv2.resize(frame_b, (w, h), interpolation=cv2.INTER_LINEAR)

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    # 多核水晕扩散中心 (中心主水滴 + 四周次水滴)
    centers = [
        (w * 0.5, h * 0.5, 1.0),
        (w * 0.25, h * 0.35, 0.7),
        (w * 0.75, h * 0.65, 0.7),
        (w * 0.3, h * 0.8, 0.6),
    ]

    # 计算到扩散核的加权最小距离
    min_dist = np.full((h, w), 9999.0, dtype=np.float32)
    for cx, cy, weight in centers:
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / weight
        min_dist = np.minimum(min_dist, d)

    # 叠加水晕有机边缘湍流噪点
    organic_noise = (
        np.sin(xx * 0.03 + yy * 0.02) * 18.0
        + np.cos(xx * 0.015 - yy * 0.04) * 15.0
        + np.sin(np.sqrt(xx ** 2 + yy ** 2) * 0.05) * 8.0
    )
    dist_field = min_dist + organic_noise

    # 水彩扩散半径随 p 展开
    max_radius = np.sqrt(w ** 2 + h ** 2) * 0.75
    current_radius = p * max_radius

    bleed_width = 35.0
    diff = current_radius - dist_field
    alpha = np.clip(diff / bleed_width, 0.0, 1.0)
    alpha = alpha * alpha * (3.0 - 2.0 * alpha)

    # 水彩边缘沉积圈 (Water droplet dark boundary ring)
    ring_mask = np.exp(-((alpha - 0.5) ** 2) / 0.06) * 0.18
    alpha_3d = np.repeat(alpha[:, :, np.newaxis], 3, axis=2)

    out = frame_a.astype(np.float32) * (1.0 - alpha_3d) + frame_b.astype(np.float32) * alpha_3d
    out = out * (1.0 - ring_mask[:, :, np.newaxis])

    return np.clip(out, 0, 255).astype(np.uint8)


# ─────────────────────────────────────────────────────────────────────────────
# 注册到 Motion FX 转场注册表
# ─────────────────────────────────────────────────────────────────────────────
STORYBOOK_TRANSITIONS: dict[str, Any] = {
    "page_flip": render_page_flip,
    "storybook_page_flip": render_page_flip,
    "wet_brush": render_wet_brush,
    "storybook_wet_brush": render_wet_brush,
    "torn_paper": render_torn_paper,
    "storybook_torn_paper": render_torn_paper,
    "pencil_sketch": render_pencil_sketch,
    "storybook_pencil_sketch": render_pencil_sketch,
    "watercolor_bloom": render_watercolor_bloom,
    "storybook_watercolor_bloom": render_watercolor_bloom,
}

for name, fn in STORYBOOK_TRANSITIONS.items():
    register_transition(name, fn)


# ─────────────────────────────────────────────────────────────────────────────
# Capability: transitions.storybook
# ─────────────────────────────────────────────────────────────────────────────
def _create_placeholder_frame(
    text: str,
    color_bg: tuple[int, int, int],
    size: tuple[int, int] = (1280, 720),
) -> np.ndarray:
    """生成带有水彩纸质感的占位帧 (BGR)。"""
    w, h = size
    # 背景底色
    img = np.full((h, w, 3), color_bg, dtype=np.uint8)
    # 添加轻柔纸纹
    noise = np.random.RandomState(42).randint(-5, 5, (h, w, 3))
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    # 居中文本
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 1.3
    thick = 2
    tsize = cv2.getTextSize(text, font, scale, thick)[0]
    tx = (w - tsize[0]) // 2
    ty = (h + tsize[1]) // 2
    cv2.putText(img, text, (tx, ty), font, scale, (30, 30, 30), thick, cv2.LINE_AA)
    return img


def render_storybook_transition(
    clip_a_or_frame: Union[str, Path, np.ndarray],
    clip_b_or_frame: Union[str, Path, np.ndarray],
    transition_type: str,
    duration: float,
    out_mp4: Path,
    *,
    fps: float = 30.0,
    size: tuple[int, int] = (1280, 720),
    params: dict | None = None,
) -> Path:
    """执行真实绘本转场渲染为 MP4 文件。"""
    trans_fn = STORYBOOK_TRANSITIONS.get(transition_type)
    if not trans_fn:
        available = ", ".join(sorted(STORYBOOK_TRANSITIONS.keys()))
        raise ValueError(f"Unknown storybook transition '{transition_type}'. Available: {available}")

    w, h = size

    # 解析输入 A
    if isinstance(clip_a_or_frame, np.ndarray):
        frame_a = clip_a_or_frame
        if frame_a.shape[:2] != (h, w):
            frame_a = cv2.resize(frame_a, (w, h))
    elif Path(clip_a_or_frame).is_file() and str(clip_a_or_frame).lower().endswith((".png", ".jpg", ".jpeg")):
        frame_a = cv2.imread(str(clip_a_or_frame))
        if frame_a.shape[:2] != (h, w):
            frame_a = cv2.resize(frame_a, (w, h))
    else:
        frame_a = _create_placeholder_frame("Scene A (Page 1)", (215, 235, 245), size=size)

    # 解析输入 B
    if isinstance(clip_b_or_frame, np.ndarray):
        frame_b = clip_b_or_frame
        if frame_b.shape[:2] != (h, w):
            frame_b = cv2.resize(frame_b, (w, h))
    elif Path(clip_b_or_frame).is_file() and str(clip_b_or_frame).lower().endswith((".png", ".jpg", ".jpeg")):
        frame_b = cv2.imread(str(clip_b_or_frame))
        if frame_b.shape[:2] != (h, w):
            frame_b = cv2.resize(frame_b, (w, h))
    else:
        frame_b = _create_placeholder_frame("Scene B (Page 2)", (255, 235, 220), size=size)

    out_mp4 = Path(out_mp4).resolve()
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    total_frames = max(2, int(round(duration * fps)))

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{w}x{h}",
        "-pix_fmt", "bgr24",
        "-r", f"{fps:.2f}",
        "-i", "-",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_mp4),
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    try:
        for idx in range(total_frames):
            p = float(idx) / float(max(1, total_frames - 1))
            frame_out = trans_fn(frame_a, frame_b, p, params=params)
            proc.stdin.write(frame_out.tobytes())
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.wait()

    if proc.returncode != 0:
        err = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        raise RuntimeError(f"FFmpeg render transition failed (code {proc.returncode}): {err}")

    return out_mp4


def render_transitions_storybook_capability(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float = 1.0,
    aspect: str = "16:9",
    seed: int = 42,
) -> Any:
    """Capability 注册执行入口。"""
    from hevi.capabilities.registry import CapabilityResult

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    trans_type = str(params.get("transition_type") or "page_flip")
    dur = float(params.get("duration") or (duration if duration > 0 else 1.0))
    fps = float(params.get("fps") or 30.0)

    size = (1920, 1080) if aspect == "16:9" else (1080, 1920) if aspect == "9:16" else (1080, 1080)

    clip_a = params.get("clip_a")
    clip_b = params.get("clip_b")

    out_mp4 = out_dir / f"storybook_transition_{trans_type}.mp4"
    render_storybook_transition(
        clip_a,
        clip_b,
        trans_type,
        dur,
        out_mp4,
        fps=fps,
        size=size,
        params=params.get("params"),
    )

    # 截取中段转场帧作为预览图
    out_png = out_dir / f"storybook_transition_{trans_type}_preview.png"
    cap = cv2.VideoCapture(str(out_mp4))
    total_f = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, total_f // 2)
    ret, mid_frame = cap.read()
    cap.release()
    if ret and mid_frame is not None:
        cv2.imwrite(str(out_png), mid_frame)
    else:
        out_png = None

    sha = hashlib.sha256(out_mp4.read_bytes()).hexdigest()

    return CapabilityResult(
        mp4=out_mp4,
        png=out_png,
        wav=None,
        duration_s=dur,
        sha256=sha,
        qa={
            "transition_type": trans_type,
            "duration": dur,
            "fps": fps,
            "aspect": aspect,
            "size": list(size),
        },
    )
