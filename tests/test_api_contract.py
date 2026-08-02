from hevi.api.main import app


def test_compatibility_aliases_are_deprecated_in_openapi() -> None:
    paths = app.openapi()["paths"]

    assert paths["/api/tasks/longvideo"]["post"]["deprecated"] is True
    assert paths["/api/canvas/graphs"]["post"]["deprecated"] is True
    assert paths["/api/canvas/graphs/{graph_id}/execute"]["post"]["deprecated"] is True


def test_canonical_task_and_canvas_endpoints_remain_active() -> None:
    paths = app.openapi()["paths"]

    assert "deprecated" not in paths["/api/tasks"]["post"]
    assert "deprecated" not in paths["/api/canvas"]["post"]
    assert "deprecated" not in paths["/api/canvas/{graph_id}/execute"]["post"]


def test_production_and_presenter_boundaries_are_canonical() -> None:
    paths = app.openapi()["paths"]

    assert "deprecated" not in paths["/api/pipeline/productions"]["post"]
    assert "/api/presenters" in paths
    assert "/api/presenters/{presenter_id}" in paths
    assert "/api/presenters/{presenter_id}/test" in paths


def test_trailing_slash_compatibility_aliases_are_hidden_from_openapi() -> None:
    paths = app.openapi()["paths"]

    assert "/api/audio/" not in paths
    assert "/api/subjects/" not in paths
    assert "/api/templates/" not in paths
