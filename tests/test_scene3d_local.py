"""scene3d_local（SPEC-008 B 轨）单测——纯 numpy，零 GPU/网络，零成本。

核心断言：同一几何多方位深度图**几何一致**（东西镜像对称），这正是 naive
txt2img 缺、G1a 失败的那一条现由 3D 几何真值补上。
"""

from __future__ import annotations

import numpy as np

from hevi.image.scene3d_local import (
    camera_pose,
    qin_hall_d1_boxes,
    render_azimuth_set,
    render_depth,
)


def test_depth_shape_dtype_and_hits() -> None:
    boxes = qin_hall_d1_boxes()
    d = render_depth(boxes, 0.0, width=256, height=144)
    assert d.shape == (144, 256)
    assert d.dtype == np.uint8
    assert (d > 0).mean() > 0.3  # master 视图应有可观命中


def test_deterministic() -> None:
    boxes = qin_hall_d1_boxes()
    a = render_depth(boxes, 45.0, width=256, height=144)
    b = render_depth(boxes, 45.0, width=256, height=144)
    assert np.array_equal(a, b)  # 无时钟无随机


def test_east_west_mirror_symmetry() -> None:
    """AZ90(东望西) 与 AZ270(西望东) 应为水平镜像——几何一致性的硬证据。"""
    boxes = qin_hall_d1_boxes()
    e = render_depth(boxes, 90.0, width=256, height=144)
    w = render_depth(boxes, 270.0, width=256, height=144)
    diff = np.abs(e.astype(int) - np.fliplr(w).astype(int))
    assert diff.mean() < 3.0  # 镜像后逐像素差极小（仅光栅化边缘残差）


def test_corner_pairs_mirror() -> None:
    """AZ45 与 AZ315、AZ135 与 AZ225 同为东西镜像对。"""
    boxes = qin_hall_d1_boxes()
    for a_az, b_az in [(45.0, 315.0), (135.0, 225.0)]:
        a = render_depth(boxes, a_az, width=256, height=144)
        b = render_depth(boxes, b_az, width=256, height=144)
        assert np.abs(a.astype(int) - np.fliplr(b).astype(int)).mean() < 3.0


def test_axial_views_see_into_hall() -> None:
    """门框中央开口 → 轴向 0/180 视图能望穿进殿（非被端墙全挡）。"""
    boxes = qin_hall_d1_boxes()
    for az in (0.0, 180.0):
        d = render_depth(boxes, az, width=256, height=144)
        assert (d == 0).mean() > 0.05  # 有望穿的远/开口暗区
        assert (d > 0).mean() > 0.3  # 又确有几何


def test_render_azimuth_set() -> None:
    boxes = qin_hall_d1_boxes()
    s = render_azimuth_set(boxes, [0.0, 90.0, 180.0, 270.0], width=128, height=72)
    assert set(s.keys()) == {0.0, 90.0, 180.0, 270.0}
    assert all(v.shape == (72, 128) for v in s.values())


def test_camera_pose_orthonormal() -> None:
    _cam, fwd, right, up = camera_pose(90.0)
    for v in (fwd, right, up):
        assert abs(np.linalg.norm(v) - 1.0) < 1e-6
    assert abs(np.dot(fwd, right)) < 1e-6
    assert abs(np.dot(right, up)) < 1e-6
