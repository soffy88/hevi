"""Offline tests for image.vector_path. CPU only, no network, no keys."""

import pytest

from hevi.capabilities.registry import CapabilityError, get
from hevi.capabilities.vector_path import process_vector_path

SQUARE = [[0, 0], [10, 0], [10, 10], [0, 10]]
SHIFTED = [[5, 5], [15, 5], [15, 15], [5, 15]]
TRIANGLE = [[0, 0], [10, 0], [0, 10]]


def _plan(paths, operations=None):
    return {"paths": paths, "operations": operations or []}


def test_registry_name():
    from hevi.capabilities import vector_path  # noqa: F401  (self-registers)
    assert get("image.vector_path").name == "image.vector_path"


def test_square_metrics():
    m = process_vector_path(_plan([{"id": "sq", "points": SQUARE}]))["metrics"]["sq"]
    assert m["area"] == pytest.approx(100.0)
    assert m["perimeter"] == pytest.approx(40.0)
    assert m["centroid"] == pytest.approx([5.0, 5.0])
    assert m["bbox"] == [0, 0, 10, 10]
    assert m["svg_path"].startswith("M 0 0")
    assert m["self_intersection_count"] == 0


def test_triangle_area():
    m = process_vector_path(_plan([{"id": "tri", "points": TRIANGLE}]))["metrics"]["tri"]
    assert m["area"] == pytest.approx(50.0)


def test_intersections_of_crossing_squares():
    result = process_vector_path(_plan(
        [{"id": "a", "points": SQUARE}, {"id": "b", "points": SHIFTED}],
        [{"op": "intersections", "a": "a", "b": "b"}],
    ))
    op = result["operations"][0]
    assert op["count"] == 2
    assert [10.0, 5.0] in op["points"]
    assert [5.0, 10.0] in op["points"]


def test_rectangle_boolean_areas():
    result = process_vector_path(_plan(
        [{"id": "a", "points": SQUARE}, {"id": "b", "points": SHIFTED}],
        [{"op": "boolean", "kind": "union", "a": "a", "b": "b"},
         {"op": "boolean", "kind": "intersection", "a": "a", "b": "b"},
         {"op": "boolean", "kind": "difference", "a": "a", "b": "b"}],
    ))
    by_kind = {op["kind"]: op for op in result["operations"]}
    assert by_kind["union"]["area"] == pytest.approx(175.0)
    assert by_kind["intersection"]["area"] == pytest.approx(25.0)
    assert by_kind["difference"]["area"] == pytest.approx(75.0)


def test_rectangle_difference_rects_tile_the_remainder():
    result = process_vector_path(_plan(
        [{"id": "a", "points": SQUARE}, {"id": "b", "points": SHIFTED}],
        [{"op": "boolean", "kind": "difference", "a": "a", "b": "b"}],
    ))
    rects = result["operations"][0]["rects"]
    total = sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects)
    assert total == pytest.approx(75.0)


def test_boolean_non_rectangle_is_unsupported_not_fabricated():
    result = process_vector_path(_plan(
        [{"id": "a", "points": SQUARE}, {"id": "b", "points": TRIANGLE}],
        [{"op": "boolean", "kind": "union", "a": "a", "b": "b"}],
    ))
    op = result["operations"][0]
    assert op["status"] == "unsupported_non_rectangle"
    assert op["area"] is None
    assert op["rects"] is None


def test_simplify_removes_collinear_point_preserving_area():
    pts = [[0, 0], [5, 0], [10, 0], [10, 10], [0, 10]]
    result = process_vector_path(_plan(
        [{"id": "p", "points": pts}],
        [{"op": "simplify", "path": "p"}],
    ))
    op = result["operations"][0]
    assert op["removed"] == 1
    assert op["area_before"] == pytest.approx(op["area_after"])


def test_bowtie_self_intersection():
    bowtie = [[0, 0], [10, 10], [10, 0], [0, 10]]
    m = process_vector_path(_plan([{"id": "b", "points": bowtie}]))["metrics"]["b"]
    assert m["self_intersection_count"] == 1


@pytest.mark.parametrize("bad_paths,bad_ops", [
    ([{"id": "p", "points": [[0, 0], [10, 0]]}], []),
    ([{"id": "p", "points": [[0, 0], [10, "x"], [0, 10]]}], []),
    ([{"id": "p", "points": SQUARE}, {"id": "p", "points": SQUARE}], []),
    ([{"id": "p", "points": SQUARE}], [{"op": "explode", "path": "p"}]),
    ([{"id": "p", "points": SQUARE}], [{"op": "intersections", "a": "p", "b": "missing"}]),
])
def test_invalid_inputs_raise(bad_paths, bad_ops):
    with pytest.raises(CapabilityError):
        process_vector_path(_plan(bad_paths, bad_ops))
