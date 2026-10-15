"""Python implementation of closed-form spring mathematics.

Matches hevi/motion_templates/lib/spring.js exactly.
Used for offline trajectory validation, timing calculations, and unit tests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


def step_response(tau: float, omega_n: float = 14.0, zeta: float = 0.82) -> float:
    """Underdamped/critically-damped closed-form step response from 0 to 1."""
    if tau <= 0.0:
        return 0.0

    if zeta < 0.9999:
        omega_d = omega_n * math.sqrt(1.0 - zeta * zeta)
        decay = math.exp(-zeta * omega_n * tau)
        envelope = math.cos(omega_d * tau) + (zeta / math.sqrt(1.0 - zeta * zeta)) * math.sin(omega_d * tau)
        return 1.0 - decay * envelope
    elif zeta <= 1.0001:
        return 1.0 - math.exp(-omega_n * tau) * (1.0 + omega_n * tau)
    else:
        alpha = zeta * omega_n
        beta = omega_n * math.sqrt(zeta * zeta - 1.0)
        return 1.0 - math.exp(-alpha * tau) * (math.cosh(beta * tau) + (alpha / beta) * math.sinh(beta * tau))


@dataclass(slots=True)
class SpringStep:
    t: float
    val: float
    omega: float | None = None
    zeta: float | None = None


def multi_target_spring(
    t: float,
    steps: Sequence[SpringStep | dict],
    default_omega: float = 14.0,
    default_zeta: float = 0.82,
) -> float:
    """Superposition of step responses across a sequence of target transitions."""
    if not steps:
        return 0.0

    normalized: list[SpringStep] = []
    for s in steps:
        if isinstance(s, dict):
            normalized.append(
                SpringStep(
                    t=float(s["t"]),
                    val=float(s["val"]),
                    omega=float(s["omega"]) if "omega" in s and s["omega"] is not None else None,
                    zeta=float(s["zeta"]) if "zeta" in s and s["zeta"] is not None else None,
                )
            )
        else:
            normalized.append(s)

    sorted_steps = sorted(normalized, key=lambda x: x.t)
    if t < sorted_steps[0].t:
        return sorted_steps[0].val

    val = sorted_steps[0].val
    for i in range(1, len(sorted_steps)):
        step = sorted_steps[i]
        if t < step.t:
            break
        prev = sorted_steps[i - 1]
        delta = step.val - prev.val
        if abs(delta) < 1e-9:
            continue
        omega = step.omega if step.omega is not None else default_omega
        zeta = step.zeta if step.zeta is not None else default_zeta
        val += delta * step_response(t - step.t, omega_n=omega, zeta=zeta)

    return val
