"""Offline tests for scene3d.collision_check. CPU only, no network, no keys."""

import pytest

from hevi.capabilities.collision3d import check_collision3d
from hevi.capabilities.registry import CapabilityError, get


def _pair(plan):
    return check_collision3d(plan)["pairs"][0]


def test_registry_name():
    from hevi.capabilities import collision3d  # noqa: F401  (self-registers)
    assert get("scene3d.collision_check").name == "scene3d.collision_check"


def test_aabb_overlap_penetration_and_normal():
    p = _pair({"objects": [
        {"id": "a", "kind": "aabb", "center": [0, 0, 0], "size": [2, 2, 2]},
        {"id": "b", "kind": "aabb", "center": [1, 0, 0], "size": [2, 2, 2]},
    ]})
    assert p["colliding"] is True
    assert p["penetration"] == pytest.approx(1.0)
    assert p["normal"] == [1.0, 0.0, 0.0]
    assert p["time_of_impact"] == 0.0


def test_aabb_separated_no_impact_without_velocity():
    p = _pair({"objects": [
        {"id": "a", "kind": "aabb", "center": [0, 0, 0], "size": [2, 2, 2]},
        {"id": "b", "kind": "aabb", "center": [5, 0, 0], "size": [2, 2, 2]},
    ]})
    assert p["colliding"] is False
    assert p["time_of_impact"] is None


def test_aabb_touching_counts_as_colliding_zero_penetration():
    p = _pair({"objects": [
        {"id": "a", "kind": "aabb", "center": [0, 0, 0], "size": [2, 2, 2]},
        {"id": "b", "kind": "aabb", "center": [2, 0, 0], "size": [2, 2, 2]},
    ]})
    assert p["colliding"] is True
    assert p["penetration"] == pytest.approx(0.0)


def test_sphere_sphere_overlap():
    p = _pair({"objects": [
        {"id": "a", "kind": "sphere", "center": [0, 0, 0], "radius": 2},
        {"id": "b", "kind": "sphere", "center": [3, 0, 0], "radius": 2},
    ]})
    assert p["colliding"] is True
    assert p["penetration"] == pytest.approx(1.0)
    assert p["normal"] == [1.0, 0.0, 0.0]


def test_sphere_inside_aabb_penetration():
    p = _pair({"objects": [
        {"id": "a", "kind": "sphere", "center": [0, 0, 0], "radius": 1},
        {"id": "b", "kind": "aabb", "center": [0, 0, 0], "size": [4, 4, 4]},
    ]})
    assert p["colliding"] is True
    # Nearest face is 2 units away, plus radius 1.
    assert p["penetration"] == pytest.approx(3.0)


def test_sphere_approaching_aabb_time_of_impact():
    p = _pair({"max_time": 1.0, "objects": [
        {"id": "a", "kind": "sphere", "center": [-5, 0, 0], "radius": 1, "velocity": [10, 0, 0]},
        {"id": "b", "kind": "aabb", "center": [0, 0, 0], "size": [2, 2, 2]},
    ]})
    assert p["colliding"] is False
    assert p["time_of_impact"] == pytest.approx(0.3)


def test_sphere_moving_away_no_impact():
    p = _pair({"max_time": 1.0, "objects": [
        {"id": "a", "kind": "sphere", "center": [-5, 0, 0], "radius": 1, "velocity": [-10, 0, 0]},
        {"id": "b", "kind": "aabb", "center": [0, 0, 0], "size": [2, 2, 2]},
    ]})
    assert p["time_of_impact"] is None


def test_summary_counts():
    result = check_collision3d({"objects": [
        {"id": "a", "kind": "sphere", "center": [0, 0, 0], "radius": 2},
        {"id": "b", "kind": "sphere", "center": [1, 0, 0], "radius": 2},
        {"id": "c", "kind": "sphere", "center": [100, 0, 0], "radius": 2},
    ]})
    assert result["summary"]["pair_count"] == 3
    assert result["summary"]["colliding_pair_count"] == 1
    assert result["summary"]["colliding_pairs"] == [["a", "b"]]


@pytest.mark.parametrize("bad", [
    [{"id": "a", "kind": "mesh", "center": [0, 0, 0]}],
    [{"id": "a", "kind": "sphere", "center": [0, 0, 0], "radius": -1}],
    [{"id": "a", "kind": "aabb", "center": [0, 0, 0], "size": [2, 0, 2]}],
    [{"id": "a", "kind": "sphere", "center": [0, 0], "radius": 1}],
    [{"id": "a", "kind": "sphere", "center": [0, 0, 0], "radius": 1},
     {"id": "a", "kind": "sphere", "center": [5, 0, 0], "radius": 1}],
])
def test_invalid_objects_raise(bad):
    with pytest.raises(CapabilityError):
        check_collision3d({"objects": bad})
