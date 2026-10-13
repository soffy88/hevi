"""渲染器单测 —— 时间线 / 帧状态 / 调度几何 / 包围盒 / 姿势变化。"""

from __future__ import annotations

import numpy as np
import pytest

from hevi.layer4_legacy.stickdir import pose, proposal, render, whitelist

COPY = (
    "很多人以为效率来自更努力。其实真正的效率来自更少的选择。"
    "当选项变多，大脑每一步都要重新评估，决策成本会吃掉你全部的时间。"
    "顶尖的人不是做得更多，而是把不重要的事情直接删掉。"
    "删掉一件事，胜过完成三件事。所以别再问怎么才能做得更快，先问这件事到底该不该做。"
)


def _plan(style="2A", aspect="16:9", dur=30):
    p = proposal.build_proposal(copy=COPY, aspect=aspect, style=style, duration=dur)
    return render.build_plan(p.data, fps=30)


def test_plan_frame_count():
    plan = _plan(dur=30)
    assert plan.n_frames == 30 * 30


def test_frame_state_covers_all_segments():
    plan = _plan(dur=30)
    seen = set()
    for i in range(plan.n_frames):
        fs = render.frame_state(plan, i / plan.fps)
        seen.add(fs.seg)
        assert fs.action in whitelist.ACTION
        assert whitelist.is_valid("prop", fs.prop)
        assert whitelist.is_valid("camera", fs.camera)
    assert seen == {0, 1, 2}


def test_staging_geometry_within_frame():
    for aspect in ("9:16", "16:9"):
        plan = _plan(aspect=aspect)
        for staging in whitelist.staging_for(aspect):
            ax, ay, sf = render._staging_geom(plan, staging)
            assert 0 < ax < 1 and 0 < ay <= 1 and 0 < sf < 1


def test_character_bbox_inside_frame():
    """人物始终完整在画内(骨骼包围盒留边距)。"""
    for aspect, style in (("16:9", "2A"), ("9:16", "1B")):
        plan = _plan(style=style, aspect=aspect)
        w, h = render.SIZE[aspect]
        for i in range(0, plan.n_frames, 15):
            fs = render.frame_state(plan, i / plan.fps)
            ax, ay, sf = render._staging_geom(plan, fs.staging)
            zoom, dxf, dyf = render._camera_state(fs.camera, 0.5, i / plan.fps)
            scale = h * sf * zoom
            ox, oy = w * ax + w * dxf, h * ay + h * dyf
            joints = pose.solve(pose.angles_at(fs.action, fs.phase))
            xs = [ox + j[0] * scale for j in joints.values()]
            ys = [oy - j[1] * scale for j in joints.values()]
            margin = min(w, h) * 0.02
            assert min(xs) >= margin, (style, aspect, fs.action, min(xs))
            assert max(xs) <= w - margin
            assert min(ys) >= margin
            assert max(ys) <= h - margin


def test_pose_changes_every_3s():
    """相邻 3s 窗口内姿势/轮廓差异超过阈值。"""
    from scripts.stickdir_verify import _largest_component, _silhouette, _fg_mask

    plan = _plan(style="1B", aspect="9:16")
    fr = render.FrameRenderer(plan)
    sigs = []
    for i in range(0, plan.n_frames, 30):  # 每 1s
        img = np.array(fr.render(render.frame_state(plan, i / plan.fps)))
        mask = _largest_component(_fg_mask(img, "1B", (255, 255, 255)), exclude_bottom_frac=0.18)
        sigs.append(_silhouette(mask))
    for i in range(len(sigs) - 3):
        d = float(np.abs(sigs[i] - sigs[i + 3]).sum() / 2)
        assert d > 0.02, f"frames {i}..{i+3} look identical (diff={d})"


def test_actions_cover_whitelist():
    whitelist.assert_renderable(whitelist.ACTION)
    assert set(pose.POSES) == set(whitelist.ACTION)
