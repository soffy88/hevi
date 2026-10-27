"""Offline tests for animation.physics2d. CPU only, no network, no keys."""

import pytest

from hevi.capabilities.physics2d import simulate_physics2d
from hevi.capabilities.registry import CapabilityError, get


def _plan(bodies, **world):
    plan = {"bodies": bodies, "world": {"dt": 1.0 / 60.0, "steps": 120, "sample_every": 1}}
    plan["world"].update(world)
    return plan


def test_registry_name():
    from hevi.capabilities import physics2d  # noqa: F401  (self-registers)
    assert get("animation.physics2d").name == "animation.physics2d"


def test_circle_drops_and_settles_on_floor():
    result = simulate_physics2d(_plan(
        [{"id": "ball", "shape": "circle", "x": 100, "y": 100, "radius": 20, "restitution": 0.0}],
        gravity_y=980.0, floor_y=500.0,
    ))
    final = result["final_state"][0]
    assert final["y"] == pytest.approx(480.0, abs=1.0)
    assert final["vy"] == pytest.approx(0.0, abs=1.0)
    assert "ball" in result["summary"]["resting_bodies"]


def test_circle_bounces_with_restitution():
    result = simulate_physics2d(_plan(
        [{"id": "ball", "shape": "circle", "x": 100, "y": 100, "radius": 20, "restitution": 0.8}],
        gravity_y=980.0, floor_y=500.0, steps=180,
    ))
    ups = [f for f in result["frames"] if f["bodies"][0]["vy"] < -10.0 and f["step"] > 30]
    assert ups, "a bouncing ball must move upward after a floor contact"


def test_determinism():
    plan = _plan(
        [{"id": "a", "shape": "circle", "x": 50, "y": 50, "vx": 60, "radius": 15},
         {"id": "b", "shape": "circle", "x": 200, "y": 50, "vx": -60, "radius": 15}],
        gravity_y=0.0, steps=60,
    )
    assert simulate_physics2d(plan) == simulate_physics2d(plan)


def test_circle_circle_collision_separates():
    result = simulate_physics2d(_plan(
        [{"id": "a", "shape": "circle", "x": 50, "y": 100, "vx": 120, "radius": 20, "restitution": 1.0},
         {"id": "b", "shape": "circle", "x": 200, "y": 100, "vx": -120, "radius": 20, "restitution": 1.0}],
        gravity_y=0.0, steps=120,
    ))
    assert result["summary"]["collision_count"] >= 1
    a, b = result["final_state"]
    assert abs(b["x"] - a["x"]) >= 40.0 - 1.0


def test_boxes_stack():
    result = simulate_physics2d(_plan(
        [{"id": "low", "shape": "box", "x": 100, "y": 200, "width": 40, "height": 40, "restitution": 0.0},
         {"id": "high", "shape": "box", "x": 100, "y": 100, "width": 40, "height": 40, "restitution": 0.0}],
        gravity_y=980.0, floor_y=500.0, steps=300,
    ))
    by_id = {b["id"]: b for b in result["final_state"]}
    assert by_id["low"]["y"] == pytest.approx(480.0, abs=2.0)
    assert by_id["high"]["y"] == pytest.approx(440.0, abs=2.0)


def test_static_body_does_not_move():
    result = simulate_physics2d(_plan(
        [{"id": "wall", "shape": "box", "x": 100, "y": 400, "width": 200, "height": 20, "static": True},
         {"id": "ball", "shape": "circle", "x": 100, "y": 100, "radius": 20, "restitution": 0.0}],
        gravity_y=980.0, steps=120,
    ))
    wall = [b for b in result["final_state"] if b["id"] == "wall"][0]
    assert wall["x"] == 100.0 and wall["y"] == 400.0


@pytest.mark.parametrize("bad", [
    [{"id": "x", "shape": "triangle", "x": 0, "y": 0}],
    [{"id": "x", "shape": "circle", "x": 0, "y": 0, "radius": -1}],
    [{"id": "x", "shape": "circle", "x": 0, "y": 0, "radius": 10, "restitution": 1.5}],
    [{"id": "x", "shape": "circle", "x": 0, "y": 0, "radius": 10},
     {"id": "x", "shape": "circle", "x": 50, "y": 0, "radius": 10}],
])
def test_invalid_plans_raise(bad):
    with pytest.raises(CapabilityError):
        simulate_physics2d({"bodies": bad, "world": {"dt": 1.0 / 60.0, "steps": 10}})


def test_invalid_dt_raises():
    with pytest.raises(CapabilityError):
        simulate_physics2d(_plan(
            [{"id": "x", "shape": "circle", "x": 0, "y": 0, "radius": 10}], dt=0.0))
