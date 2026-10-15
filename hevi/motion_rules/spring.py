"""Closed-form spring animation system (pure function step response).

Supports underdamped, critically damped, and overdamped closed-form solutions.
Multi-target tracks are computed by linear superposition of individual step responses:
value(t) = initial_value + sum_i (delta_target_i * spring_step(t - t_i)).
All calculations are pure functions of time without frame-to-frame mutable state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class SpringConfig:
    """Spring configuration parameters.

    Can be initialized with (stiffness, damping, mass) or (omega, zeta).
    omega: natural angular frequency (rad/s)
    zeta: damping ratio (zeta < 1: underdamped, zeta == 1: critically damped, zeta > 1: overdamped)
    """

    omega: float
    zeta: float
    mass: float = 1.0

    def __init__(
        self,
        *,
        stiffness: float | None = None,
        damping: float | None = None,
        mass: float = 1.0,
        omega: float | None = None,
        zeta: float | None = None,
    ) -> None:
        if mass <= 0.0:
            raise ValueError(f"mass must be positive, got {mass}")

        if omega is not None and zeta is not None:
            if omega <= 0.0:
                raise ValueError(f"omega must be positive, got {omega}")
            if zeta < 0.0:
                raise ValueError(f"zeta must be non-negative, got {zeta}")
            object.__setattr__(self, "omega", float(omega))
            object.__setattr__(self, "zeta", float(zeta))
            object.__setattr__(self, "mass", float(mass))
        elif stiffness is not None and damping is not None:
            if stiffness <= 0.0:
                raise ValueError(f"stiffness must be positive, got {stiffness}")
            if damping < 0.0:
                raise ValueError(f"damping must be non-negative, got {damping}")
            computed_omega = math.sqrt(stiffness / mass)
            computed_zeta = damping / (2.0 * math.sqrt(mass * stiffness))
            object.__setattr__(self, "omega", float(computed_omega))
            object.__setattr__(self, "zeta", float(computed_zeta))
            object.__setattr__(self, "mass", float(mass))
        else:
            # Default snappy UI spring: stiffness=100, damping=15 (omega=10, zeta=0.75)
            object.__setattr__(self, "omega", 10.0)
            object.__setattr__(self, "zeta", 0.75)
            object.__setattr__(self, "mass", float(mass))

    @property
    def stiffness(self) -> float:
        return self.mass * (self.omega**2)

    @property
    def damping(self) -> float:
        return 2.0 * self.mass * self.zeta * self.omega

    def step(self, t: float) -> float:
        """Normalized unit step response at time t (relative to trigger time)."""
        return spring_step(t, self.omega, self.zeta)

    def velocity(self, t: float) -> float:
        """Time derivative of normalized unit step response at time t."""
        return spring_velocity(t, self.omega, self.zeta)


def spring_step(t: float, omega: float, zeta: float) -> float:
    """Pure function calculating unit step response y(t) of a damped spring.

    For t <= 0, y(t) = 0.
    For t -> infinity, y(t) -> 1.
    """
    if t <= 0.0:
        return 0.0

    eps = 1e-7
    if abs(zeta - 1.0) <= eps:
        # Critically damped
        decay = math.exp(-omega * t)
        return 1.0 - decay * (1.0 + omega * t)
    elif zeta < 1.0:
        # Underdamped
        omega_d = omega * math.sqrt(1.0 - zeta * zeta)
        decay = math.exp(-zeta * omega * t)
        envelope = math.cos(omega_d * t) + (zeta * omega / omega_d) * math.sin(omega_d * t)
        return 1.0 - decay * envelope
    else:
        # Overdamped
        omega_d = omega * math.sqrt(zeta * zeta - 1.0)
        decay = math.exp(-zeta * omega * t)
        envelope = math.cosh(omega_d * t) + (zeta * omega / omega_d) * math.sinh(omega_d * t)
        return 1.0 - decay * envelope


def spring_velocity(t: float, omega: float, zeta: float) -> float:
    """Pure function calculating derivative y'(t) of unit step response."""
    if t <= 0.0:
        return 0.0

    eps = 1e-7
    if abs(zeta - 1.0) <= eps:
        decay = math.exp(-omega * t)
        return (omega * omega) * t * decay
    elif zeta < 1.0:
        omega_d = omega * math.sqrt(1.0 - zeta * zeta)
        decay = math.exp(-zeta * omega * t)
        return ((omega * omega) / omega_d) * decay * math.sin(omega_d * t)
    else:
        omega_d = omega * math.sqrt(zeta * zeta - 1.0)
        decay = math.exp(-zeta * omega * t)
        return ((omega * omega) / omega_d) * decay * math.sinh(omega_d * t)


class SpringTrack:
    """Multi-target spring track.

    A value that changes target multiple times is evaluated as the linear sum
    of one closed-form spring response per change:
        value(t) = initial_value + sum_{i: t_i <= t} delta_i * spring_step(t - t_i)
    Pure function of time without internal mutation during evaluation.
    """

    def __init__(
        self,
        keyframes: Sequence[tuple[float, float]] | None = None,
        spring: SpringConfig | None = None,
        *,
        initial_value: float = 0.0,
    ) -> None:
        self.spring = spring if spring is not None else SpringConfig()
        self.initial_value = float(initial_value)
        self._keyframes: list[tuple[float, float]] = []
        if keyframes:
            for t, val in keyframes:
                self.add_keyframe(t, val)

    def add_keyframe(self, t: float, target: float) -> None:
        """Add a target change event at time t."""
        self._keyframes.append((float(t), float(target)))
        self._keyframes.sort(key=lambda item: item[0])

    @property
    def keyframes(self) -> list[tuple[float, float]]:
        return list(self._keyframes)

    def _get_steps(self) -> list[tuple[float, float]]:
        """Compute delta changes for each keyframe."""
        if not self._keyframes:
            return []
        steps: list[tuple[float, float]] = []
        prev_target = self.initial_value
        for t, target in self._keyframes:
            delta = target - prev_target
            steps.append((t, delta))
            prev_target = target
        return steps

    def value(self, t: float) -> float:
        """Pure function computing track value at time t."""
        steps = self._get_steps()
        if not steps:
            return self.initial_value

        res = self.initial_value
        omega = self.spring.omega
        zeta = self.spring.zeta
        for t_k, delta in steps:
            if t >= t_k:
                res += delta * spring_step(t - t_k, omega, zeta)
        return res

    def velocity(self, t: float) -> float:
        """Pure function computing track velocity (derivative) at time t."""
        steps = self._get_steps()
        if not steps:
            return 0.0

        vel = 0.0
        omega = self.spring.omega
        zeta = self.spring.zeta
        for t_k, delta in steps:
            if t >= t_k:
                vel += delta * spring_velocity(t - t_k, omega, zeta)
        return vel

    def values(self, ts: Iterable[float]) -> list[float]:
        """Compute values for multiple sample times."""
        return [self.value(t) for t in ts]
