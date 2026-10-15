"""Unit tests for closed-form spring mathematics."""

import math
from hevi.motion_templates.lib.spring import step_response, multi_target_spring, SpringStep


def test_step_response_boundary_conditions():
    # Before or at tau=0, response must be strictly 0
    assert step_response(-1.0) == 0.0
    assert step_response(0.0) == 0.0

    # Underdamped step response
    r_fast = step_response(0.2, omega_n=14.0, zeta=0.82)
    assert 0.8 < r_fast < 1.05

    # Long time limit approaches 1.0
    r_inf = step_response(5.0, omega_n=14.0, zeta=0.82)
    assert math.isclose(r_inf, 1.0, rel_tol=1e-5)


def test_tiny_overshoot_underdamped():
    # For zeta=0.82, peak overshoot should be very tiny (< 2%)
    max_val = 0.0
    for i in range(100):
        tau = i * 0.02
        val = step_response(tau, omega_n=14.0, zeta=0.82)
        if val > max_val:
            max_val = val

    overshoot_pct = (max_val - 1.0) * 100.0
    assert 0.0 < overshoot_pct < 2.5, f"Overshoot should be tiny (<2.5%), got {overshoot_pct:.3f}%"


def test_critically_damped_no_overshoot():
    # zeta = 1.0 should have zero overshoot
    max_val = 0.0
    for i in range(100):
        tau = i * 0.02
        val = step_response(tau, omega_n=14.0, zeta=1.0)
        if val > max_val:
            max_val = val
        assert val <= 1.000001, "Critically damped spring must not overshoot"


def test_multi_target_superposition():
    steps = [
        SpringStep(t=0.0, val=0.0),
        SpringStep(t=1.0, val=100.0),
        SpringStep(t=2.0, val=50.0),
    ]

    # Before t=0
    assert multi_target_spring(-0.5, steps) == 0.0
    assert multi_target_spring(0.0, steps) == 0.0

    # Between t=0 and t=1
    assert multi_target_spring(0.5, steps) == 0.0

    # At t=1.2, rising towards 100
    v1 = multi_target_spring(1.2, steps)
    assert 70.0 < v1 < 105.0

    # Long after t=2 (e.g. t=5.0), settles at 50.0
    v_final = multi_target_spring(5.0, steps)
    assert math.isclose(v_final, 50.0, rel_tol=1e-4)


def test_multi_target_statelessness():
    steps = [
        {"t": 0.0, "val": 10.0},
        {"t": 1.5, "val": 80.0},
        {"t": 3.0, "val": 20.0},
    ]

    # Calling out of order must produce identical results
    t_targets = [2.0, 0.5, 3.5, 1.2, 2.0]
    results = [multi_target_spring(t, steps) for t in t_targets]

    assert results[0] == results[4], "Random seek must be 100% deterministic and stateless"
