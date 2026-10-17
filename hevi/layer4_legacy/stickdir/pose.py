"""参数化火柴人姿势库 —— 覆盖白名单全部动作, 节拍间平滑插值。

表示法
------
一个"姿势"是一组关节角度(度), 经 2D 正向运动学解算成关节坐标。坐标与
``hevi.studio.cmumocap`` 的 2D 投影同构: 身高归一化到约 1.0, 地面 y=0,
髋部水平居中于 x=0。这样 mocap 片段与参数化姿势可以直接混用。

角度约定
--------
* 关节角以"竖直向下"为 0°, 向角色正面(+x, 画面右侧)为正。
* 躯干 ``lean`` 以竖直向上为 0°, 向 +x 倾斜为正。
* 每个 ``POSE_FUNCS`` 里的函数接收相位 ``p ∈ [0,1)``(循环)或
  ``p ∈ [0,1]``(一次性动作), 返回角度字典。
"""

from __future__ import annotations

import math
from typing import Callable

# ---------------------------------------------------------------------------
# 骨架比例(归一化身高约 1.0)
# ---------------------------------------------------------------------------

THIGH = 0.25
SHIN = 0.25
SPINE = 0.20
NECK = 0.07
HEAD = 0.12
UPPER_ARM = 0.16
FOREARM = 0.15
SHOULDER_DX = 0.09
HIP_DX = 0.06

#: 站立时髋高(= THIGH + SHIN)
HIP_Y = THIGH + SHIN

#: 关节顺序(与 svg_character.BONES 一致)
JOINTS: tuple[str, ...] = (
    "hips",
    "chest",
    "neck",
    "head",
    "shR",
    "elR",
    "haR",
    "shL",
    "elL",
    "haL",
    "hipR",
    "knR",
    "ftR",
    "hipL",
    "knL",
    "ftL",
)

#: 骨骼连线(渲染用)
BONES: tuple[tuple[str, str], ...] = (
    ("hips", "chest"),
    ("chest", "neck"),
    ("neck", "head"),
    ("chest", "shR"),
    ("shR", "elR"),
    ("elR", "haR"),
    ("chest", "shL"),
    ("shL", "elL"),
    ("elL", "haL"),
    ("hips", "hipR"),
    ("hipR", "knR"),
    ("knR", "ftR"),
    ("hips", "hipL"),
    ("hipL", "knL"),
    ("knL", "ftL"),
)

#: 角度字典的键(用于插值)
ANGLE_KEYS: tuple[str, ...] = (
    "lean",
    "head",
    "armR_sh",
    "armR_el",
    "armL_sh",
    "armL_el",
    "legR_hip",
    "legR_kn",
    "legL_hip",
    "legL_kn",
    "rootX",
    "rootY",
)

PoseAngles = dict[str, float]


def _seg(origin: tuple[float, float], length: float, angle_deg: float) -> tuple[float, float]:
    a = math.radians(angle_deg)
    return (origin[0] + length * math.sin(a), origin[1] - length * math.cos(a))


def solve(angles: PoseAngles) -> dict[str, tuple[float, float]]:
    """角度字典 → 关节坐标(归一化)。"""
    lean = angles.get("lean", 0.0)
    root_x = angles.get("rootX", 0.0)
    root_y = angles.get("rootY", 0.0)
    hips = (root_x, HIP_Y + root_y)
    la = math.radians(lean)
    spine_dir = (math.sin(la), math.cos(la))
    perp = (math.cos(la), -math.sin(la))

    chest = (hips[0] + spine_dir[0] * SPINE, hips[1] + spine_dir[1] * SPINE)
    neck = (chest[0] + spine_dir[0] * NECK, chest[1] + spine_dir[1] * NECK)
    head = (neck[0] + spine_dir[0] * HEAD, neck[1] + spine_dir[1] * HEAD)

    sh_r = (chest[0] + perp[0] * SHOULDER_DX, chest[1] + perp[1] * SHOULDER_DX)
    sh_l = (chest[0] - perp[0] * SHOULDER_DX, chest[1] - perp[1] * SHOULDER_DX)

    el_r = _seg(sh_r, UPPER_ARM, angles.get("armR_sh", 0.0))
    ha_r = _seg(el_r, FOREARM, angles.get("armR_sh", 0.0) + angles.get("armR_el", 0.0))
    el_l = _seg(sh_l, UPPER_ARM, angles.get("armL_sh", 0.0))
    ha_l = _seg(el_l, FOREARM, angles.get("armL_sh", 0.0) + angles.get("armL_el", 0.0))

    hip_r = (hips[0] + perp[0] * HIP_DX, hips[1] + perp[1] * HIP_DX)
    hip_l = (hips[0] - perp[0] * HIP_DX, hips[1] - perp[1] * HIP_DX)
    kn_r = _seg(hip_r, THIGH, angles.get("legR_hip", 0.0))
    ft_r = _seg(kn_r, SHIN, angles.get("legR_hip", 0.0) + angles.get("legR_kn", 0.0))
    kn_l = _seg(hip_l, THIGH, angles.get("legL_hip", 0.0))
    ft_l = _seg(kn_l, SHIN, angles.get("legL_hip", 0.0) + angles.get("legL_kn", 0.0))

    return {
        "hips": hips,
        "chest": chest,
        "neck": neck,
        "head": head,
        "shR": sh_r,
        "elR": el_r,
        "haR": ha_r,
        "shL": sh_l,
        "elL": el_l,
        "haL": ha_l,
        "hipR": hip_r,
        "knR": kn_r,
        "ftR": ft_r,
        "hipL": hip_l,
        "knL": kn_l,
        "ftL": ft_l,
    }


def lerp(a: PoseAngles, b: PoseAngles, t: float) -> PoseAngles:
    """两组角度线性插值(缺省键取 0)。"""
    t = max(0.0, min(1.0, t))
    return {k: a.get(k, 0.0) * (1 - t) + b.get(k, 0.0) * t for k in ANGLE_KEYS}


def _ease(t: float) -> float:
    return t * t * (3 - 2 * t)


def _base(**over: float) -> PoseAngles:
    """默认站姿 + 覆盖。"""
    a: PoseAngles = {k: 0.0 for k in ANGLE_KEYS}
    a.update(armR_sh=8.0, armL_sh=-8.0, legR_hip=2.0, legL_hip=-2.0)
    a.update(over)
    return a


# ---------------------------------------------------------------------------
# 各动作的姿势函数(相位 → 角度)
# ---------------------------------------------------------------------------


def _stand(p: float) -> PoseAngles:
    breathe = math.sin(p * 2 * math.pi) * 1.5
    return _base(lean=breathe * 0.4, armR_sh=8 + breathe, armL_sh=-8 - breathe)


def _walk(p: float) -> PoseAngles:
    s = math.sin(p * 2 * math.pi)
    c = math.cos(p * 2 * math.pi)
    return _base(
        lean=4.0,
        legR_hip=26 * s,
        legL_hip=-26 * s,
        legR_kn=-18 * max(0.0, -s),
        legL_kn=-18 * max(0.0, s),
        armR_sh=8 - 24 * s,
        armL_sh=-8 + 24 * s,
        armR_el=10,
        armL_el=-10,
        rootY=0.02 * abs(c) - 0.02,
        rootX=0.0,
    )


def _run(p: float) -> PoseAngles:
    s = math.sin(p * 2 * math.pi)
    return _base(
        lean=14.0,
        legR_hip=42 * s,
        legL_hip=-42 * s,
        legR_kn=-55 * max(0.0, -s) - 20,
        legL_kn=-55 * max(0.0, s) - 20,
        armR_sh=15 - 42 * s,
        armL_sh=-15 + 42 * s,
        armR_el=55,
        armL_el=-55,
        rootY=0.05 * abs(math.sin(p * 4 * math.pi)) - 0.02,
    )


def _jump(p: float) -> PoseAngles:
    # 0-0.25 下蹲蓄力, 0.25-0.6 腾空, 0.6-1 落地缓冲
    if p < 0.25:
        t = _ease(p / 0.25)
        return _base(
            lean=6,
            rootY=-0.10 * t,
            legR_hip=10 * t,
            legL_hip=-10 * t,
            legR_kn=-30 * t,
            legL_kn=-30 * t,
            armR_sh=8 - 30 * t,
            armL_sh=-8 + 30 * t,
        )
    if p < 0.6:
        t = (p - 0.25) / 0.35
        h = math.sin(t * math.pi)
        return _base(
            lean=-4 * h,
            rootY=-0.10 + 0.42 * h,
            legR_hip=30 * h,
            legL_hip=-18 * h,
            legR_kn=-25 * h,
            legL_kn=-35 * h,
            armR_sh=8 + 150 * h,
            armL_sh=-8 - 150 * h,
        )
    t = _ease((p - 0.6) / 0.4)
    return _base(
        lean=8 * (1 - t),
        rootY=-0.10 * (1 - t),
        legR_hip=10 * (1 - t),
        legL_hip=-10 * (1 - t),
        legR_kn=-28 * (1 - t),
        legL_kn=-28 * (1 - t),
        armR_sh=8 - 25 * (1 - t),
        armL_sh=-8 + 25 * (1 - t),
    )


def _point(p: float) -> PoseAngles:
    reach = _ease(min(1.0, p * 2.2))
    return _base(lean=3 * reach, armR_sh=8 + 78 * reach, armR_el=6 * reach, armL_sh=-10)


def _raise(p: float) -> PoseAngles:
    up = _ease(min(1.0, p * 2.0))
    return _base(
        lean=-2 * up,
        armR_sh=8 + 158 * up,
        armR_el=-18 * up,
        armL_sh=-8 - 158 * up,
        armL_el=18 * up,
        head=-6 * up,
    )


def _push_door(p: float) -> PoseAngles:
    push = _ease(min(1.0, p * 1.8))
    return _base(
        lean=12 * push,
        armR_sh=8 + 62 * push,
        armR_el=18 * push,
        armL_sh=-8 - 62 * push,
        armL_el=-18 * push,
        legR_hip=16 * push,
        legL_hip=-22 * push,
        legL_kn=-14 * push,
    )


def _draw_line(p: float) -> PoseAngles:
    sweep = math.sin(p * 2 * math.pi)
    return _base(lean=5, armR_sh=8 + 70 + 22 * sweep, armR_el=8, armL_sh=-14 - 12 * sweep)


def _sit(p: float) -> PoseAngles:
    t = _ease(min(1.0, p * 1.6))
    return _base(
        lean=8 * t,
        rootY=-0.20 * t,
        legR_hip=88 * t,
        legL_hip=88 * t,
        legR_kn=-86 * t,
        legL_kn=-86 * t,
        armR_sh=8 + 30 * t,
        armR_el=35 * t,
        armL_sh=-8 - 30 * t,
        armL_el=-35 * t,
    )


def _wave(p: float) -> PoseAngles:
    w = math.sin(p * 2 * math.pi * 2)
    return _base(armR_sh=8 + 150, armR_el=22 * w, armL_sh=-9, head=-3)


def _think(p: float) -> PoseAngles:
    t = _ease(min(1.0, p * 2.0))
    return _base(lean=4 * t, armR_sh=8 + 52 * t, armR_el=-72 * t, armL_sh=-12, head=-8 * t)


def _surprise(p: float) -> PoseAngles:
    j = math.sin(p * 2 * math.pi * 3) * 2
    return _base(
        lean=-6 + j,
        armR_sh=8 + 130,
        armR_el=25,
        armL_sh=-8 - 130,
        armL_el=-25,
        legR_hip=6,
        legL_hip=-6,
        head=-10,
        rootY=0.03,
    )


def _march(p: float) -> PoseAngles:
    s = math.sin(p * 2 * math.pi * 2)
    lift = max(0.0, s)
    return _base(
        lean=2,
        legR_hip=40 * lift,
        legR_kn=-70 * lift,
        legL_hip=-6,
        armR_sh=8 - 30 * lift,
        armL_sh=-8 + 30 * lift,
        rootY=0.03 * lift,
    )


def _kick(p: float) -> PoseAngles:
    k = math.sin(p * 2 * math.pi)
    k = max(0.0, k)
    return _base(
        lean=-8 * k,
        legR_hip=78 * k,
        legR_kn=-18 * k,
        legL_hip=-4,
        armR_sh=8 - 40 * k,
        armL_sh=-8 - 30 * k,
    )


def _shuffle(p: float) -> PoseAngles:
    s = math.sin(p * 2 * math.pi)
    return _base(
        lean=2,
        legR_hip=12 * s,
        legL_hip=-12 * s,
        legR_kn=-8 * max(0.0, -s),
        armR_sh=8 - 10 * s,
        armL_sh=-8 + 10 * s,
        rootX=0.02 * s,
    )


def _twist(p: float) -> PoseAngles:
    s = math.sin(p * 2 * math.pi)
    return _base(
        lean=3 * s,
        armR_sh=8 + 40 * s,
        armL_sh=-8 + 40 * s,
        armR_el=20 * s,
        armL_el=20 * s,
        legR_hip=2 + 8 * s,
        legL_hip=-2 + 8 * s,
    )


def _dance(p: float) -> PoseAngles:
    s = math.sin(p * 2 * math.pi)
    c = math.cos(p * 2 * math.pi)
    return _base(
        lean=6 * s,
        armR_sh=8 + 120 + 40 * s,
        armR_el=30 * c,
        armL_sh=-8 - 120 + 40 * s,
        armL_el=-30 * c,
        legR_hip=2 + 20 * s,
        legL_hip=-2 - 20 * s,
        legR_kn=-20 * max(0.0, s),
        legL_kn=-20 * max(0.0, -s),
        rootY=0.04 * abs(s) - 0.02,
        head=-4 * s,
    )


def _crouch(p: float) -> PoseAngles:
    t = _ease(min(1.0, p * 2.0))
    return _base(
        lean=10 * t,
        rootY=-0.26 * t,
        legR_hip=46 * t,
        legL_hip=46 * t,
        legR_kn=-72 * t,
        legL_kn=-72 * t,
        armR_sh=8 + 25 * t,
        armL_sh=-8 - 25 * t,
    )


def _shrug(p: float) -> PoseAngles:
    t = _ease(min(1.0, p * 2.2)) * (1 - 0.35 * max(0.0, math.sin(p * 2 * math.pi)))
    return _base(
        armR_sh=8 + 88 * t, armR_el=-58 * t, armL_sh=-8 - 88 * t, armL_el=58 * t, head=-4 * t
    )


def _celebrate(p: float) -> PoseAngles:
    s = math.sin(p * 2 * math.pi)
    return _base(
        armR_sh=8 + 165,
        armR_el=15 * s,
        armL_sh=-8 - 165,
        armL_el=-15 * s,
        rootY=0.05 * abs(s),
        lean=-3,
        head=-8,
    )


#: 动作 → 姿势函数
POSE_FUNCS: dict[str, Callable[[float], PoseAngles]] = {
    "stand": _stand,
    "walk": _walk,
    "run": _run,
    "jump": _jump,
    "point": _point,
    "raise": _raise,
    "push_door": _push_door,
    "draw_line": _draw_line,
    "sit": _sit,
    "wave": _wave,
    "think": _think,
    "surprise": _surprise,
    "march": _march,
    "kick": _kick,
    "shuffle": _shuffle,
    "twist": _twist,
    "dance": _dance,
    "crouch": _crouch,
    "shrug": _shrug,
    "celebrate": _celebrate,
}

#: 渲染器可实现的动作集合(whitelist.assert_renderable 校验)
POSES: frozenset[str] = frozenset(POSE_FUNCS)

#: 一次性动作(相位按 [0,1] 推进, 不循环)
ONESHOT: frozenset[str] = frozenset(
    {"jump", "point", "raise", "push_door", "sit", "crouch", "think", "shrug", "surprise"}
)


def angles_at(action: str, phase: float) -> PoseAngles:
    """取某动作在给定相位的角度(相位自动归一)。"""
    fn = POSE_FUNCS.get(action)
    if fn is None:
        raise KeyError(f"unknown action {action!r}")
    if action in ONESHOT:
        p = max(0.0, min(1.0, phase))
    else:
        p = phase % 1.0
    return fn(p)


__all__ = [
    "ANGLE_KEYS",
    "BONES",
    "HIP_Y",
    "JOINTS",
    "ONESHOT",
    "POSES",
    "POSE_FUNCS",
    "PoseAngles",
    "angles_at",
    "lerp",
    "solve",
]
