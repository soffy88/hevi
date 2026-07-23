"""参数化场景深度渲染器（SPEC-008 B 轨）。

纯 numpy ray-AABB，无 3D 库 / 无 OpenGL 依赖。把场景建成一组轴对齐盒子（粗 3D），
虚拟相机按方位环绕投射，取最近交点出深度图，作 C 轨 ControlNet-depth 的控制图。
**同一套几何 + 不同相机方位 = 几何一致的多视图**——这正是 naive txt2img 缺的"几何
真值"（见签字工件 G1a-aqin-L2-finding / SPEC-008）。

方位约定（QNLR-EP0-SPEC-001 §5.4）：世界 Y 上；王座 N(+Z)、殿门 S(-Z)、柱阵
东(+X)/西(-X)。az 0 = 殿门(S)望 N(王座)；90=东；180=王座反打望 S；270=西。
确定性：无时钟无随机，同参数同输出（可测）。
"""

from __future__ import annotations

import math

import numpy as np

# 一个轴对齐盒子 = (lo_xyz, hi_xyz)
Box = tuple[np.ndarray, np.ndarray]


def qin_hall_d1_boxes() -> list[Box]:
    """EP0 D1 咸阳宫大殿粗几何（柱阵东西各 4 + 王座台 N + 殿门框 S + 王座后矮屏）。

    几何参数最终应从 SceneStage.space_map 结构化坐标派生（SPEC-008 §3 落点）；
    此函数是 EP0 的硬编码底本。
    """
    boxes: list[Box] = []
    boxes.append((np.array([-4.0, -0.2, -6.0]), np.array([4.0, 0.0, 6.0])))  # 地面
    # 柱阵：东(x=+2.2)/西(x=-2.2) 各 4，z = -3/-1/1/3，柱高 4.2
    boxes.extend(
        (np.array([x - 0.35, 0.0, z - 0.35]), np.array([x + 0.35, 4.2, z + 0.35]))
        for x in (2.2, -2.2)
        for z in (-3.0, -1.0, 1.0, 3.0)
    )
    boxes.append((np.array([-1.6, 0.0, 4.2]), np.array([1.6, 0.9, 5.4])))  # 王座高台
    boxes.append((np.array([-0.7, 0.9, 4.5]), np.array([0.7, 2.2, 5.2])))  # 王座本体
    # 殿门框 S：东西门柱 + 上楣，中央开口可望穿
    boxes.append((np.array([-3.2, 0.0, -5.6]), np.array([-2.0, 4.4, -5.2])))
    boxes.append((np.array([2.0, 0.0, -5.6]), np.array([3.2, 4.4, -5.2])))
    boxes.append((np.array([-3.2, 3.4, -5.6]), np.array([3.2, 4.4, -5.2])))
    boxes.append((np.array([-2.6, 0.0, 5.6]), np.array([2.6, 2.6, 5.9])))  # 王座后矮屏
    return boxes


def camera_pose(
    azimuth_deg: float,
    *,
    radius: float = 9.0,
    height: float = 2.6,
    center: tuple[float, float, float] = (0.0, 1.5, 0.0),
):
    """相机位姿：绕 center 按方位环绕，恒看向 center。返回 (cam, fwd, right, up)。"""
    th = math.radians(azimuth_deg)
    c = np.array(center, dtype=float)
    cam = c + radius * np.array([math.sin(th), 0.0, -math.cos(th)]) + np.array([0.0, height, 0.0])
    fwd = c - cam
    fwd = fwd / np.linalg.norm(fwd)
    right = np.cross(fwd, np.array([0.0, 1.0, 0.0]))
    right = right / np.linalg.norm(right)
    up = np.cross(right, fwd)
    return cam, fwd, right, up


def render_depth(
    boxes: list[Box],
    azimuth_deg: float,
    *,
    width: int = 1024,
    height: int = 576,
    fov_deg: float = 55.0,
    radius: float = 9.0,
    cam_height: float = 2.6,
    center: tuple[float, float, float] = (0.0, 1.5, 0.0),
) -> np.ndarray:
    """渲一张深度图（uint8, HxW）。近=亮、远/背景=黑（ControlNet-depth 惯例）。"""
    cam, fwd, right, up = camera_pose(azimuth_deg, radius=radius, height=cam_height, center=center)
    aspect = width / height
    t = math.tan(math.radians(fov_deg) / 2)
    js, is_ = np.meshgrid(np.arange(width), np.arange(height))
    ndc_x = (2 * (js + 0.5) / width - 1) * aspect * t
    ndc_y = (1 - 2 * (is_ + 0.5) / height) * t
    dirs = (
        fwd[None, None, :]
        + ndc_x[..., None] * right[None, None, :]
        + ndc_y[..., None] * up[None, None, :]
    )
    dirs = dirs / np.linalg.norm(dirs, axis=2, keepdims=True)
    rays = dirs.reshape(-1, 3)
    origin = cam[None, :]
    # ray-AABB slab 法；对平行轴（分量≈0）用大数避免除零
    safe = np.where(np.abs(rays) < 1e-9, 1e-9, rays)
    inv = 1.0 / safe
    best = np.full(rays.shape[0], np.inf)
    for lo, hi in boxes:
        t1 = (lo[None, :] - origin) * inv
        t2 = (hi[None, :] - origin) * inv
        tmin = np.max(np.minimum(t1, t2), axis=1)
        tmax = np.min(np.maximum(t1, t2), axis=1)
        thit = np.where(tmin > 1e-4, tmin, tmax)
        valid = (tmax >= np.maximum(tmin, 0.0)) & (tmin <= tmax) & (thit > 1e-4)
        best = np.where(valid & (thit < best), thit, best)
    depth = best.reshape(height, width)
    hit = np.isfinite(depth)
    img = np.zeros((height, width), np.uint8)
    if hit.any():
        dmin = depth[hit].min()
        dmax = depth[hit].max()
        norm = np.clip((depth - dmin) / max(dmax - dmin, 1e-6), 0.0, 1.0)
        img[hit] = ((1.0 - norm[hit]) * 255).astype(np.uint8)
    return img


def render_azimuth_set(boxes: list[Box], azimuths: list[float], **kw) -> dict[float, np.ndarray]:
    """一套几何出多方位深度图（几何一致）。返回 {azimuth: depth_uint8}。"""
    return {az: render_depth(boxes, az, **kw) for az in azimuths}
