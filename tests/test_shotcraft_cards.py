"""Tests for the video-shotcraft recipe card import (shotlang data asset
+ shot.recipe_cards capability). Offline, data-only."""

import json
from pathlib import Path

import pytest

from hevi.creative.shotlang import shotcraft as sc


def test_index_counts_match_upstream() -> None:
    counts = sc.counts()
    assert counts["total"] == 124
    assert counts["by_category"] == {
        "camera": 10,
        "data": 5,
        "effects": 15,
        "interaction": 11,
        "opening": 11,
        "outro": 6,
        "rhythm": 8,
        "transition": 15,
        "typography": 22,
        "ui-entrance": 21,
    }
    index = sc.load_index()
    assert index["license"] == "Apache-2.0"
    assert index["upstream_commit"] == "43bd349a136651865ecfa6ea1cf012f6e957d304"
    assert len({c["name"] for c in index["cards"]}) == 124


def test_every_card_file_and_demo_pointer() -> None:
    for card in sc.load_index()["cards"]:
        path = sc.DATA_DIR / card["file"]
        assert path.exists(), card["file"]
        assert card["one_liner"], card["name"]
        # Stable sections across all 124 cards; the core-recipe section's
        # heading varies upstream (动效核心 / 两式选型 / 动作阶段 / 做法 ...).
        for section in ("意图", "参数表", "已知坑", "参考实现"):
            assert any(s.startswith(section) for s in card["sections"]), (
                card["name"],
                section,
            )
        assert card["demo"].startswith("demos/"), card["name"]


def test_get_card_returns_full_markdown() -> None:
    card = sc.get_card("crash-zoom-punch")
    assert card["category"] == "camera"
    assert "## 动效核心" in card["markdown"]
    assert "## 参数表" in card["markdown"]
    with pytest.raises(KeyError):
        sc.get_card("no-such-card")


def test_search_and_filters() -> None:
    assert len(sc.list_cards(category="typography")) == 22
    hits = sc.list_cards(query="crash-zoom-punch")
    assert [h["name"] for h in hits] == ["crash-zoom-punch"]
    assert sc.list_cards(energy="高")
    entries = sc.motion_library_entries()
    assert len(entries) == 124
    assert {"id", "name", "desc"} <= set(entries[0])


def test_capability_registered_and_renders(tmp_path: Path) -> None:
    import hevi.capabilities as caps
    import hevi.capabilities.shotcraft  # noqa: F401  (import-time registration)

    assert "shot.recipe_cards" in caps.names()
    cap = caps.get("shot.recipe_cards")

    result = cap.render_safe(
        {"category": "camera"}, tmp_path / "cat", duration=1.0, aspect="16:9", seed=1
    )
    payload = json.loads(Path(result.qa["catalogue_json"]).read_text(encoding="utf-8"))
    assert payload["returned"] == 10
    assert payload["counts"]["total"] == 124
    assert payload["license"] == "Apache-2.0"

    result = cap.render_safe(
        {"name": "basic-3d-scene"}, tmp_path / "one", duration=1.0, aspect="16:9", seed=1
    )
    assert Path(result.qa["card_markdown"]).exists()
    payload = json.loads(Path(result.qa["catalogue_json"]).read_text(encoding="utf-8"))
    assert payload["cards"][0]["name"] == "basic-3d-scene"
    assert "camera = stepTransform.inverse()" in payload["cards"][0]["markdown"]

    from hevi.capabilities.errors import CapabilityError

    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"name": "nope"}, tmp_path / "bad", duration=1.0, aspect="16:9", seed=1
        )
