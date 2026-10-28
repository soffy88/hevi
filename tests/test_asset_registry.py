import pytest

from hevi.capabilities import asset_registry as ar
from hevi.capabilities.errors import CapabilityError

VIEWS = {
    "face_closeup": {"file": "face.png", "sha256": "face-sha"},
    "front": {"file": "front.png", "sha256": "front-sha"},
    "side": {"file": "side.png", "sha256": "side-sha"},
    "back": {"file": "back.png", "sha256": "back-sha"},
}


def _character(reg, asset_id="c1", name="守仁"):
    ar.register_asset(reg, asset_id, "character", name, views=dict(VIEWS))
    return reg


def test_character_master_needs_all_four_views():
    reg = ar.new_registry()
    bad = dict(VIEWS)
    del bad["back"]
    with pytest.raises(CapabilityError, match="back"):
        ar.register_asset(reg, "c1", "character", "守仁", views=bad)


def test_alias_resolves_to_same_master():
    reg = _character(ar.new_registry())
    ar.add_alias(reg, "小守仁", "c1")
    assert ar.resolve_name(reg, "小守仁") == "c1"
    assert ar.resolve_name(reg, "守仁") == "c1"


def test_same_name_different_entity_is_not_merged():
    reg = _character(ar.new_registry())
    with pytest.raises(CapabilityError, match="守仁"):
        ar.register_asset(reg, "p1", "prop", "守仁")


def test_scene_master_needs_skeleton_and_light():
    reg = ar.new_registry()
    with pytest.raises(CapabilityError, match="skeleton"):
        ar.register_asset(reg, "s1", "scene", "塾馆")
    ar.register_asset(
        reg, "s1", "scene", "塾馆",
        scene_skeleton={"walls": "east", "door": "south"},
        light="morning window light",
    )
    assert reg["assets"]["s1"]["light"] == "morning window light"


def test_costume_change_keeps_face():
    reg = _character(ar.new_registry())
    ar.add_derivative(
        reg, "c1", "c1-winter",
        changed=["outfit"], unchanged=["face", "hairstyle"],
    )
    variant = reg["assets"]["c1-winter"]
    assert variant["face_closeup"] == {"file": "face.png", "sha256": "face-sha"}
    assert variant["parent_id"] == "c1"


def test_boundary_aspects_do_not_get_derivative_by_default():
    reg = _character(ar.new_registry())
    with pytest.raises(CapabilityError, match="weather"):
        ar.add_derivative(
            reg, "c1", "c1-rain",
            changed=["weather"], unchanged=["face"],
        )
    ar.add_derivative(
        reg, "c1", "c1-rain",
        changed=["weather"], unchanged=["face"], allow_boundary=True,
    )
    assert "c1-rain" in reg["assets"]


def test_at_most_five_variants_per_parent():
    reg = _character(ar.new_registry())
    for i in range(5):
        ar.add_derivative(
            reg, "c1", f"c1-v{i}",
            changed=[f"outfit-{i}"], unchanged=["face"],
        )
    with pytest.raises(CapabilityError, match="5 variants"):
        ar.add_derivative(
            reg, "c1", "c1-v5",
            changed=["outfit-5"], unchanged=["face"],
        )


def test_episode_references_only_and_pending_blocks_generation():
    reg = _character(ar.new_registry())
    ar.reference_asset(reg, "ep-1", "c1")
    assert reg["episodes"]["ep-1"]["references"] == ["c1"]
    assert ar.check_episode(reg, "ep-1")["ready"] is True
    ar.mark_pending_material(reg, "ep-1", "shot-3", "c1", "winter outfit missing")
    report = ar.check_episode(reg, "ep-1")
    assert report["ready"] is False
    assert report["pending_material"][0]["shot_id"] == "shot-3"
    with pytest.raises(CapabilityError, match="shot-3"):
        ar.assert_episode_ready(reg, "ep-1")
