"""Tests for Python closed-form spring implementation."""

import math
import pytest
from hevi.motion_rules.spring import SpringConfig, SpringTrack, spring_step, spring_velocity


def test_spring_config_conversion() -> None:
    # omega = 10, zeta = 0.5, mass = 1
    # stiffness = 100, damping = 10
    cfg1 = SpringConfig(omega=10.0, zeta=0.5, mass=1.0)
    assert math.isclose(cfg1.stiffness, 100.0, rel_tol=1e-7)
    assert math.isclose(cfg1.damping, 10.0, rel_tol=1e-7)

    cfg2 = SpringConfig(stiffness=100.0, damping=10.0, mass=1.0)
    assert math.isclose(cfg2.omega, 10.0, rel_tol=1e-7)
    assert math.isclose(cfg2.zeta, 0.5, rel_tol=1e-7)


def test_spring_config_invalid() -> None:
    with pytest.raises(ValueError):
        SpringConfig(omega=-1.0, zeta=0.5)
    with pytest.raises(ValueError):
        SpringConfig(stiffness=-10.0, damping=5.0)
    with pytest.raises(ValueError):
        SpringConfig(mass=0.0)


def test_step_response_boundaries() -> None:
    # Before trigger, value is 0
    assert spring_step(-1.0, 10.0, 0.75) == 0.0
    assert spring_step(0.0, 10.0, 0.75) == 0.0
    assert spring_velocity(0.0, 10.0, 0.75) == 0.0

    # Long after trigger, settles to 1.0
    assert math.isclose(spring_step(10.0, 10.0, 0.75), 1.0, abs_tol=1e-5)
    assert math.isclose(spring_step(10.0, 10.0, 1.0), 1.0, abs_tol=1e-5)
    assert math.isclose(spring_step(10.0, 10.0, 1.5), 1.0, abs_tol=1e-4)


def test_spring_step_regimes() -> None:
    # Underdamped has overshoot (> 1.0)
    under_vals = [spring_step(t * 0.05, 10.0, 0.3) for t in range(50)]
    assert max(under_vals) > 1.05

    # Critically damped is monotonic or virtually no overshoot (<= 1.0)
    crit_vals = [spring_step(t * 0.05, 10.0, 1.0) for t in range(50)]
    assert max(crit_vals) <= 1.000001

    # Overdamped is also strictly monotonic
    over_vals = [spring_step(t * 0.05, 10.0, 2.0) for t in range(50)]
    assert max(over_vals) <= 1.000001


def test_velocity_derivative() -> None:
    # Numerical derivative check
    omega, zeta = 10.0, 0.7
    dt = 1e-6
    for t in [0.1, 0.3, 0.7, 1.2]:
        analytic_v = spring_velocity(t, omega, zeta)
        num_v = (spring_step(t + dt, omega, zeta) - spring_step(t - dt, omega, zeta)) / (2 * dt)
        assert math.isclose(analytic_v, num_v, rel_tol=1e-4)


def test_spring_track_stateless_pure_function() -> None:
    cfg = SpringConfig(stiffness=120.0, damping=14.0)
    track = SpringTrack([(0.0, 100.0), (1.0, 50.0), (2.5, 200.0)], spring=cfg, initial_value=0.0)

    # Calling out of chronological order
    val_at_1_5 = track.value(1.5)
    val_at_0_2 = track.value(0.2)
    val_at_3_0 = track.value(3.0)

    # Repeating calls should give exact same result
    assert track.value(1.5) == val_at_1_5
    assert track.value(0.2) == val_at_0_2
    assert track.value(3.0) == val_at_3_0

    # Before start
    assert track.value(-0.5) == 0.0

    # Eventually reaches final target 200.0
    assert math.isclose(track.value(10.0), 200.0, abs_tol=1e-4)
