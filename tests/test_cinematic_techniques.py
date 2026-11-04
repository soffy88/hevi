"""Tests for the cinematic technique libraries (movie-atmosphere 10-site
intake, 2026-10-25). Offline, data-only, zero cost."""

import json
from pathlib import Path

import pytest

from hevi.capabilities import cinematic_techniques as ct
from hevi.capabilities.errors import CapabilityError


def test_movement_catalogue_counts_and_fields() -> None:
    rows = ct.list_movements()
    assert len(rows) == 46
    assert len({r["id"] for r in rows}) == 46
    for row in rows:
        assert row["movement"] and row["speed"] and row["framing"] and row["end"]
        assert row["category"] and row["name_en"] and row["name_zh"]
    assert len(ct.list_movements("Pan/Tilt")) == 7
    assert len(ct.list_movements("Drone/Crane")) == 5
    assert len(ct.list_movements("Specials")) == 6
    assert ct.get_movement("helicopter_shot")["name_zh"] == "直升机航拍"
    assert ct.get_movement("dolly_in")["name_en"] == "Dolly in"
    with pytest.raises(CapabilityError):
        ct.get_movement("no-such-move")


def test_vvsvs_catalogue_counts_and_layers() -> None:
    rows = ct.list_techniques()
    assert len(rows) == 30
    assert len({r["id"] for r in rows}) == 30
    for row in rows:
        assert row["note_zh"] and row["prompt_fragment_en"]
        assert row["source_url"] == "https://vvsvs.pro/cinematique"
    assert len(ct.list_techniques(category="Lighting")) == 8
    assert len(ct.list_techniques(layer="lighting")) == 8
    flagged = {r["id"] for r in rows if r["is_camera_movement"]}
    assert flagged == {"vv_dolly", "vv_vertigo", "vv_crane", "vv_steadicam"}


def test_melies_index_categories_and_total() -> None:
    cats = ct.list_melies()
    assert set(cats) == {
        "camera_moves",
        "shot_sizes",
        "angles",
        "lighting",
        "composition",
        "lenses",
        "grades",
        "motion",
        "effects",
        "transitions",
        "atmosphere",
        "styles",
    }
    assert sum(len(v) for v in cats.values()) == 380
    assert "Dolly In" in cats["camera_moves"]
    assert "Golden Hour" in cats["lighting"]
    assert ct.list_melies("angles") == {"angles": cats["angles"]}
    with pytest.raises(CapabilityError):
        ct.list_melies("no-such-category")


def test_one_movement_rule_ids() -> None:
    assert ct.validate_shot(["dolly_in"])["movement"] == "dolly_in"
    with pytest.raises(CapabilityError):
        ct.validate_shot(["dolly_in", "crane_up"])
    with pytest.raises(CapabilityError):
        ct.validate_shot([])
    with pytest.raises(CapabilityError):
        ct.validate_shot(["no-such-move"])


def test_one_movement_rule_text_detection() -> None:
    assert ct.detect_movements_in_text("slow dolly in toward the scholar") == ["dolly_in"]
    with pytest.raises(CapabilityError):
        ct.validate_shot(text="crane up, then dolly in")
    with pytest.raises(CapabilityError):
        ct.validate_shot(text="a quiet room, no camera move named")


def test_compose_allows_layers_but_not_second_movement() -> None:
    shot = ct.compose_shot_prompt(
        "the scholar", "dolly_in", ["vv_golden_hour", "vv_rule_thirds"]
    )
    assert shot["movement"]["id"] == "dolly_in"
    assert "Camera movement:" in shot["prompt_en"]
    assert "golden hour" in shot["prompt_en"].lower()
    assert "the scholar" in shot["prompt_en"]
    with pytest.raises(CapabilityError):
        ct.compose_shot_prompt("the scholar", "dolly_in", ["vv_crane"])
    with pytest.raises(CapabilityError):
        ct.compose_shot_prompt("the scholar", "no-such-move", [])


def test_capabilities_registered_and_render(tmp_path: Path) -> None:
    import hevi.capabilities as caps

    assert "shot.camera_movements" in caps.names()
    assert "shot.cinematic_techniques" in caps.names()
    cap = caps.get("shot.camera_movements")
    result = cap.render_safe(
        {"action": "compose", "subject": "the scholar",
         "movement": "dolly_in", "layers": ["vv_golden_hour"]},
        tmp_path / "shot", duration=1.0, aspect="16:9", seed=1,
    )
    payload = json.loads(Path(result.qa["result_json"]).read_text(encoding="utf-8"))
    assert payload["movement"]["id"] == "dolly_in"
    assert payload["layers"][0]["id"] == "vv_golden_hour"
    cap2 = caps.get("shot.cinematic_techniques")
    result2 = cap2.render_safe(
        {"action": "list_melies", "category": "styles"},
        tmp_path / "melies", duration=1.0, aspect="16:9", seed=1,
    )
    payload2 = json.loads(Path(result2.qa["result_json"]).read_text(encoding="utf-8"))
    assert "Wuxia" in payload2["melies"]["styles"]
