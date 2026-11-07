"""Contract tests for story.reference_bundle (offline, deterministic).

Fixtures are invented for these tests only: two unnamed travellers,
a roadside shelter and a lantern, none taken from any real plot or
person. No external skill text or example is reused.
"""

import json

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.reference_bundle import build_bundle, validate_bundle


def _registry():
    return {
        "CH_A": {
            "kind": "character",
            "block": "旅人甲：灰色斗篷、短发、圆脸",
            "face_anchors": "圆脸、短发",
            "outfit": "灰色斗篷",
        },
        "CH_B": {
            "kind": "character",
            "block": "旅人乙：深色外衣、束发、瘦长身形",
            "face_anchors": "束发、瘦长脸",
            "outfit": "深色外衣",
        },
        "SC_A": {
            "kind": "scene",
            "block": "路边小屋：木门、石桌、门廊灯火",
        },
        "PROP_A": {
            "kind": "prop",
            "block": "提灯：竹骨、暖黄灯光",
        },
    }


def _shot(**overrides):
    shot = {
        "shot_id": "SH01",
        "scene_id": "SC_A",
        "character_ids": ["CH_A", "CH_B"],
        "prop_ids": ["PROP_A"],
    }
    shot.update(overrides)
    return shot


def _issues_by_code(issues, code):
    return [i for i in issues if i["code"] == code]


def test_normal_path_order_and_character_order():
    bundle = build_bundle(_shot(), asset_registry=_registry())
    assert bundle["shot_id"] == "SH01"
    refs = bundle["references"]
    assert [(r["role"], r["asset_id"]) for r in refs] == [
        ("character", "CH_A"),
        ("character", "CH_B"),
        ("scene", "SC_A"),
        ("prop", "PROP_A"),
    ]
    assert refs[0]["block"] == "旅人甲：灰色斗篷、短发、圆脸"
    assert refs[2]["block"] == "路边小屋：木门、石桌、门廊灯火"
    assert refs[3]["block"] == "提灯：竹骨、暖黄灯光"
    assert all(set(r) == {"role", "asset_id", "block", "source"} for r in refs)
    assert validate_bundle(bundle, asset_registry=_registry()) == []


def test_character_order_follows_shot_order():
    bundle = build_bundle(
        _shot(character_ids=["CH_B", "CH_A"]), asset_registry=_registry()
    )
    assert [r["asset_id"] for r in bundle["references"][:2]] == ["CH_B", "CH_A"]


def test_costume_variant_splits_into_identity_and_style():
    shot = _shot(
        character_ids=["CH_A"],
        costume_variant={
            "character_id": "CH_B",
            "outfit": "雨天蓑衣",
            "variant_id": "CH_B_rain",
        },
    )
    bundle = build_bundle(shot, asset_registry=_registry())
    tail = bundle["references"][-2:]
    assert tail[0] == {
        "role": "character",
        "asset_id": "CH_B",
        "block": "旅人乙：深色外衣、束发、瘦长身形",
        "source": "costume_variant:identity",
    }
    assert tail[1] == {
        "role": "costume",
        "asset_id": "CH_B_rain",
        "block": "雨天蓑衣",
        "source": "costume_variant:style",
    }
    # The identity block is the registry block, not the new outfit.
    assert "雨天蓑衣" not in tail[0]["block"]
    assert "深色外衣" not in tail[1]["block"]


def test_costume_variant_missing_identity_and_outfit_marked_missing():
    shot = _shot(
        costume_variant={"character_id": "CH_MISSING", "variant_id": "V_X"},
    )
    bundle = build_bundle(shot, asset_registry=_registry())
    tail = bundle["references"][-2:]
    assert tail[0]["block"] == "[缺失]"
    assert tail[1]["block"] == "[缺失]"
    assert bundle["warnings"], "missing identity/outfit must be warned, not invented"


def test_missing_shot_id_raises():
    with pytest.raises(CapabilityError):
        build_bundle({"scene_id": "SC_A"}, asset_registry=_registry())


def test_registry_not_a_dict_raises():
    with pytest.raises(CapabilityError):
        build_bundle(_shot(), asset_registry=["CH_A"])


def test_unknown_character_raises():
    with pytest.raises(CapabilityError):
        build_bundle(
            _shot(character_ids=["CH_A", "CH_NOPE"]), asset_registry=_registry()
        )


def test_unknown_scene_raises():
    with pytest.raises(CapabilityError):
        build_bundle(_shot(scene_id="SC_NOPE"), asset_registry=_registry())


def test_validate_unknown_asset_is_error():
    bundle = {
        "shot_id": "SH01",
        "character_ids": [],
        "references": [
            {"role": "prop", "asset_id": "PROP_NOPE", "block": "x", "source": "prop_ids"}
        ],
    }
    issues = validate_bundle(bundle, asset_registry=_registry())
    found = _issues_by_code(issues, "unknown_asset")
    assert len(found) == 1 and found[0]["severity"] == "error"
    assert found[0]["asset_id"] == "PROP_NOPE"


def test_validate_role_kind_mismatch_is_error():
    bundle = {
        "shot_id": "SH01",
        "character_ids": [],
        "references": [
            {"role": "scene", "asset_id": "CH_A", "block": "x", "source": "character_ids"}
        ],
    }
    issues = validate_bundle(bundle, asset_registry=_registry())
    found = _issues_by_code(issues, "role_kind_mismatch")
    assert len(found) == 1 and found[0]["severity"] == "error"


def test_validate_character_missing_face_anchors_is_warning():
    registry = _registry()
    del registry["CH_A"]["face_anchors"]
    bundle = build_bundle(_shot(), asset_registry=registry)
    issues = validate_bundle(bundle, asset_registry=registry)
    found = _issues_by_code(issues, "missing_face_anchors")
    assert len(found) == 1 and found[0]["severity"] == "warning"
    assert found[0]["asset_id"] == "CH_A"


def test_validate_duplicate_asset_is_warning():
    bundle = build_bundle(_shot(), asset_registry=_registry())
    bundle["references"].append(dict(bundle["references"][0]))
    issues = validate_bundle(bundle, asset_registry=_registry())
    found = _issues_by_code(issues, "duplicate_asset")
    assert len(found) == 1 and found[0]["severity"] == "warning"
    assert found[0]["asset_id"] == "CH_A"


def test_validate_character_listed_without_reference_is_error():
    bundle = {
        "shot_id": "SH01",
        "character_ids": ["CH_A", "CH_B"],
        "references": [
            {
                "role": "character",
                "asset_id": "CH_A",
                "block": "旅人甲：灰色斗篷、短发、圆脸",
                "source": "character_ids",
            },
            {
                "role": "scene",
                "asset_id": "SC_A",
                "block": "路边小屋：木门、石桌、门廊灯火",
                "source": "scene_id",
            },
        ],
    }
    issues = validate_bundle(bundle, asset_registry=_registry())
    found = _issues_by_code(issues, "missing_character_reference")
    assert len(found) == 1 and found[0]["severity"] == "error"
    assert found[0]["asset_id"] == "CH_B"


def test_output_is_json_serializable():
    bundle = build_bundle(
        _shot(
            costume_variant={
                "character_id": "CH_B",
                "outfit": "雨天蓑衣",
                "variant_id": "CH_B_rain",
            }
        ),
        asset_registry=_registry(),
    )
    text = json.dumps(bundle, ensure_ascii=False)
    parsed = json.loads(text)
    assert parsed["shot_id"] == "SH01"
    assert len(parsed["references"]) == 6
    issues = validate_bundle(parsed, asset_registry=_registry())
    # The costume identity duplicates the regular CH_B reference, which
    # is a warning by design, never an error.
    assert not [i for i in issues if i["severity"] == "error"]
