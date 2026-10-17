"""运动语言库(纯函数, 确定性) + 物理原语。

七段式运动语言:预备 → 拉伸 → 冲击 → 压扁 → 过冲 → 回稳 → 次级响应。
形变由速度/冲量推导(不是随机 easing);上一段末速度接续下一段初速度。

物理原语(≥8 种实现,全部纯函数):
  1. gravity        重力抛物线
  2. collision      碰撞连锁(冲量传递)
  3. bounce         弹跳(恢复系数)
  4. roll_inertia   滚动惯性(摩擦衰减)
  5. spring         闭式弹簧回稳(复用 hevi.motion_rules.spring)
  6. soft_body      软体压扁(体积守恒)
  7. buoyancy       漂浮(正弦浮力)
  8. water_wave     水波(径向脉冲衰减)
  9. particles_cohere 粒子聚散(向心收敛)

坐标约定:归一化, 原点左上, x 向右, y 向下(屏幕坐标)。位移单位为画面高度/宽度比例。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from hevi.motion_rules.spring import spring_step

# ── 七段式运动语言 ──────────────────────────────────────────────────────
PHASES: tuple[str, ...] = (
    "anticipation",  # 预备
    "stretch",  # 拉伸
    "impact",  # 冲击
    "squash",  # 压扁
    "overshoot",  # 过冲
    "settle",  # 回稳
    "secondary",  # 次级响应
)

# 事件类型 → 所处相位(供审片 HTML / 自检门显示)
EVENT_PHASE: dict[str, str] = {
    "anticipation": "anticipation",
    "drop": "stretch",
    "contact": "impact",
    "impact": "squash",
    "bounce": "overshoot",
    "roll": "overshoot",
    "settle": "settle",
    "wave": "secondary",
    "cohere": "secondary",
    "float": "secondary",
    "press": "squash",
    "spring_response": "secondary",
}

GRAVITY = 9.8


@dataclass
class MotionState:
    """某一帧的运动状态(相对元素 home 的归一化增量)。"""

    dx: float = 0.0
    dy: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    rot: float = 0.0  # 弧度
    vx: float = 0.0
    vy: float = 0.0
    phase: str = "settle"

    def to_dict(self) -> dict[str, float | str]:
        return {
            "dx": self.dx,
            "dy": self.dy,
            "sx": self.sx,
            "sy": self.sy,
            "rot": self.rot,
            "vx": self.vx,
            "vy": self.vy,
            "phase": self.phase,
        }


# ── 物理原语(纯函数) ───────────────────────────────────────────────────


def gravity(
    t: float, *, v0: float = 0.0, g: float = GRAVITY, y0: float = 0.0
) -> tuple[float, float]:
    """1. 重力抛物线:返回 (位移 y, 速度 vy)。y 向下为正。"""
    if t <= 0:
        return y0, v0
    return y0 + v0 * t + 0.5 * g * t * t, v0 + g * t


def bounce_arc(t: float, *, v0: float, g: float = GRAVITY) -> tuple[float, float]:
    """3. 弹跳弧线(v0 为向上初速度, 负值)。返回 (位移 y, 速度 vy)。"""
    if t <= 0:
        return 0.0, v0
    return v0 * t + 0.5 * g * t * t, v0 + g * t


def collision_impulse(v_in: float, restitution: float) -> tuple[float, float]:
    """2. 碰撞:冲量 J = (1+e)·|v_in|, 返回 (冲量, 反弹速度)。"""
    j = (1.0 + restitution) * abs(v_in)
    return j, -restitution * v_in


def roll_inertia(
    t: float, *, v0: float, mu: float = 0.35, g: float = GRAVITY
) -> tuple[float, float]:
    """4. 滚动惯性:摩擦匀减速, 速度过零后停住。返回 (位移 x, 速度 vx)。"""
    if t <= 0:
        return 0.0, v0
    a = mu * g
    t_stop = abs(v0) / a if a > 0 else math.inf
    te = min(t, t_stop)
    dx = v0 * te - 0.5 * a * math.copysign(te * te, v0)
    vx = 0.0 if t >= t_stop else v0 - math.copysign(a * te, v0)
    return dx, vx


def spring_settle(t: float, *, omega: float = 12.0, zeta: float = 0.6, start: float = 1.0) -> float:
    """5. 闭式弹簧回稳:返回从 start 收敛到 0 的位移。"""
    if t <= 0:
        return start
    return start * (1.0 - spring_step(t, omega, zeta))


def soft_body_squash(
    impulse: float, *, k: float = 0.10, max_squash: float = 0.42
) -> tuple[float, float]:
    """6. 软体压扁:由冲量推导形变(体积守恒 sx·sy=1)。返回 (sx, sy)。"""
    sq = min(max_squash, k * impulse)
    sy = 1.0 - sq
    sx = 1.0 / sy if sy > 1e-6 else 1.0
    return sx, sy


def stretch_from_velocity(
    vy: float, vx: float, *, k: float = 0.045, cap: float = 0.35
) -> tuple[float, float]:
    """拉伸:形变由速度推导(竖直运动时竖直拉伸, 体积守恒)。返回 (sx, sy)。"""
    speed = math.hypot(vx, vy)
    st = min(cap, k * speed)
    if abs(vy) >= abs(vx):
        sy = 1.0 + st
        sx = 1.0 / sy
    else:
        sx = 1.0 + st
        sy = 1.0 / sx
    return sx, sy


def buoyancy(
    t: float, *, amp: float = 0.05, freq: float = 0.8, phase: float = 0.0
) -> tuple[float, float]:
    """7. 漂浮:正弦浮力。返回 (位移 y, 速度 vy)。"""
    w = 2.0 * math.pi * freq
    return amp * math.sin(w * t + phase), amp * w * math.cos(w * t + phase)


def water_wave(
    t: float, *, amp: float = 0.06, rings: int = 3, decay: float = 0.6, freq: float = 2.2
) -> float:
    """8. 水波:径向脉冲随距离与时间衰减。返回归一化波幅。"""
    if t <= 0:
        return 0.0
    env = math.exp(-decay * freq * t)
    return amp * env * math.sin(2.0 * math.pi * freq * t / max(1, rings))


def particles_cohere(
    t: float, *, amount: float = 1.0, omega: float = 6.0, zeta: float = 0.7
) -> float:
    """9. 粒子聚散:向心收敛(弹簧式, 无过冲)。返回剩余散开比例 1→0。"""
    if t <= 0:
        return amount
    return amount * (1.0 - spring_step(t, omega, zeta))


def anticipation_dip(t: float, dur: float, *, amount: float = 0.04) -> tuple[float, float]:
    """预备:反方向轻拉(压扁+下沉), 在 dur 内到位并保持。返回 (dy, squash)。"""
    if dur <= 0 or t <= 0:
        return 0.0, 0.0
    u = min(1.0, t / dur)
    # ease-out 到位
    e = 1.0 - (1.0 - u) ** 2
    return amount * e, 0.12 * e


def overshoot_scale(
    t: float, *, peak: float = 1.18, omega: float = 16.0, zeta: float = 0.45
) -> float:
    """过冲:冲击后回弹过冲再回稳。返回缩放系数(围绕 1.0)。"""
    if t <= 0:
        return 1.0
    return 1.0 + (peak - 1.0) * math.sin(math.pi * min(1.0, t * omega / math.pi)) * math.exp(
        -zeta * omega * t
    )


PRIMITIVES: dict[str, Callable[..., object]] = {
    "gravity": gravity,
    "collision": collision_impulse,
    "bounce": bounce_arc,
    "roll_inertia": roll_inertia,
    "spring": spring_settle,
    "soft_body": soft_body_squash,
    "buoyancy": buoyancy,
    "water_wave": water_wave,
    "particles_cohere": particles_cohere,
}

# 主题运动原语 → 用到的物理原语(用于文档/自检)
MOTION_PHYSICS: dict[str, tuple[str, ...]] = {
    "bounce": ("gravity", "collision", "bounce", "soft_body", "spring"),
    "fall": ("gravity", "collision", "roll_inertia", "soft_body", "spring"),
    "float": ("buoyancy", "particles_cohere", "spring"),
    "wave": ("gravity", "water_wave", "particles_cohere", "spring"),
    "roll": ("roll_inertia", "collision", "buoyancy", "spring"),
    "press": ("soft_body", "collision", "buoyancy", "spring"),
    "spring_response": ("spring",),
}


# ── 轨迹求值(速度连续) ─────────────────────────────────────────────────


@dataclass
class _Seg:
    kind: str
    t0: float
    t1: float
    params: dict
    magnitude: float


def _segments(events: list, duration_s: float) -> list[_Seg]:
    evs = sorted(events, key=lambda e: e.t)
    segs: list[_Seg] = []
    for i, e in enumerate(evs):
        t1 = evs[i + 1].t if i + 1 < len(evs) else duration_s
        if t1 < e.t:
            t1 = e.t
        segs.append(_Seg(kind=e.kind, t0=e.t, t1=t1, params=dict(e.params), magnitude=e.magnitude))
    return segs


def sample_track(track, t: float, duration_s: float) -> MotionState:
    """在时间 t 求一条元素轨迹的运动状态。

    速度连续:每个 segment 的初速度 = 上一段末速度(由物理原语推进)。纯函数。
    """
    segs = _segments(track.events, duration_s)
    st = MotionState()
    if not segs:
        return st

    vx, vy = 0.0, 0.0  # 接续速度
    scale_extra = 1.0
    for i, seg in enumerate(segs):
        if t < seg.t0:
            break
        dt = t - seg.t0
        active = t < seg.t1 or i == len(segs) - 1
        kind = seg.kind
        p = seg.params
        mag = seg.magnitude
        st.phase = EVENT_PHASE.get(kind, "settle")

        if kind == "anticipation":
            dur = max(1e-3, seg.t1 - seg.t0)
            dy, sq = anticipation_dip(dt, dur, amount=0.04 * mag)
            st.dy += dy
            st.sy *= 1.0 - sq
            st.sx *= 1.0 + sq * 0.5
            vy = 0.0
        elif kind == "drop":
            g = float(p.get("g", GRAVITY))
            y, vy = gravity(dt, v0=vy, g=g)
            st.dy += y * mag
            sx, sy = stretch_from_velocity(vy, vx)
            st.sx *= sx
            st.sy *= sy
        elif kind == "bounce":
            g = float(p.get("g", GRAVITY))
            # 初速度由上一段(impact)末速度决定, 否则用恢复系数反推
            v0 = vy if vy < 0 else -abs(float(p.get("v0", 2.4))) * mag
            y, vy = bounce_arc(dt, v0=v0, g=g)
            st.dy += y
            sx, sy = stretch_from_velocity(vy, vx)
            st.sx *= sx
            st.sy *= sy
        elif kind in ("impact", "contact"):
            rest = float(p.get("restitution", 0.5))
            j, v_out = collision_impulse(vy if vy != 0 else 2.0, rest)
            vy = v_out
            if dt > 0:
                sx, sy = soft_body_squash(j * mag)
                # 压扁随时间用弹簧回稳
                relax = spring_settle(dt, omega=18.0, zeta=0.55, start=1.0)
                sx = 1.0 + (sx - 1.0) * relax
                sy = 1.0 + (sy - 1.0) * relax
                st.sx *= sx
                st.sy *= sy
        elif kind == "roll":
            mu = float(p.get("mu", 0.35))
            v0 = vx if vx != 0 else 1.1 * mag
            x, vx = roll_inertia(dt, v0=v0, mu=mu)
            st.dx += x
            st.rot += x * 6.0  # 滚动 → 自转
        elif kind == "settle":
            omega = float(p.get("omega", 12.0))
            zeta = float(p.get("zeta", 0.6))
            s = spring_settle(dt, omega=omega, zeta=zeta, start=1.0)
            st.dy += 0.02 * s
            st.sy *= 1.0 + 0.06 * s
            st.sx *= 1.0 - 0.04 * s
            vx = vy = 0.0
        elif kind == "wave":
            rings = int(p.get("rings", 3))
            decay = float(p.get("decay", 0.6))
            w = water_wave(dt, amp=0.06 * mag, rings=rings, decay=decay)
            st.dy += w
            st.sx *= 1.0 + w * 0.5
            st.sy *= 1.0 - w * 0.5
        elif kind == "cohere":
            amount = float(p.get("amount", 1.0)) * mag
            rem = particles_cohere(dt, amount=amount)
            st.dx += 0.03 * rem
            st.sx *= 1.0 - 0.08 * rem
            st.sy *= 1.0 - 0.08 * rem
        elif kind == "float":
            amp = float(p.get("amp", 0.05)) * mag
            freq = float(p.get("freq", 0.8))
            dy, vy = buoyancy(dt, amp=amp, freq=freq)
            st.dy += dy
        elif kind == "press":
            amt = float(p.get("amount", 0.3)) * mag
            relax = spring_settle(dt, omega=10.0, zeta=0.7, start=1.0)
            st.sy *= 1.0 - amt * 0.5 * relax
            st.sx *= 1.0 + amt * 0.35 * relax
        elif kind == "spring_response":
            omega = float(p.get("omega", 14.0))
            zeta = float(p.get("zeta", 0.5))
            s = spring_settle(dt, omega=omega, zeta=zeta, start=1.0)
            st.dy += 0.012 * mag * s
            st.sy *= 1.0 + 0.03 * mag * s

        if not active:
            continue

    # 次级微动:保证静止时高光/形变仍在轻微变化(禁止冻结)
    if track.motion in ("float", "bounce", "fall", "wave", "roll", "press", "spring_response"):
        idle = 0.0015 * math.sin(2.0 * math.pi * 0.9 * t + 0.7)
        st.dy += idle
        st.sy *= 1.0 + idle * 0.5
    st.vx, st.vy = vx, vy
    return st


def phase_at(track, t: float, duration_s: float) -> str:
    """t 时刻该轨迹所处的七段式相位。"""
    return sample_track(track, t, duration_s).phase


def primitives_implemented() -> list[str]:
    """已实现的物理原语名单(用于自检报告)。"""
    return sorted(PRIMITIVES)


__all__ = [
    "PHASES",
    "EVENT_PHASE",
    "GRAVITY",
    "MotionState",
    "gravity",
    "bounce_arc",
    "collision_impulse",
    "roll_inertia",
    "spring_settle",
    "soft_body_squash",
    "stretch_from_velocity",
    "buoyancy",
    "water_wave",
    "particles_cohere",
    "anticipation_dip",
    "overshoot_scale",
    "PRIMITIVES",
    "MOTION_PHYSICS",
    "sample_track",
    "phase_at",
    "primitives_implemented",
]
