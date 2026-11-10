"""S29 anidoodle: catalog, attribution, safe area and capability registration."""

from __future__ import annotations

import pytest

from hevi.anidoodle import (
    AnidoodleError,
    check_safe_area,
    families,
    get_style,
    list_styles,
    recommend_style,
)


def test_catalog_has_32_styles_and_media_groups() -> None:
    styles = list_styles()
    assert len(styles) == 32
    assert len({style.id for style in styles}) == 32
    groups = families()
    assert len(groups) >= 10
    assert sum(len(group["styles"]) for group in groups) == 32


def test_style_draw_films_are_named() -> None:
    for style in list_styles():
        assert style.draw_film
        assert style.name
        assert style.medium


def test_recommend_is_explainable_and_avoids_blocked() -> None:
    result = recommend_style("灯塔为什么建在礁石上", intent="explainer")
    assert result["style"]["id"] == "lighthouse"
    assert result["reason"]
    assert len(result["alternatives"]) == 2
    blocked = recommend_style("灯塔", intent="explainer", avoid=["lighthouse"])
    assert blocked["style"]["id"] != "lighthouse"


def test_unknown_style_fails_closed() -> None:
    with pytest.raises(AnidoodleError):
        get_style("not-a-style")


def test_safe_area_s26_vertical() -> None:
    width, height = 1080, 1920
    good = check_safe_area(
        [{"x0": 60, "y0": 150, "x1": 940, "y1": 1540}],
        width=width,
        height=height,
    )
    assert good["ok"] is True
    bad = check_safe_area(
        [{"x0": 20, "y0": 120, "x1": 1000, "y1": 1600}],
        width=width,
        height=height,
    )
    assert bad["ok"] is False
    assert set(bad["failures"][0]["edges"]) == {"left", "top", "right", "bottom"}
    empty = check_safe_area([], width=width, height=height)
    assert empty["ok"] is None
    assert empty["status"] == "not_applicable"


def test_capabilities_registered() -> None:
    from hevi.capabilities import registry

    names = set(registry.names())
    for name in (
        "anidoodle.style_list",
        "anidoodle.still",
        "anidoodle.draw_clip",
        "anidoodle.music",
        "anidoodle.gate",
    ):
        assert name in names


def test_engine_probe_reports_node_and_browser() -> None:
    from hevi.anidoodle import engine_info

    info = engine_info()
    assert info.node_major >= 20
    assert info.npm_deps is True
    assert "headless" in info.browser or "chrome" in info.browser
